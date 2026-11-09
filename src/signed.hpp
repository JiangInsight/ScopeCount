#pragma once
namespace pages {
class GroupDirectory {
    const std::vector<Region> &runs;
    size_t begin, end;
    std::vector<unsigned> bucket, dense_run_id;
    std::vector<size_t> owners;
    std::vector<Count> labels, cardinality, word_count;
    struct Edge {
        size_t first, last, l, r;
    };
    using EdgeSets = std::array<std::vector<Edge>, 2>;
    std::map<Count, Count> local(const EdgeSets &edges, Count total, bool allow_pivot) const {


        std::vector<Count> hits[2];
        for (unsigned sign = 0; sign < 2; ++sign) {
            std::vector<Count> delta(runs.size() + 1);
            hits[sign].resize(labels.size());
            for (auto &e : edges[sign]) {
                ++delta[e.first];
                --delta[e.last + 1];
            }
            Count depth = 0;
            for (size_t i = 0; i < runs.size(); ++i) {
                depth += delta[i];
                hits[sign][owners[i]] += depth;
            }
        }
        size_t pivot = labels.size();
        Count best = -1;
        std::vector<unsigned> sign(labels.size());
        for (size_t g = 0; g < labels.size(); ++g) {
            sign[g] = hits[1][g] <= hits[0][g];
            Count cost = hits[sign[g]][g];
            if (allow_pivot && cost > best) {
                best = cost;
                pivot = g;
            }
        }
        std::vector<Count> subtotal(labels.size());
        Count others = 0;
        for (unsigned z = 0; z < 2; ++z) {
            std::vector<size_t> rank(runs.size() + 1), selected;
            for (size_t j = 0; j < runs.size(); ++j) {
                if (owners[j] != pivot && sign[owners[j]] == z)
                    selected.push_back(j);
                rank[j + 1] = selected.size();
            }
            for (const auto &e : edges[z]) {
                for (size_t q = rank[e.first]; q < rank[e.last + 1]; ++q) {
                    auto j = selected[q];
                    subtotal[owners[j]] +=
                        std::min(e.r, runs[j].end) - std::max(e.l, runs[j].begin);
                }
            }
        }
        std::map<Count, Count> out;
        for (size_t g = 0; g < labels.size(); ++g)
            if (g != pivot) {
                Count val = sign[g] ? subtotal[g] : cardinality[g] - subtotal[g];
                out[labels[g]] = val;
                others += val;
            }
        if (allow_pivot)
            out[labels[pivot]] = total - others;
        return out;
    }

  public:
    GroupDirectory(const std::vector<Region> &spans, size_t l, size_t r)
        : runs(spans), begin(l), end(r) {
        Count smallest = INT64_MAX, largest = INT64_MIN;
        for (const auto &span : runs)
            if (span.key != missing_key) {
                smallest = std::min(smallest, span.key);
                largest = std::max(largest, span.key);
            }
        bool compact = smallest <= largest && largest - smallest < 65536;
        std::vector<int> direct(compact ? size_t(largest - smallest) + 2 : 0, -1);
        std::map<Count, size_t> ids;
        auto add_key = [&](Count key) {
            auto id = labels.size();
            labels.push_back(key);
            cardinality.push_back(0);
            word_count.push_back(0);
            return id;
        };
        for (const auto &span : runs) {
            size_t id;
            if (compact) {
                auto &slot = direct[span.key == missing_key ? 0 : 1 + size_t(span.key - smallest)];
                if (slot < 0)
                    slot = int(add_key(span.key));
                id = size_t(slot);
            } else {
                auto [it, inserted] = ids.try_emplace(span.key, labels.size());
                if (inserted)
                    add_key(span.key);
                id = it->second;
            }
            owners.push_back(id);
            cardinality[id] += span.end - span.begin;
            word_count[id] += (span.end - 1) / 64 - span.begin / 64 + 1;
        }
        if (runs.size() > (end - begin) / 12) {
            dense_run_id.resize(end - begin);
            for (size_t i = 0; i < runs.size(); ++i)
                std::fill(dense_run_id.begin() + (runs[i].begin - begin),
                          dense_run_id.begin() + (runs[i].end - begin), unsigned(i));
            return;
        }
        size_t j = 0;
        for (size_t pos = l; pos < r; pos += 64) {
            while (runs[j].end <= pos)
                ++j;
            bucket.push_back(unsigned(j));
        }
    }
    size_t at(size_t pos) const {
        if (!dense_run_id.empty())
            return dense_run_id[pos - begin];
        auto j = bucket[(pos - begin) / 64];
        while (runs[j].end <= pos)
            ++j;
        return j;
    }
    const auto &work() const { return word_count; }
    size_t owner(size_t i) const { return owners[i]; }
    const auto &keys() const { return labels; }
    const auto &counts() const { return cardinality; }
    std::map<Count, Count> reduce(const std::vector<Region> &truth, bool signed_choice,
                                  bool flip = false, int plan = 0) const {
        EdgeSets edges;
        size_t price[2] = {0, 0};
        Count total = 0;
        for (const auto &span : truth) {
            size_t l = std::max(begin, span.begin), r = std::min(end, span.end);
            if (l >= r)
                continue;
            auto a = at(l), b = at(r - 1);
            unsigned z = unsigned(bool(span.key) != flip);
            if (z)
                total += r - l;
            price[z] += b - a + 1;
            edges[z].push_back({a, b, l, r});
        }
        if (plan)
            return local(edges, total, plan == 2);
        bool subtract = signed_choice && price[0] < price[1];

        std::vector<Count> increments(labels.size());
        for (const auto &e : edges[subtract ? 0 : 1]) {
            for (size_t j = e.first; j <= e.last; ++j)
                increments[owners[j]] += std::min(runs[j].end, e.r) - std::max(runs[j].begin, e.l);
        }
        std::map<Count, Count> out;
        for (size_t j = 0; j < labels.size(); ++j)
            out[labels[j]] = subtract ? cardinality[j] - increments[j] : increments[j];
        return out;
    }
};
inline std::vector<Region> intersect(const std::vector<const std::vector<Region> *> &inputs,
                                     const std::vector<bool> &wants_present, size_t n) {
    std::vector<size_t> cursor(inputs.size());
    std::vector<Region> out;
    for (size_t pos = 0; pos < n;) {
        size_t end = n;
        bool match = true;
        for (size_t j = 0; j < inputs.size(); ++j) {
            auto &s = (*inputs[j])[cursor[j]];
            end = std::min(end, s.end);
            match &= (bool(s.key) == wants_present[j]);
        }
        append(out, match, pos, end - pos);
        for (size_t j = 0; j < inputs.size(); ++j)
            if ((*inputs[j])[cursor[j]].end == end)
                ++cursor[j];
        pos = end;
    }
    return out;
}
}
