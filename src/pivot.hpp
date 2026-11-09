#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <map>
#include <optional>
#include <stdexcept>
#include <utility>

namespace pages {

struct PivotChoice {
    std::optional<std::int64_t> key;
    std::array<std::pair<std::size_t, std::size_t>, 2> exterior;
    std::uint64_t outside_words = 0;
    std::uint64_t saved_words = 0;
};

inline std::size_t range_words(std::size_t lo, std::size_t hi) {
    return lo == hi ? 0 : (hi - 1) / 64 - lo / 64 + 1;
}


inline PivotChoice pick_pivot(const std::map<std::int64_t, std::int64_t> &work, std::size_t n,
                              std::size_t lo, std::size_t hi) {
    if (lo > hi || hi > n)
        throw std::invalid_argument("invalid tile interval");
    PivotChoice choice{std::nullopt, {{{0, lo}, {hi, n}}}};
    choice.outside_words = range_words(0, lo) + range_words(hi, n);
    for (const auto &[key, charge] : work) {
        if (charge < 0)
            throw std::invalid_argument("negative span price");
        const auto visits = static_cast<std::uint64_t>(charge);
        if (visits <= choice.outside_words)
            continue;
        const auto gain = visits - choice.outside_words;
        if (gain > choice.saved_words) {
            choice.key = key;
            choice.saved_words = gain;
        }
    }
    return choice;
}

}
