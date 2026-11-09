#include "segments.hpp"
#include <bit>
#include <iostream>
#include <random>
#include <stdexcept>
#include <unordered_map>

int main() {
    std::mt19937 rng(99141);
    unsigned shapes = 0, schedules = 0;
    std::array<unsigned, 7> keys{};
    auto check = [&](unsigned n) {
        std::array<int, 8> direct{}, prefix{};
        for (unsigned i = 0; i < n; ++i) {
            direct[i] = int(rng() % 5);
            prefix[i] = int(rng() % 5);
        }
        auto plan = pages::plan_segments(keys.data(), direct.data(), prefix.data(), n, true);
        int minimum = 1000;
        for (unsigned observed = 0; observed < (1u << (2 * n - 1)); ++observed) {
            ++schedules;
            int price = 0;
            for (unsigned j = 0; j < n; ++j)
                if (observed & (1u << j))
                    price += direct[j];
            for (unsigned j = 1; j < n; ++j)
                if (observed & (1u << (n + j - 1)))
                    price += prefix[j];
            if (price >= minimum)
                continue;
            std::unordered_map<uint64_t, uint64_t> seen;
            bool identifiable = true;
            for (unsigned mass = 0; mass < (1u << n) && identifiable; ++mass) {
                uint64_t response = std::popcount(mass), target = 0;
                std::array<unsigned, 7> output{};
                for (unsigned i = 0; i < n; ++i) {
                    unsigned x = (mass >> i) & 1;
                    output[keys[i]] += x;
                    if (observed & (1u << i))
                        response = response * 8 + x;
                    if (i > 0 && (observed & (1u << (n + i - 1))))
                        response = response * 8 + std::popcount(mass & ((1u << i) - 1));
                }
                for (auto x : output)
                    target = target * 8 + x;
                auto [it, fresh] = seen.try_emplace(response, target);
                if (!fresh && it->second != target)
                    identifiable = false;
            }
            if (identifiable)
                minimum = price;
        }
        if (plan.cost != minimum)
            throw std::runtime_error("DP differs from exhaustive identifiability");
        ++shapes;
    };
    auto visit = [&](auto &&self, unsigned at, unsigned n, unsigned next) -> void {
        if (at == n) {
            check(n);
            return;
        }
        for (unsigned k = 0; k <= next && k < 4; ++k) {
            if (at && k == keys[at - 1])
                continue;
            keys[at] = k;
            self(self, at + 1, n, std::max(next, k + 1));
        }
    };
    for (unsigned n = 1; n <= 6; ++n)
        visit(visit, 0, n, 0);
    std::array<unsigned, 10> example = {0, 1, 0, 2, 0, 3, 4, 3, 5, 3};
    std::array<int, 11> unit{};
    unit.fill(1);
    if (pages::plan_segments(example.data(), unit.data(), unit.data(), 10, true).cost != 5 ||
        pages::plan_segments(example.data(), unit.data(), unit.data(), 10, false).cost != 7)
        throw std::runtime_error("ten-run example mismatch");
    std::cout << "Verified " << shapes << " canonical run sequences, " << schedules
              << " measurement schedules and the ten-run example.\n";
}
