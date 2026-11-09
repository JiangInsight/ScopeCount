#include "pivot.hpp"
#include <algorithm>
#include <iostream>
#include <numeric>
#include <random>
#include <vector>

using Key = std::int64_t;
using Interval = std::pair<std::size_t, std::size_t>;

void verify(bool ok) {
    if (!ok)
        throw std::runtime_error("residual identity or minimum-price witness failed");
}
std::uint64_t count_words(std::size_t l, std::size_t r) {
    std::uint64_t result = 0;
    for (auto i = l; i < r; ++i)
        if (i == l || i % 64 == 0)
            ++result;
    return result;
}
void check(const std::vector<Key> &keys, const std::vector<int> &predicate, std::size_t lo,
           std::size_t hi) {
    std::map<Key, std::int64_t> direct, visit;
    std::uint64_t direct_price = 0;
    for (auto left = lo; left < hi;) {
        auto right = left + 1;
        while (right < hi && keys[right] == keys[left])
            ++right;
        const auto words = count_words(left, right);
        direct_price += words;
        visit[keys[left]] += words;
        direct[keys[left]] +=
            std::accumulate(predicate.begin() + left, predicate.begin() + right, std::int64_t{0});
        left = right;
    }
    const auto choice = pages::pick_pivot(visit, keys.size(), lo, hi);
    std::uint64_t outside = 0;
    for (auto [l, r] : {Interval{0, lo}, Interval{hi, keys.size()}})
        outside += count_words(l, r);
    std::uint64_t best = direct_price;
    for (const auto &[k, unused] : direct) {

        auto candidate = outside;
        for (auto other : visit)
            if (other.first != k)
                candidate += other.second;
        best = std::min(best, candidate);
    }
    verify(choice.saved_words == direct_price - best && outside == choice.outside_words);
    if (!choice.key) {
        verify(best == direct_price);
        return;
    }
    std::int64_t remainder = std::accumulate(predicate.begin(), predicate.end(), std::int64_t{0});
    for (auto [l, r] : choice.exterior) {
        for (auto i = l; i < r; ++i)
            remainder -= predicate[i];
    }
    for (auto [k, v] : direct)
        if (k != *choice.key)
            remainder -= v;
    verify(direct.at(*choice.key) == remainder);
}
int main() {
    std::uint64_t checked = 0;
    for (unsigned n = 0; n <= 6; ++n) {
        const unsigned combos = 1u << n;
        for (unsigned a = 0; a < combos; ++a)
            for (unsigned b = 0; b < combos; ++b) {
                std::vector<Key> keys(n);
                std::vector<int> pred(n);
                for (unsigned i = 0; i < n; ++i) {
                    keys[i] = (a >> i) & 1;
                    pred[i] = (b >> i) & 1;
                }
                for (unsigned lo = 0; lo <= n; ++lo)
                    for (unsigned hi = lo; hi <= n; ++hi) {
                        check(keys, pred, lo, hi);
                        ++checked;
                    }
            }
    }
    std::mt19937_64 rng(20261109);
    for (unsigned t = 0; t < 5000; ++t) {
        const auto n = std::size_t(62 + rng() % 260);
        std::vector<Key> keys(n);
        std::vector<int> pred(n);
        const unsigned period = 1 + rng() % 80;
        for (std::size_t i = 0; i < n; ++i) {
            keys[i] = std::int64_t((i / period) % 5) - 2;
            pred[i] = int(rng() & 1);
        }
        const auto l = std::size_t(rng() % (n + 1)), r = std::size_t(rng() % (n + 1));
        check(keys, pred, std::min(l, r), std::max(l, r));
        ++checked;
    }
    verify(pages::pick_pivot({{12, 4}, {9, 4}}, 190, 0, 190).key == 9);
    verify(!pages::pick_pivot({{1, 1}}, 65, 0, 64).key);
    verify(pages::pick_pivot({{7, 2}}, 65, 0, 64).saved_words == 1);
    std::cout << "Verified " << checked << " labeled slices plus tie cases.\n";
}
