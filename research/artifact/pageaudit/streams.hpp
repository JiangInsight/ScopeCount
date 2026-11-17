#pragma once
#include <algorithm>
#include <bit>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <vector>
#include <parquet/column_page.h>
#include <parquet/column_reader.h>
#include <parquet/file_reader.h>

namespace pages {
using Word = uint64_t;
using Count = int64_t;
constexpr Count missing_key = std::numeric_limits<Count>::min();
inline void require(bool ok, const char *why) {
    if (!ok)
        throw std::invalid_argument(why);
}
inline Word low(unsigned n) { return n == 64 ? ~Word(0) : (Word(1) << n) - 1; }

struct Bytes {
    const uint8_t *p;
    size_t n;
    const uint8_t *take(size_t k) {
        require(k <= n, "truncated Parquet byte stream");
        auto out = p;
        p += k;
        n -= k;
        return out;
    }
    uint32_t little(unsigned k) {
        uint32_t x = 0;
        require(k <= 4, "invalid integer width");
        std::memcpy(&x, take(k), k);
        return x;
    }
    uint32_t varint() {
        uint32_t x = 0;
        for (unsigned shift = 0; shift <= 28; shift += 7) {
            auto b = little(1);
            require(shift < 28 || b < 16, "RLE header overflow");
            x |= (b & 127) << shift;
            if (!(b & 128))
                return x;
        }
        throw std::invalid_argument("bad RLE header");
    }
};


template <class Fn> void decode(Bytes stream, unsigned width, size_t count, Fn &&emit) {
    require(width <= 32, "unsupported bit width");
    while (count) {
        auto hdr = stream.varint();
        size_t len = hdr >> 1;
        require(len > 0, "zero run");
        if (!(hdr & 1)) {
            uint32_t v = stream.little((width + 7) / 8);
            require(len <= count, "RLE extends past page");
            emit(v, len);
            count -= len;
        } else {
            require(len <= SIZE_MAX / 32, "oversize literal run");
            auto raw = stream.take(len * width);
            auto num = std::min(count, len * 8);
            require(len * 8 - num < 8, "invalid bit-pack padding");
            uint64_t bits = 0;
            unsigned avail = 0;
            for (size_t i = 0; i < num; ++i) {
                while (avail < width) {
                    bits |= uint64_t(*raw++) << avail;
                    avail += 8;
                }
                emit(uint32_t(bits & low(width)), 1);
                bits >>= width;
                avail -= width;
            }
            count -= num;
        }
    }
}
struct Region {
    Count key;
    size_t begin, end;
};
inline void append(std::vector<Region> &runs, Count key, size_t begin, size_t len) {
    if (!len)
        return;
    if (!runs.empty() && runs.back().key == key && runs.back().end == begin)
        runs.back().end += len;
    else
        runs.push_back({key, begin, begin + len});
}
struct PageParts {
    Bytes levels, values;
};
inline PageParts split(const parquet::DataPage &page, bool optional) {
    require(page.size() >= 0 && page.num_values() >= 0, "negative page length");
    Bytes bytes{page.data(), size_t(page.size())};
    size_t length = 0;
    if (page.type() == parquet::PageType::DATA_PAGE_V2) {
        auto &v = static_cast<const parquet::DataPageV2 &>(page);
        require(v.repetition_levels_byte_length() == 0 && v.definition_levels_byte_length() >= 0,
                "nested levels");
        length = v.definition_levels_byte_length();
    } else if (optional) {
        auto &v = static_cast<const parquet::DataPageV1 &>(page);
        require(v.definition_level_encoding() == parquet::Encoding::RLE,
                "unsupported definition encoding");
        length = bytes.little(4);
    }
    const auto *p = bytes.take(length);
    return {{p, length}, bytes};
}
inline bool data_page(parquet::PageType::type t) {
    return t == parquet::PageType::DATA_PAGE || t == parquet::PageType::DATA_PAGE_V2;
}
inline std::vector<Region> levels(parquet::RowGroupReader &group, int col, size_t n,
                                  bool optional) {
    if (!optional)
        return {{1, 0, n}};
    auto reader = group.GetColumnPageReader(col);
    std::vector<Region> runs;
    size_t pos = 0;
    while (auto base = reader->NextPage()) {
        if (!data_page(base->type()))
            continue;
        auto &page = static_cast<parquet::DataPage &>(*base);
        auto parts = split(page, true);
        decode(parts.levels, 1, page.num_values(), [&](auto value, size_t len) {
            append(runs, value, pos, len);
            pos += len;
        });
    }
    require(pos == n, "definition stream has wrong row count");
    return runs;
}
inline std::vector<Region> groups(parquet::RowGroupReader &group, int col, size_t n, bool optional,
                                  bool unsigned_key) {
    if (col < 0)
        return {{0, 0, n}};
    auto reader = group.GetColumnPageReader(col);
    std::vector<Count> dict;
    std::vector<Region> result;
    size_t pos = 0;
    auto key = [&](uint32_t x) -> Count {
        return unsigned_key ? Count(x) : Count(std::bit_cast<int32_t>(x));
    };
    while (auto base = reader->NextPage()) {
        if (base->type() == parquet::PageType::DICTIONARY_PAGE) {
            auto &page = static_cast<parquet::DictionaryPage &>(*base);
            Bytes raw{page.data(), size_t(page.size())};
            require(page.encoding() == parquet::Encoding::PLAIN ||
                        page.encoding() == parquet::Encoding::PLAIN_DICTIONARY,
                    "key dictionary encoding");
            for (int i = 0; i < page.num_values(); ++i)
                dict.push_back(key(raw.little(4)));
            continue;
        }
        if (!data_page(base->type()))
            continue;
        auto &page = static_cast<parquet::DataPage &>(*base);
        auto parts = split(page, optional);
        size_t length = page.num_values(), present = 0;
        std::vector<Region> def;
        if (optional)
            decode(parts.levels, 1, length, [&](auto v, size_t k) {
                size_t j = def.empty() ? 0 : def.back().end;
                append(def, v, j, k);
                present += v ? k : 0;
            });
        else {
            def.push_back({1, 0, length});
            present = length;
        }
        size_t j = 0, at = 0;
        auto skips = [&]() {
            while (j < def.size() && !def[j].key) {
                size_t m = def[j].end - at;
                append(result, missing_key, pos, m);
                pos += m;
                at += m;
                ++j;
            }
        };
        auto emit = [&](Count v, size_t len) {
            while (len) {
                skips();
                require(j < def.size(), "too many group keys");
                auto m = std::min(len, def[j].end - at);
                append(result, v, pos, m);
                pos += m;
                at += m;
                len -= m;
                if (at == def[j].end)
                    ++j;
            }
        };
        if (present) {
            if (page.encoding() == parquet::Encoding::RLE_DICTIONARY ||
                page.encoding() == parquet::Encoding::PLAIN_DICTIONARY) {
                unsigned width = parts.values.little(1);
                decode(parts.values, width, present, [&](auto id, size_t len) {
                    require(id < dict.size(), "bad dictionary id");
                    emit(dict[id], len);
                });
            } else if (page.encoding() == parquet::Encoding::PLAIN) {
                for (size_t k = 0; k < present; ++k)
                    emit(key(parts.values.little(4)), 1);
            } else
                throw std::invalid_argument("unsupported grouping-key encoding");
        }
        skips();
        require(at == length, "key definition mismatch");
    }
    require(pos == n, "group stream has wrong row count");
    return result;
}
}
