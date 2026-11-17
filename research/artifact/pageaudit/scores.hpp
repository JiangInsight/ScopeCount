#pragma once
namespace pages {
class ScoreEvents {
    size_t n;
    int initial = 0;
    std::vector<std::pair<size_t, int>> events;
    std::vector<int> delta;

  public:
    explicit ScoreEvents(size_t len) : n(len) {}
    void constant() { ++initial; }
    void add(const std::vector<Region> &runs, bool invert) {
        if (bool(runs.front().key) != invert)
            ++initial;
        if (delta.empty() && events.size() + runs.size() > n / 12 + 32) {
            delta.resize(n);
            for (auto [at, d] : events)
                delta[at] += d;
            events.clear();
        }
        for (size_t j = 1; j < runs.size(); ++j) {
            auto r = runs[j];
            int step = (bool(r.key) != invert) ? 1 : -1;
            if (delta.empty())
                events.emplace_back(r.begin, step);
            else
                delta[r.begin] += step;
        }
    }
    std::vector<Region> finish() {
        std::vector<Region> out;
        int score = initial;
        size_t pos = 0;
        auto move = [&](size_t next, int diff) {
            if (diff) {
                append(out, score, pos, next - pos);
                pos = next;
                score += diff;
            }
        };
        if (delta.empty()) {
            std::sort(events.begin(), events.end());
            for (size_t j = 0; j < events.size();) {
                size_t t = events[j].first;
                int d = 0;
                do {
                    d += events[j++].second;
                } while (j < events.size() && events[j].first == t);
                move(t, d);
            }
        } else
            for (size_t t = 1; t < n; ++t)
                if (delta[t])
                    move(t, delta[t]);
        append(out, score, pos, n - pos);
        return out;
    }
};
inline std::vector<Count> score_counts(const GroupDirectory &dir, const std::vector<Region> &keys,
                                       const std::vector<Region> &all, size_t l, size_t r,
                                       size_t width, const std::string &mode) {
    std::vector<Count> result(dir.keys().size());
    if (mode == "merge") {
        size_t g = 0;
        for (auto s : all) {
            auto pos = std::max(l, s.begin), end = std::min(r, s.end);
            while (pos < end) {
                auto stop = std::min(end, keys[g].end);
                result[dir.owner(g)] += s.key * Count(stop - pos);
                pos = stop;
                if (pos == keys[g].end)
                    ++g;
            }
        }
        return result;
    }
    struct E {
        size_t a, b, l, r;
    };
    std::vector<std::vector<E>> by(width + 1);
    std::vector<Count> cost(width + 1);
    Count total = 0;
    for (auto s : all) {
        auto lo = std::max(l, s.begin), hi = std::min(r, s.end);
        if (lo >= hi)
            continue;
        auto a = dir.at(lo), b = dir.at(hi - 1);
        by[s.key].push_back({a, b, lo, hi});
        cost[s.key] += b - a + 1;
        total += s.key * Count(hi - lo);
    }
    size_t modal = std::max_element(cost.begin(), cost.end()) - cost.begin();
    auto size = dir.keys().size();
    if (mode == "score") {
        for (size_t g = 0; g < size; ++g)
            result[g] = Count(modal) * dir.counts()[g];
        for (size_t s = 0; s < by.size(); ++s)
            if (s != modal) {
                Count weight = Count(s) - Count(modal);
                for (auto e : by[s])
                    for (size_t j = e.a; j <= e.b; ++j)
                        result[dir.owner(j)] += weight * Count(std::min(e.r, keys[j].end) -
                                                               std::max(e.l, keys[j].begin));
            }
        return result;
    }
    std::vector<size_t> ref(size);
    std::vector<Count> best(size, -1), tot(size);
    for (size_t s = 0; s < by.size(); ++s)
        if (!by[s].empty()) {
            std::vector<Count> diff(keys.size() + 1), freq(size);
            Count d = 0;
            for (auto e : by[s]) {
                ++diff[e.a];
                --diff[e.b + 1];
            }
            for (size_t k = 0; k < keys.size(); ++k) {
                d += diff[k];
                freq[dir.owner(k)] += d;
            }
            for (size_t g = 0; g < size; ++g) {
                tot[g] += freq[g];
                if (freq[g] > best[g]) {
                    best[g] = freq[g];
                    ref[g] = s;
                }
            }
        }
    size_t pivot = 0;
    for (size_t g = 0; g < size; ++g)
        if (tot[g] - best[g] > tot[pivot] - best[pivot])
            pivot = g;
    for (size_t g = 0; g < size; ++g)
        result[g] = Count(ref[g]) * dir.counts()[g];
    for (size_t s = 0; s < by.size(); ++s)
        if (!by[s].empty()) {
            std::vector<size_t> offsets(keys.size() + 1), chosen;
            for (size_t j = 0; j < keys.size(); ++j) {
                auto g = dir.owner(j);
                if (g != pivot && ref[g] != s)
                    chosen.push_back(j);
                offsets[j + 1] = chosen.size();
            }
            for (auto e : by[s])
                for (size_t t = offsets[e.a]; t < offsets[e.b + 1]; ++t) {
                    auto j = chosen[t], g = dir.owner(j);
                    Count weight = Count(s) - Count(ref[g]);
                    result[g] +=
                        weight * Count(std::min(e.r, keys[j].end) - std::max(e.l, keys[j].begin));
                }
        }
    result[pivot] = total;
    for (size_t g = 0; g < size; ++g)
        if (g != pivot)
            result[pivot] -= result[g];
    return result;
}
}
