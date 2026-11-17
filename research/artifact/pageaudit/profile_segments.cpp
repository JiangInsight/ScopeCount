#include "segments.hpp"
#include <bit>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>

static std::vector<uint32_t> load(const char *file) {
    std::ifstream in(file, std::ios::binary | std::ios::ate);
    if (!in)
        throw std::runtime_error("missing projection");
    auto bytes = in.tellg();
    if (bytes % 4 != 0)
        throw std::runtime_error("unaligned input");
    std::vector<uint32_t> v(size_t(bytes) / 4);
    in.seekg(0);
    if (!in.read(reinterpret_cast<char *>(v.data()), bytes))
        throw std::runtime_error("short projection");
    return v;
}
int main(int argc, char **argv) {
    if (argc != 4)
        return 2;
    auto key = load(argv[1]), mask = load(argv[2]);
    if (key.size() != mask.size())
        throw std::runtime_error("mismatched rows");
    uint32_t active = uint32_t(std::stoul(argv[3]));
    uint64_t words = 0, eligible = 0, gain = 0, one = 0, many = 0, weighted_one = 0,
             weighted_many = 0;
    std::unordered_map<pages::Shape, std::pair<int, int>, pages::ShapeHash> plans;
    std::array<int, 13> unit{};
    unit.fill(1);
    for (size_t i = 0; i < key.size(); i += 64) {
        ++words;
        size_t stop = std::min(i + 64, key.size());
        uint32_t varying = 0;
        unsigned n = 1;
        std::array<uint32_t, 12> runs{};
        runs[0] = key[i];
        for (size_t j = i + 1; j < stop; ++j) {
            varying |= mask[j] ^ mask[i];
            if (key[j] != key[j - 1]) {
                if (n < 12)
                    runs[n] = key[j];
                ++n;
            }
        }
        unsigned literals = std::popcount(varying & active);
        if (!literals || n < 2 || n > 12)
            continue;
        ++eligible;
        pages::Shape shape;
        shape.count = uint8_t(n);
        std::array<unsigned, 12> ids{};
        std::array<uint32_t, 12> names{};
        unsigned distinct = 0;
        for (unsigned j = 0; j < n; ++j) {
            unsigned g = 0;
            while (g < distinct && names[g] != runs[j])
                ++g;
            if (g == distinct)
                names[distinct++] = runs[j];
            ids[j] = g;
            shape.ids[j] = uint8_t(g);
        }
        auto [it, fresh] = plans.try_emplace(shape);
        if (fresh)
            it->second = {pages::plan_segments(ids.data(), unit.data(), unit.data(), n, false).cost,
                          pages::plan_segments(ids.data(), unit.data(), unit.data(), n, true).cost};
        auto [a, b] = it->second;
        one += a;
        many += b;
        weighted_one += literals * a;
        weighted_many += literals * b;
        gain += a > b;
    }
    std::cout << words << "," << eligible << "," << gain << "," << one << "," << many << ","
              << weighted_one << "," << weighted_many << "\n";
}
