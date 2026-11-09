#pragma once


namespace pages {
inline std::vector<Word> null_words(parquet::RowGroupReader &group, int col, size_t n,
                                    bool optional) {
    std::vector<Word> out((n + 63) / 64);
    if (!optional)
        return out;
    auto reader = group.GetColumnPageReader(col);
    size_t pos = 0;
    while (auto base = reader->NextPage()) {
        if (!data_page(base->type()))
            continue;
        auto &page = static_cast<parquet::DataPage &>(*base);
        require(page.num_values() >= 0 && size_t(page.num_values()) <= n - pos,
                "invalid level count");
        size_t left = size_t(page.num_values());
        auto data = split(page, true).levels;
        while (left) {
            const auto header = data.varint();
            size_t units = header >> 1;
            require(units > 0, "empty packed level run");
            if (!(header & 1)) {
                require(units <= left, "invalid level repetition");
                auto bit = data.little(1);
                require(bit <= 1, "invalid definition level");
                if (!bit)
                    mark(out, pos, pos + units);
                pos += units;
                left -= units;
                continue;
            }
            const auto *ptr = data.take(units);
            size_t count = std::min(left, 8 * units);
            require(8 * units - count < 8, "invalid packed level padding");
            left -= count;
            while (count) {
                unsigned size = unsigned(std::min(count, size_t(64)));
                Word value = 0;
                std::memcpy(&value, ptr, (size + 7) / 8);
                value = (~value) & low(size);
                auto shift = unsigned(pos % 64);
                out[pos / 64] |= value << shift;
                if (size > 64 - shift)
                    out[pos / 64 + 1] |= value >> (64 - shift);
                ptr += (size + 7) / 8;
                pos += size;
                count -= size;
            }
        }
    }
    require(pos == n, "incomplete level stream");
    return out;
}

inline const auto byte_lanes = [] {
    std::array<Word, 256> table{};
    for (unsigned m = 0; m < 256; ++m)
        for (unsigned j = 0; j < 8; ++j)
            table[m] |= Word((m >> j) & 1u) << (8 * j);
    return table;
}();

struct WordClause {
    std::vector<std::pair<const std::vector<Word> *, bool>> masks;
    Word value(size_t w) const {
        Word bits = ~Word(0);
        for (auto [mask, want_null] : masks)
            bits &= want_null ? (*mask)[w] : ~(*mask)[w];
        return bits;
    }
};


inline std::vector<Count> packed_counts(const GroupDirectory &dir, const std::vector<Region> &keys,
                                        const std::vector<WordClause> &clauses, unsigned constant,
                                        size_t l, size_t r, bool adapt, bool permit_sign,
                                        size_t pivot = SIZE_MAX) {
    std::vector<Count> sums(dir.keys().size());
    size_t j = 0;
    for (size_t g = 0; g < sums.size(); ++g)
        sums[g] = constant * dir.counts()[g];
    for (size_t w = l / 64; w <= (r - 1) / 64; ++w) {
        size_t start = std::max(l, w * 64), stop = std::min(r, w * 64 + 64);
        Word active = low(unsigned(stop - start)) << (start % 64);
        auto first = j;
        while (keys[j].end < stop)
            ++j;
        auto last = j;
        if (keys[j].end == stop && stop < r)
            ++j;
        if (first == last && dir.owner(first) == pivot)
            continue;
        unsigned base = 0, exceptions = 0, used = 0;
        Count total = 0;
        std::array<Word, 64> bits{};
        for (const auto &clause : clauses) {
            Word mask = clause.value(w) & active;
            if (mask == active) {
                ++base;
                continue;
            }
            if (!mask)
                continue;
            auto hits = unsigned(std::popcount(mask));
            total += hits;
            exceptions += permit_sign ? std::min(hits, unsigned(stop - start) - hits) : hits;
            bits[used++] = mask;
        }
        if (adapt && first == last) {
            sums[dir.owner(first)] += base * Count(stop - start) + total;
            continue;
        }
        if (adapt && used && exceptions <= (last - first + 1) * used && exceptions <= 16) {
            for (unsigned h = 0; h < used; ++h) {
                Word v = bits[h];
                int sign = 1;
                if (permit_sign && std::popcount(v) * 2 > int(stop - start)) {
                    v ^= active;
                    ++base;
                    sign = -1;
                }
                while (v) {
                    auto pos = w * 64 + std::countr_zero(v);
                    sums[dir.owner(dir.at(pos))] += sign;
                    v &= v - 1;
                }
            }
            used = 0;
        }
        bool boundaries = adapt && (last - first + 1 <= 4 || !used);
        std::array<Word, 8> lanes{};
        if (!boundaries) {
            for (unsigned h = 0; h < used; ++h)
                for (unsigned b = 0; b < 8; ++b)
                    lanes[b] += byte_lanes[(bits[h] >> (8 * b)) & 255];
        }
        for (size_t k = first; k <= last; ++k) {
            auto a = std::max(start, keys[k].begin), b = std::min(stop, keys[k].end);
            Count value = base * Count(b - a);
            if (boundaries) {
                Word selector = low(unsigned(b - a)) << (a % 64);
                for (unsigned h = 0; h < used; ++h)
                    value += std::popcount(bits[h] & selector);
            } else
                for (size_t p = a; p < b; ++p)
                    value += (lanes[(p % 64) / 8] >> (8 * (p % 8))) & 255;
            sums[dir.owner(k)] += value;
        }
    }
    return sums;
}
}
