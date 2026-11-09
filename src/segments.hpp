#pragma once
#include <array>
#include <cstddef>
#include <vector>
#include <algorithm>
#include <cstdint>
#include <limits>

namespace pages {
struct Segment {
    unsigned begin, end, omit;
};
struct SegmentPlan {
    int cost = 0;
    std::vector<Segment> parts;
};


inline SegmentPlan plan_segments(const unsigned *keys, const int *direct, const int *prefix,
                                 unsigned count, bool allow_anchors) {
    std::array<int, 65> optimum{};
    std::array<unsigned, 65> previous{}, omitted{};
    for (unsigned b = 1; b <= count; ++b) {
        optimum[b] = std::numeric_limits<int>::max();
        std::array<int, 64> by_group{};
        int total = 0, best = 0;
        unsigned candidate = keys[b - 1];
        for (unsigned a = b; a-- > 0;) {
            unsigned group = keys[a];
            total += direct[a];
            int saved = (by_group[group] += direct[a]);
            if (saved > best) {
                best = saved;
                candidate = group;
            }
            if (!allow_anchors && a)
                continue;
            int price = optimum[a] + total - best + (b == count ? 0 : prefix[b]);
            if (price < optimum[b]) {
                optimum[b] = price;
                previous[b] = a;
                omitted[b] = candidate;
            }
        }
    }
    SegmentPlan result;
    result.cost = optimum[count];
    for (unsigned b = count; b; b = previous[b])
        result.parts.push_back({previous[b], b, omitted[b]});
    std::reverse(result.parts.begin(), result.parts.end());
    return result;
}

struct Shape {
    std::array<uint8_t, 12> ids{};
    uint8_t count = 0;
    bool operator==(const Shape &) const = default;
};
struct ShapeHash {
    std::size_t operator()(const Shape &shape) const noexcept {
        std::size_t h = shape.count;
        for (unsigned j = 0; j < shape.count; ++j)
            h = (h ^ shape.ids[j]) * 16777619u;
        return h;
    }
};
}
