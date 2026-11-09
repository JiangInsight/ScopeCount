#pragma once
#include "segments.hpp"
#include <unordered_map>
namespace pages {


struct EndpointAnswer {
    Count n = 0, score = 0;
};
inline const auto lanes16 = [] {
    std::array<Word, 16> values{};
    for (unsigned m = 0; m < 16; ++m)
        for (unsigned j = 0; j < 4; ++j)
            values[m] |= Word((m >> j) & 1) << (16 * j);
    return values;
}();
inline void project_endpoints(const std::vector<Region> &spans,
                              const std::vector<WordClause> &clauses, unsigned fixed, size_t l,
                              size_t r, unsigned materialization_threshold, unsigned segment_mode,
                              Answers &output) {
    Count lo = INT64_MAX, hi = INT64_MIN;
    for (const auto &s : spans)
        if (s.key != missing_key) {
            lo = std::min(lo, s.key);
            hi = std::max(hi, s.key);
        }
    bool compact = lo <= hi && hi - lo < 65536;
    std::vector<EndpointAnswer> direct(compact ? size_t(hi - lo) + 2 : 0);
    std::map<Count, EndpointAnswer> other;
    auto counter = [&](Count k) -> EndpointAnswer & {
        if (compact)
            return direct[k == missing_key ? 0 : 1 + size_t(k - lo)];
        return other[k];
    };
    std::unordered_map<Shape, SegmentPlan, ShapeHash> plans;
    size_t index = 0;
    for (size_t w = l / 64; w <= (r - 1) / 64; ++w) {
        auto a = std::max(l, w * 64), b = std::min(r, w * 64 + 64);
        unsigned off = unsigned(a % 64), width = unsigned(b - a);
        Word active = low(width) << off;
        size_t first = index;
        while (spans[index].end < b)
            ++index;
        size_t last = index;
        if (spans[index].end == b && b < r)
            ++index;
        unsigned bias = fixed, used = 0, pop = 0;
        std::array<Word, 64> forms{};
        for (const auto &clause : clauses) {
            Word x = clause.value(w) & active;
            if (x == active) {
                ++bias;
                continue;
            }
            if (x) {
                forms[used++] = x >> off;
                pop += std::popcount(x);
            }
        }
        auto cuts = last - first;
        if (materialization_threshold && !cuts) {
            auto &dst = counter(spans[first].key);
            dst.n += width;
            dst.score += bias * width + pop;
            continue;
        }
        if (segment_mode && used && cuts > 0 && cuts < 12) {
            Shape shape;
            shape.count = uint8_t(cuts + 1);
            std::array<Count, 12> names{};
            std::array<unsigned, 12> ids{}, ends{};
            std::array<int, 13> prices{};
            prices.fill(1);
            unsigned distinct = 0;
            for (unsigned t = 0; t < shape.count; ++t) {
                auto key = spans[first + t].key;
                unsigned g = 0;
                while (g < distinct && names[g] != key)
                    ++g;
                if (g == distinct)
                    names[distinct++] = key;
                shape.ids[t] = uint8_t(g);
                ids[t] = g;
                ends[t] = unsigned(std::min(b, spans[first + t].end) - a);
            }

            if (plans.size() >= 512)
                plans.clear();
            auto [it, new_shape] = plans.try_emplace(shape);
            if (new_shape)
                it->second = plan_segments(ids.data(), prices.data(), prices.data(), shape.count,
                                           segment_mode == 2);
            const auto &plan = it->second;
            auto masked_score = [&](unsigned lo, unsigned hi) {
                Word sel = low(hi) & ~low(lo);
                unsigned total = 0;
                for (unsigned h = 0; h < used; ++h)
                    total += std::popcount(forms[h] & sel);
                return total;
            };
            std::array<Count, 12> mass{}, size{};
            unsigned left_prefix = 0;
            for (const auto &seg : plan.parts) {
                auto hi = ends[seg.end - 1];
                unsigned right_prefix = seg.end == shape.count ? pop : masked_score(0, hi);
                Count residue = right_prefix - left_prefix;
                left_prefix = right_prefix;
                for (unsigned j = seg.begin; j < seg.end; ++j) {
                    unsigned lo = j ? ends[j - 1] : 0;
                    unsigned g = ids[j];
                    size[g] += ends[j] - lo;
                    if (g != seg.omit) {
                        auto value = masked_score(lo, ends[j]);
                        mass[g] += value;
                        residue -= value;
                    }
                }
                mass[seg.omit] += residue;
            }
            for (unsigned g = 0; g < distinct; ++g) {
                auto &dst = counter(names[g]);
                dst.n += size[g];
                dst.score += mass[g] + bias * size[g];
            }
            continue;
        }
        std::array<uint16_t, 65> prefix{};
        bool materialize = cuts >= materialization_threshold && used;
        if (materialize && used) {
            for (unsigned tile = 0; tile < width; tile += 4) {
                Word block = 0;
                for (unsigned j = 0; j < used; ++j)
                    block += lanes16[(forms[j] >> tile) & 15];

                block *= 0x0001000100010001ULL;
                for (unsigned h = 0; h < std::min(4u, width - tile); ++h)
                    prefix[tile + h + 1] = uint16_t(prefix[tile] + ((block >> (16 * h)) & 65535));
            }
        }
        unsigned prior = 0;
        for (size_t j = first; j <= last; ++j) {
            auto end = std::min(spans[j].end, b);
            unsigned count = unsigned(end - std::max(spans[j].begin, a));
            unsigned t = unsigned(end - a);
            unsigned value = 0;
            if (j == last)
                value = pop;
            else if (materialize)
                value = prefix[t];
            else {
                Word mask = low(t);
                for (unsigned h = 0; h < used; ++h)
                    value += std::popcount(forms[h] & mask);
            }
            auto &dst = counter(spans[j].key);
            dst.n += count;
            dst.score += bias * count + value - prior;
            prior = value;
        }
    }
    auto publish = [&](Count k, const EndpointAnswer &entry) {
        if (entry.n) {
            auto &dst = output[k];
            dst.resize(2);
            dst[0] += entry.n;
            dst[1] += entry.score;
        }
    };
    for (size_t j = 0; j < direct.size(); ++j)
        publish(j ? lo + Count(j - 1) : missing_key, direct[j]);
    for (auto &[k, entry] : other)
        publish(k, entry);
}
}
