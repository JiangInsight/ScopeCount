

#define DUCKDB_EXTENSION_NAME scopefused
#include "duckdb_extension.h"
DUCKDB_EXTENSION_EXTERN
#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#if defined(__AVX2__)
#include <immintrin.h>
#endif

namespace fused {
using Key = uint32_t;
using Word = uint64_t;
constexpr size_t dense_limit = 4096;

template <size_t W> using Counts = std::array<Word, W + 1>;

template <size_t W> struct Groups {
    std::vector<Counts<W>> direct;
    std::unordered_map<Key, Counts<W>> other;

    Counts<W> &counter(Key key) {
        if (key >= dense_limit)
            return other[key];
        if (key >= direct.size())
            direct.resize(std::min(dense_limit, std::bit_ceil(static_cast<size_t>(key) + 1)));
        return direct[key];
    }
    template <class Fn> void each(Fn visit) const {
        for (size_t k = 0; k < direct.size(); ++k)
            if (direct[k][0])
                visit(Key(k), direct[k]);
        for (const auto &[k, v] : other)
            visit(k, v);
    }
};

Word mask_for(size_t n) { return n == 64 ? ~Word(0) : (Word(1) << n) - 1; }

template <size_t W>
void scatter(Groups<W> &groups, const Key *keys, size_t length, Word kept,
             const std::array<Word, W> &present) {

    const bool all = kept == mask_for(length);
    for (size_t k = 0; k < length; ++k) {
        if (!all && !(kept >> k & 1))
            continue;
        auto &counts = groups.counter(keys[k]);
        ++counts[0];
        for (size_t j = 0; j < W; ++j)
            counts[j + 1] += present[j] >> k & 1;
    }
}



Word transitions(const Key *keys, size_t n) {
    Word starts = 1;
    size_t i = 1;
#if defined(__AVX2__)
    for (; i + 8 <= n; i += 8) {
        auto current = _mm256_loadu_si256(reinterpret_cast<const __m256i *>(keys + i));
        auto prior = _mm256_loadu_si256(reinterpret_cast<const __m256i *>(keys + i - 1));
        auto equal = _mm256_cmpeq_epi32(current, prior);
        unsigned changed = (~_mm256_movemask_ps(_mm256_castsi256_ps(equal))) & 255;
        starts |= Word(changed) << i;
    }
#endif
    for (; i < n; ++i)
        starts |= Word(keys[i] != keys[i - 1]) << i;
    return starts;
}

template <size_t W>
void add_range(Counts<W> &counts, Word selected, const std::array<Word, W> &present) {
    counts[0] += std::popcount(selected);
    for (size_t j = 0; j < W; ++j)
        counts[j + 1] += std::popcount(selected & present[j]);
}



bool constant_key(const Key *keys, size_t n) {
    size_t i = 0;
#if defined(__AVX2__)
    const auto pivot = _mm256_set1_epi32(static_cast<int32_t>(keys[0]));
    for (; i + 32 <= n; i += 32) {
        auto v0 = _mm256_xor_si256(pivot,
                                   _mm256_loadu_si256(reinterpret_cast<const __m256i *>(keys + i)));
        auto v1 = _mm256_xor_si256(
            pivot, _mm256_loadu_si256(reinterpret_cast<const __m256i *>(keys + i + 8)));
        auto v2 = _mm256_xor_si256(
            pivot, _mm256_loadu_si256(reinterpret_cast<const __m256i *>(keys + i + 16)));
        auto v3 = _mm256_xor_si256(
            pivot, _mm256_loadu_si256(reinterpret_cast<const __m256i *>(keys + i + 24)));
        auto any = _mm256_or_si256(_mm256_or_si256(v0, v1), _mm256_or_si256(v2, v3));
        if (!_mm256_testz_si256(any, any))
            return false;
    }
#endif
    for (; i < n; ++i)
        if (keys[i] != keys[0])
            return false;
    return true;
}
bool all_keys_valid(const Word *valid, size_t n) {
    if (!valid)
        return true;
    size_t i = 0;
    for (; i + 64 <= n; i += 64)
        if (valid[i / 64] != ~Word(0))
            return false;
    return i == n || (valid[i / 64] & mask_for(n - i)) == mask_for(n - i);
}
template <size_t W>
void reduce_uniform(Counts<W> &counts, size_t n, const std::array<const Word *, W> &validity) {
    counts[0] += n;
    for (size_t j = 0; j < W; ++j) {
        const Word *bits = validity[j];
        if (!bits) {
            counts[j + 1] += n;
            continue;
        }
        size_t i = 0;
        Word sum = 0;
        for (; i + 64 <= n; i += 64)
            sum += std::popcount(bits[i / 64]);
        if (i < n)
            sum += std::popcount(bits[i / 64] & mask_for(n - i));
        counts[j + 1] += sum;
    }
}
template <size_t W>
void scalar_stream(Groups<W> &groups, const Key *keys, size_t n,
                   const std::array<const Word *, W> &validity) {
    size_t first = 0;
    while (first < n) {
        size_t i = first;
        Counts<W> local{};
        do {
            ++local[0];
            for (size_t j = 0; j < W; ++j)
                local[j + 1] += validity[j] ? (validity[j][i / 64] >> (i % 64)) & 1 : 1;
            ++i;
        } while (i < n && keys[i] == keys[first]);
        auto &counters = groups.counter(keys[first]);
        for (size_t j = 0; j <= W; ++j)
            counters[j] += local[j];
        first = i;
    }
}
template <size_t W, int mode>
void update(duckdb_function_info info, duckdb_data_chunk input, duckdb_aggregate_state *states) {
    try {
        size_t n = duckdb_data_chunk_get_size(input);
        if (!n)
            return;
        auto column = duckdb_data_chunk_get_vector(input, 0);
        auto *keys = static_cast<const Key *>(duckdb_vector_get_data(column));
        auto *key_valid = duckdb_vector_get_validity(column);
        std::array<const Word *, W> validity;
        for (size_t j = 0; j < W; ++j)
            validity[j] = duckdb_vector_get_validity(duckdb_data_chunk_get_vector(input, j + 1));


        bool shared = std::memcmp(states, states + 1, (n - 1) * sizeof(*states)) == 0;
        if constexpr (mode != 0) {
            if (shared && all_keys_valid(key_valid, n)) {
                auto &groups = *reinterpret_cast<Groups<W> *>(states[0]);
                if constexpr (mode == 2) {
                    scalar_stream<W>(groups, keys, n, validity);
                    return;
                }
                if (constant_key(keys, n)) {
                    reduce_uniform<W>(groups.counter(keys[0]), n, validity);
                    return;
                }
            }
        }
        for (size_t pos = 0; pos < n; pos += 64) {
            size_t width = std::min(size_t(64), n - pos);
            Word active = mask_for(width);
            Word kept = active & (key_valid ? key_valid[pos / 64] : ~Word(0));
            if (!kept)
                continue;
            std::array<Word, W> present;
            for (size_t j = 0; j < W; ++j)
                present[j] = validity[j] ? validity[j][pos / 64] : ~Word(0);
            if (!shared) {
                while (kept) {
                    unsigned k = std::countr_zero(kept);
                    auto &c =
                        reinterpret_cast<Groups<W> *>(states[pos + k])->counter(keys[pos + k]);
                    ++c[0];
                    for (size_t j = 0; j < W; ++j)
                        c[j + 1] += present[j] >> k & 1;
                    kept &= kept - 1;
                }
                continue;
            }
            auto &groups = *reinterpret_cast<Groups<W> *>(states[0]);
            if constexpr (mode == 1) {


                if (kept == active) {
                    Word breaks = transitions(keys + pos, width);
                    if (std::popcount(breaks) <= 8) {
                        while (breaks) {
                            size_t first = std::countr_zero(breaks);
                            breaks &= breaks - 1;
                            size_t last = breaks ? std::countr_zero(breaks) : width;
                            add_range<W>(groups.counter(keys[pos + first]),
                                         mask_for(last) & ~mask_for(first), present);
                        }
                        continue;
                    }
                }
            }
            scatter<W>(groups, keys + pos, width, kept, present);
        }
    } catch (const std::exception &e) {
        duckdb_aggregate_function_set_error(info, e.what());
    }
}

template <size_t W> idx_t state_size(duckdb_function_info) { return sizeof(Groups<W>); }
template <size_t W> void init(duckdb_function_info, duckdb_aggregate_state s) {
    new (s) Groups<W>();
}
template <size_t W> void destroy(duckdb_aggregate_state *states, idx_t n) {
    for (idx_t i = 0; i < n; ++i)
        reinterpret_cast<Groups<W> *>(states[i])->~Groups<W>();
}
template <size_t W>
void combine(duckdb_function_info info, duckdb_aggregate_state *src, duckdb_aggregate_state *dst,
             idx_t n) {
    try {
        for (idx_t i = 0; i < n; ++i) {
            auto &to = *reinterpret_cast<Groups<W> *>(dst[i]);
            reinterpret_cast<Groups<W> *>(src[i])->each([&](Key k, const Counts<W> &values) {
                auto &out = to.counter(k);
                for (size_t j = 0; j <= W; ++j)
                    out[j] += values[j];
            });
        }
    } catch (const std::exception &e) {
        duckdb_aggregate_function_set_error(info, e.what());
    }
}
template <size_t W>
void finalize(duckdb_function_info info, duckdb_aggregate_state *states, duckdb_vector out, idx_t n,
              idx_t offset) {
    try {
        auto entries = static_cast<duckdb_list_entry *>(duckdb_vector_get_data(out));
        idx_t next = duckdb_list_vector_get_size(out);
        for (idx_t i = 0; i < n; ++i) {
            auto &s = *reinterpret_cast<Groups<W> *>(states[i]);
            idx_t count = s.other.size();
            for (const auto &c : s.direct)
                count += c[0] != 0;
            entries[offset + i] = {next, count};
            if (duckdb_list_vector_reserve(out, next + count) != DuckDBSuccess ||
                duckdb_list_vector_set_size(out, next + count) != DuckDBSuccess)
                throw std::bad_alloc();
            auto records = duckdb_list_vector_get_child(out);
            auto keys = static_cast<Key *>(
                duckdb_vector_get_data(duckdb_struct_vector_get_child(records, 0)));
            std::array<Word *, W + 1> outputs;
            for (size_t j = 0; j <= W; ++j)
                outputs[j] = static_cast<Word *>(
                    duckdb_vector_get_data(duckdb_struct_vector_get_child(records, j + 1)));
            s.each([&](Key key, const Counts<W> &c) {
                keys[next] = key;
                for (size_t j = 0; j <= W; ++j)
                    outputs[j][next] = c[j];
                ++next;
            });
        }
    } catch (const std::exception &e) {
        duckdb_aggregate_function_set_error(info, e.what());
    }
}
#include "word_cover.hpp"
template <size_t W, int mode> void install(duckdb_connection con) {
    auto fn = duckdb_create_aggregate_function();
    auto key = duckdb_create_logical_type(DUCKDB_TYPE_UINTEGER);
    auto col = duckdb_create_logical_type(DUCKDB_TYPE_BOOLEAN);
    auto count = duckdb_create_logical_type(DUCKDB_TYPE_UBIGINT);
    constexpr size_t fields = mode >= 3 ? 1 : W;
    std::array<duckdb_logical_type, fields + 2> types;
    types.fill(count);
    types[0] = key;
    std::array<std::string, fields + 2> labels;
    labels[0] = "key";
    labels[1] = "n";
    std::array<const char *, fields + 2> names;
    for (size_t j = 0; j < fields; ++j)
        labels[j + 2] = "c" + std::to_string(j + 1);
    for (size_t j = 0; j < fields + 2; ++j)
        names[j] = labels[j].c_str();
    auto st = duckdb_create_struct_type(types.data(), names.data(), fields + 2);
    auto result = duckdb_create_list_type(st);
    std::string name = (mode == 5   ? "scope_wmargin"
                        : mode == 6 ? "scope_wliteral"
                        : mode == 3 ? "scope_weight"
                        : mode == 4 ? "scope_wrows"
                        : mode == 1 ? "scope_runs"
                        : mode == 2 ? "scope_stream"
                                    : "scope_rows") +
                       std::to_string(W);
    duckdb_aggregate_function_set_name(fn, name.c_str());
    duckdb_aggregate_function_add_parameter(fn, key);
    for (size_t j = 0; j < W; ++j)
        duckdb_aggregate_function_add_parameter(fn, col);
    duckdb_aggregate_function_set_return_type(fn, result);
    duckdb_aggregate_function_set_special_handling(fn);
    if constexpr (mode >= 3)
        duckdb_aggregate_function_set_functions(fn, state_size<1>, init<1>,
                                                weight_update<W, mode != 4, mode == 3, mode != 6>,
                                                combine<1>, finalize<1>);
    else
        duckdb_aggregate_function_set_functions(fn, state_size<W>, init<W>, update<W, mode>,
                                                combine<W>, finalize<W>);
    duckdb_aggregate_function_set_destructor(fn, destroy<fields>);
    auto status = duckdb_register_aggregate_function(con, fn);
    duckdb_destroy_aggregate_function(&fn);
    for (auto *t : {&result, &st, &count, &col, &key})
        duckdb_destroy_logical_type(t);
    if (status != DuckDBSuccess)
        throw std::runtime_error("Could not install " + name);
}
template <size_t W> void both(duckdb_connection con) {
    install<W, 0>(con);
    install<W, 1>(con);
    install<W, 2>(con);
    install<W, 3>(con);
    install<W, 4>(con);
    install<W, 5>(con);
    install<W, 6>(con);
}
}
DUCKDB_EXTENSION_ENTRYPOINT(duckdb_connection con, duckdb_extension_info info,
                            struct duckdb_extension_access *access) {
    try {
        fused::both<1>(con);
        fused::both<2>(con);
        fused::both<3>(con);
        fused::both<4>(con);
        fused::both<5>(con);
        fused::both<6>(con);
        fused::both<7>(con);
        fused::both<8>(con);
        fused::both<9>(con);
        fused::both<10>(con);
        fused::both<11>(con);
        fused::both<12>(con);
        fused::both<13>(con);
        fused::both<14>(con);
        fused::both<15>(con);
        fused::both<16>(con);
        fused::both<17>(con);
        fused::both<18>(con);
        fused::both<19>(con);
        fused::both<20>(con);
        fused::both<21>(con);
        fused::both<22>(con);
        fused::both<23>(con);
        fused::both<24>(con);
        return true;
    } catch (const std::exception &e) {
        access->set_error(info, e.what());
        return false;
    }
}
