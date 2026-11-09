#pragma once
#include "roaring.h"
#include <memory>

namespace pages {
using Bitmap = std::unique_ptr<roaring_bitmap_t, decltype(&roaring_bitmap_free)>;
inline Bitmap make_bitmap() {
    Bitmap b(roaring_bitmap_create(), roaring_bitmap_free);
    if (!b)
        throw std::bad_alloc();
    return b;
}


inline std::vector<Count> bitmap_counts(const GroupDirectory &dir, const std::vector<Region> &spans,
                                        const std::vector<WordClause> &clauses, unsigned base,
                                        size_t n, size_t l, size_t r, bool roaring) {
    std::vector<Count> result(dir.keys().size());
    for (size_t g = 0; g < result.size(); ++g)
        result[g] = base * dir.counts()[g];
    std::vector<Bitmap> groups;
    if (roaring && !clauses.empty()) {
        require(n <= UINT32_MAX, "row group exceeds bitmap position range");
        for (size_t g = 0; g < result.size(); ++g)
            groups.push_back(make_bitmap());
        for (size_t i = 0; i < spans.size(); ++i)
            roaring_bitmap_add_range(groups[dir.owner(i)].get(), spans[i].begin, spans[i].end);
        for (auto &g : groups)
            roaring_bitmap_run_optimize(g.get());
    }
    std::vector<Word> words((n + 63) / 64);
    for (const auto &clause : clauses) {
        size_t ones = 0;
        for (size_t w = l / 64; w <= (r - 1) / 64; ++w) {
            size_t a = std::max(l, w * 64), b = std::min(r, w * 64 + 64);
            words[w] = clause.value(w) & (low(unsigned(b - a)) << (a % 64));
            ones += std::popcount(words[w]);
        }
        if (roaring) {
            bool flip = ones > (r - l) / 2;
            auto mask = make_bitmap();
            for (size_t w = l / 64; w <= (r - 1) / 64; ++w) {
                size_t a = std::max(l, w * 64), b = std::min(r, w * 64 + 64);
                Word bits = words[w];
                if (flip)
                    bits ^= low(unsigned(b - a)) << (a % 64);
                while (bits) {
                    unsigned first = std::countr_zero(bits), len = std::countr_one(bits >> first);
                    roaring_bitmap_add_range(mask.get(), 64 * w + first, 64 * w + first + len);
                    bits &= ~(low(len) << first);
                }
            }
            roaring_bitmap_run_optimize(mask.get());
            for (size_t g = 0; g < groups.size(); ++g) {
                auto x = Count(roaring_bitmap_and_cardinality(groups[g].get(), mask.get()));
                result[g] += flip ? dir.counts()[g] - x : x;
            }
        } else {
            std::vector<Count> sums(words.size() + 1);
            for (size_t w = l / 64; w <= (r - 1) / 64; ++w)
                sums[w + 1] = sums[w] + std::popcount(words[w]);
            auto rank = [&](size_t p) {
                return sums[p / 64] +
                       (p % 64 ? std::popcount(words[p / 64] & low(unsigned(p % 64))) : 0);
            };
            auto prior = rank(l);
            for (size_t i = 0; i < spans.size(); ++i) {
                auto next = rank(spans[i].end);
                result[dir.owner(i)] += next - prior;
                prior = next;
            }
        }
    }
    return result;
}
}
