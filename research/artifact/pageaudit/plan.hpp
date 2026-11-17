#pragma once
#include "streams.hpp"
#include <arrow/io/memory.h>
#include <parquet/statistics.h>
#include <charconv>
#include <map>
#include <optional>
#include <set>
#include <sstream>
namespace pages {
using Rule = std::pair<Word, Word>;
using Answers = std::map<Count, std::vector<Count>>;
struct Stats {
    Count groups = 0, columns = 0, certified = 0, omitted_words = 0;
};
inline std::vector<Rule> rules(const std::string &text) {
    std::vector<Rule> out;
    std::istringstream in(text);
    std::string pair;
    auto number = [](const std::string &s) {
        Word x;
        auto [end, err] = std::from_chars(s.data(), s.data() + s.size(), x);
        require(err == std::errc{} && end == s.data() + s.size(), "invalid column mask");
        return x;
    };
    while (std::getline(in, pair, ',')) {
        auto at = pair.find('/');
        require(at != std::string::npos, "expected null/present mask pair");
        out.emplace_back(number(pair.substr(0, at)), number(pair.substr(at + 1)));
    }
    require(!out.empty(), "empty audit");
    return out;
}
inline void mark(std::vector<Word> &w, size_t l, size_t r) {
    if (l >= r)
        return;
    size_t a = l / 64, b = (r - 1) / 64;
    if (a == b) {
        w[a] |= low(unsigned(r - l)) << (l % 64);
        return;
    }
    w[a] |= ~Word(0) << (l % 64);
    std::fill(w.begin() + a + 1, w.begin() + b, ~Word(0));
    w[b] |= low(unsigned((r - 1) % 64 + 1));
}
}
#include <array>
#include "signed.hpp"
#include "pivot.hpp"
#include "scores.hpp"
#include "packed.hpp"
#include "bitmap.hpp"
#include "endpoints.hpp"
namespace pages {
struct Tile {
    size_t n;
    std::shared_ptr<parquet::RowGroupReader> group;
    const parquet::SchemaDescriptor *schema;
    std::map<int, std::vector<Word>> streams;
    std::map<int, Count> absent;
    Stats &stats;
    Tile(size_t size, std::shared_ptr<parquet::RowGroupReader> reader,
         const parquet::SchemaDescriptor *s, Stats &cost)
        : n(size), group(std::move(reader)), schema(s), stats(cost) {}
    bool optional(int j) const {
        require(j >= 0 && j < schema->num_columns(), "column out of range");
        auto c = schema->Column(j);
        require(c->max_repetition_level() == 0 && c->max_definition_level() <= 1 &&
                    c->path()->ToDotVector().size() == 1,
                "only flat columns supported");
        return c->max_definition_level() != 0;
    }
    Count nulls(int j) {
        if (absent.contains(j))
            return absent[j];
        Count m = -1;
        if (!optional(j))
            m = 0;
        else if (auto stat = group->metadata()->ColumnChunk(j)->statistics();
                 stat && stat->HasNullCount())
            m = stat->null_count();
        require(m >= -1 && m <= Count(n), "invalid null count");
        return absent[j] = m;
    }
    const std::vector<Word> &missing(int j) {
        auto [it, fresh] = streams.try_emplace(j);
        if (fresh) {
            ++stats.columns;
            auto &w = it->second;
            w.assign((n + 63) / 64, 0);
            for (auto run : levels(*group, j, n, optional(j)))
                if (!run.key)
                    mark(w, run.begin, run.end);
        }
        return it->second;
    }
};
struct Term {
    int col;
    bool want_null;
};
struct Clause {
    std::vector<Term> active;
    std::optional<Count> total;
};
inline Clause simplify(Tile &t, Rule rule, bool use_footer) {
    Clause c;
    if (rule.first & rule.second) {
        c.total = 0;
        return c;
    }
    Count last = -1;
    for (Word bits = rule.first | rule.second; bits; bits &= bits - 1) {
        int j = std::countr_zero(bits);
        bool sign = (rule.first >> j) & 1;
        Count m = use_footer ? t.nulls(j) : -1;
        if (m >= 0 && !sign)
            m = Count(t.n) - m;
        if (m == 0) {
            c.active.clear();
            c.total = 0;
            return c;
        }
        if (m != Count(t.n)) {
            c.active.push_back({j, sign});
            last = m;
        }
    }
    if (c.active.empty())
        c.total = t.n;
    else if (c.active.size() == 1 && last >= 0)
        c.total = last;
    return c;
}
inline size_t words(const Region &r) { return (r.end - 1) / 64 - r.begin / 64 + 1; }
inline Count pop(const Region &r,
                 const std::vector<std::pair<const std::vector<Word> *, bool>> &masks) {
    Count result = 0;
    for (size_t w = r.begin / 64; w <= (r.end - 1) / 64; ++w) {
        Word v = ~Word(0);
        if (w == r.begin / 64)
            v &= ~Word(0) << (r.begin % 64);
        if (w == (r.end - 1) / 64)
            v &= low(unsigned((r.end - 1) % 64 + 1));
        for (auto [bits, sign] : masks) {
            Word m = (*bits)[w];
            v &= sign ? m : ~m;
            if (!v)
                break;
        }
        result += std::popcount(v);
    }
    return result;
}
inline Answers execute(const uint8_t *bytes, size_t length, int group_col,
                       const std::vector<Rule> &predicates, Count begin, Count end,
                       const std::string &mode, Stats &stats) {
    bool bitmaps = mode == "dense" || mode == "roaring";
    bool endpoint = mode == "endpoint" || mode == "endpoint_dense" || mode == "endpoint_sparse" ||
                    mode == "endpoint8" || mode == "segment" || mode == "segment_one";
    bool packed = endpoint || bitmaps || mode == "residual" || mode == "packed" ||
                  mode == "boundary" || mode == "boundary_pos";
    bool weighted = packed || mode == "merge" || mode == "score" || mode == "scorelocal";
    require(weighted || mode == "cert" || mode == "nosub" || mode == "runs" ||
                mode == "incidence" || mode == "positive" || mode == "local" ||
                mode == "local_nopivot",
            "unknown page mode");
    require(group_col >= -1 && begin >= 0 && end >= begin, "invalid key or range");
    auto buf = std::make_shared<arrow::Buffer>(bytes, length);
    auto file = parquet::ParquetFileReader::Open(std::make_shared<arrow::io::BufferReader>(buf));
    auto meta = file->metadata();
    auto schema = meta->schema();
    require(end <= meta->num_rows(), "range extends past table");
    if (group_col >= 0)
        require(group_col < schema->num_columns() &&
                    schema->Column(group_col)->physical_type() == parquet::Type::INT32,
                "group key requires a flat INT32 storage type");
    for (auto [a, b] : predicates)
        if (schema->num_columns() < 64)
            require(((a | b) >> schema->num_columns()) == 0, "predicate references unknown column");
    if (weighted) {
        require(predicates.size() <= 64, "weighted plans support up to 64 checks");
        require(meta->num_rows() <= INT64_MAX / Count(predicates.size()),
                "score exceeds integer range");
    }
    Answers output;
    if (group_col < 0)
        output[0].resize(weighted ? 2 : predicates.size() + 1);
    if (begin == end)
        return output;
    Count offset = 0;
    for (int i = 0; i < meta->num_row_groups(); ++i) {
        auto desc = meta->RowGroup(i);
        require(desc->num_rows() >= 0 && uint64_t(desc->num_rows()) <= UINT32_MAX &&
                    desc->num_rows() <= meta->num_rows() - offset,
                "invalid row group size");
        size_t n = size_t(desc->num_rows());
        Count start = offset;
        offset += Count(n);
        if (offset <= begin || start >= end || !n)
            continue;
        ++stats.groups;
        Tile tile(n, file->RowGroup(i), schema, stats);
        size_t l = size_t(std::max(begin - start, Count(0))),
               r = size_t(std::min(end - start, Count(n)));
        bool full = l == 0 && r == n;
        std::map<Count, Count> sizes, work;
        std::vector<Region> spans;
        bool optional = group_col >= 0 && tile.optional(group_col);
        bool unsigned_key = group_col >= 0 && schema->Column(group_col)->converted_type() ==
                                                  parquet::ConvertedType::UINT_32;
        for (auto region : groups(*tile.group, group_col, n, optional, unsigned_key)) {
            region.begin = std::max(region.begin, l);
            region.end = std::min(region.end, r);
            if (region.end <= region.begin)
                continue;
            spans.push_back(region);
        }
        bool incidence =
            mode == "incidence" || mode == "positive" || mode == "local" || mode == "local_nopivot";
        int pruning = mode == "local" ? 2 : (mode == "local_nopivot" ? 1 : 0);
        auto get_words = [&]() {
            unsigned base = 0;
            std::vector<WordClause> word_clauses;
            for (auto rule : predicates) {
                auto c = simplify(tile, rule, true);
                if (c.total && (*c.total == 0 || *c.total == Count(n))) {
                    if (*c.total)
                        ++base;
                    ++stats.certified;
                    continue;
                }
                WordClause word;
                for (auto term : c.active) {
                    auto [it, fresh] = tile.streams.try_emplace(term.col);
                    if (fresh) {
                        ++stats.columns;
                        it->second = null_words(*tile.group, term.col, n, tile.optional(term.col));
                    }
                    word.masks.emplace_back(&it->second, term.want_null);
                }
                word_clauses.push_back(std::move(word));
            }
            return std::make_pair(base, word_clauses);
        };
        if (endpoint) {
            auto [base, word_clauses] = get_words();
            unsigned threshold = 4;
            if (mode == "endpoint_dense")
                threshold = 0;
            if (mode == "endpoint_sparse")
                threshold = 65;
            if (mode == "endpoint8")
                threshold = 8;
            project_endpoints(spans, word_clauses, base, l, r, threshold,
                              mode == "segment" ? 2 : unsigned(mode == "segment_one"), output);
            continue;
        }
        GroupDirectory directory(spans, l, r);
        for (size_t j = 0; j < directory.keys().size(); ++j) {
            auto id = directory.keys()[j];
            sizes[id] = directory.counts()[j];
            work[id] = directory.work()[j];
        }
        std::map<int, std::vector<Region>> decoded;
        for (auto [key, size] : sizes) {
            auto &a = output[key];
            a.resize(weighted ? 2 : predicates.size() + 1);
            a[0] += size;
        }
        if (weighted) {
            if (packed) {
                size_t pivot = SIZE_MAX;
                Count margin = 0;
                if (mode == "residual" && full) {
                    bool complete = true;
                    for (auto rule : predicates) {
                        auto c = simplify(tile, rule, true);
                        if (!c.total) {
                            complete = false;
                            break;
                        }
                        margin += *c.total;
                    }
                    if (complete) {
                        std::vector<size_t> savings(directory.keys().size());
                        for (size_t k = 0; k < spans.size(); ++k) {
                            auto a = (spans[k].begin + 63) / 64;
                            auto b = spans[k].end == n ? (n + 63) / 64 : spans[k].end / 64;
                            if (b > a)
                                savings[directory.owner(k)] += b - a;
                        }
                        auto best = std::max_element(savings.begin(), savings.end());
                        if (*best)
                            pivot = size_t(best - savings.begin());
                        if (directory.keys().size() == 1) {
                            output[directory.keys()[0]][1] += margin;
                            stats.certified += predicates.size();
                            stats.omitted_words += (n + 63) / 64;
                            continue;
                        }
                        stats.omitted_words += *best;
                    }
                }
                auto [base, word_clauses] = get_words();
                auto values = bitmaps
                                  ? bitmap_counts(directory, spans, word_clauses, base, n, l, r,
                                                  mode == "roaring")
                                  : packed_counts(directory, spans, word_clauses, base, l, r,
                                                  mode != "packed", mode != "boundary_pos", pivot);
                if (pivot != SIZE_MAX) {
                    values[pivot] = margin;
                    for (size_t g = 0; g < values.size(); ++g)
                        if (g != pivot)
                            values[pivot] -= values[g];
                }
                for (size_t g = 0; g < values.size(); ++g)
                    output[directory.keys()[g]][1] += values[g];
                continue;
            }
            ScoreEvents events(n);
            for (auto rule : predicates) {
                auto clause = simplify(tile, rule, true);
                if (clause.total && (*clause.total == 0 || *clause.total == Count(n))) {
                    if (*clause.total)
                        events.constant();
                    ++stats.certified;
                    continue;
                }
                std::vector<const std::vector<Region> *> ss;
                std::vector<bool> signs;
                for (auto term : clause.active) {
                    auto [it, fresh] = decoded.try_emplace(term.col);
                    if (fresh) {
                        ++stats.columns;
                        it->second = levels(*tile.group, term.col, n, tile.optional(term.col));
                    }
                    ss.push_back(&it->second);
                    signs.push_back(!term.want_null);
                }
                if (ss.size() == 1)
                    events.add(*ss[0], !signs[0]);
                else
                    events.add(intersect(ss, signs, n), false);
            }
            auto counts =
                score_counts(directory, spans, events.finish(), l, r, predicates.size(), mode);
            for (size_t j = 0; j < counts.size(); ++j)
                output[directory.keys()[j]][1] += counts[j];
            continue;
        }
        std::map<Rule, std::map<Count, Count>> computed;
        for (size_t k = 0; k < predicates.size(); ++k) {
            Rule rule = predicates[k];
            auto [it, new_rule] = computed.try_emplace(rule);
            auto &answers = it->second;
            if (new_rule) {
                auto clause = simplify(tile, rule, mode != "runs");
                if (clause.total && (*clause.total == 0 || *clause.total == Count(n))) {
                    for (auto [key, size] : sizes)
                        answers[key] = *clause.total ? size : 0;
                    ++stats.certified;
                } else if (incidence) {
                    if (full && sizes.size() == 1 && clause.total) {
                        answers[sizes.begin()->first] = *clause.total;
                        ++stats.certified;
                    } else {
                        std::vector<const std::vector<Region> *> streams;
                        std::vector<bool> signs;
                        for (auto term : clause.active) {
                            auto [c, fresh] = decoded.try_emplace(term.col);
                            if (fresh) {
                                ++stats.columns;
                                c->second =
                                    levels(*tile.group, term.col, n, tile.optional(term.col));
                            }
                            streams.push_back(&c->second);
                            signs.push_back(!term.want_null);
                        }
                        if (streams.size() == 1)
                            answers = directory.reduce(*streams.front(), mode != "positive",
                                                       !signs.front(), pruning);
                        else
                            answers = directory.reduce(intersect(streams, signs, n),
                                                       mode != "positive", false, pruning);
                    }
                } else {
                    std::optional<Count> pivot;
                    auto choice = pick_pivot(work, n, l, r);
                    if (mode == "cert" && clause.total && choice.key) {
                        pivot = choice.key;
                        stats.omitted_words += choice.saved_words;
                    }
                    Count others = 0;
                    if (!pivot || sizes.size() > 1 || choice.outside_words) {
                        std::vector<std::pair<const std::vector<Word> *, bool>> masks;
                        for (auto term : clause.active)
                            masks.push_back({&tile.missing(term.col), term.want_null});
                        std::vector<Count> subtotal(directory.keys().size());
                        for (size_t x = 0; x < spans.size(); ++x)
                            if (!pivot || spans[x].key != *pivot) {
                                Count v = pop(spans[x], masks);
                                subtotal[directory.owner(x)] += v;
                                others += v;
                            }
                        if (pivot)
                            for (auto [lo, hi] : choice.exterior)
                                if (lo < hi)
                                    others += pop({0, lo, hi}, masks);
                        for (size_t j = 0; j < subtotal.size(); ++j)
                            answers[directory.keys()[j]] = subtotal[j];
                    } else
                        ++stats.certified;
                    if (pivot)
                        answers[*pivot] = *clause.total - others;
                }
            }
            for (auto [key, size] : sizes) {
                auto value = answers.at(key);
                require(value >= 0 && value <= size, "footer/rank disagreement");
                output[key][1 + k] += value;
            }
        }
    }
    return output;
}
}
