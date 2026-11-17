

template <size_t W> struct Form {
    int bias = 0;
    size_t size = 0;
    std::array<Word, W> masks{};
    std::array<int, W> scale{};
    Form() = default;
    explicit Form(const std::array<Word, W> &valid, Word active) {
        for (Word original : valid)
            add(original, 1, active);
        compact();
    }
    void add(Word mask, int weight, Word active) {
        mask &= active;
        if (mask & 1) {
            bias += weight;
            mask ^= active;
            weight = -weight;
        }
        if (!mask)
            return;
        size_t i = 0;
        while (i < size && masks[i] != mask)
            ++i;
        if (i == size)
            masks[size++] = mask;
        scale[i] += weight;
    }
    void compact() {
        for (size_t i = 0; i < size;) {
            if (scale[i]) {
                ++i;
                continue;
            }
            --size;
            masks[i] = masks[size];
            scale[i] = scale[size];
        }
    }
    int sum(Word selection) const {
        int value = bias * std::popcount(selection);
        for (size_t j = 0; j < size; ++j)
            value += scale[j] * std::popcount(selection & masks[j]);
        return value;
    }
};

Word equal_keys(const Key *keys, size_t n, Key key) {
    size_t i = 0;
    Word result = 0;
#if defined(__AVX2__)
    auto want = _mm256_set1_epi32(static_cast<int32_t>(key));
    for (; i + 8 <= n; i += 8) {
        auto v = _mm256_loadu_si256(reinterpret_cast<const __m256i *>(keys + i));
        auto eq = _mm256_cmpeq_epi32(v, want);
        result |= Word(static_cast<unsigned>(_mm256_movemask_ps(_mm256_castsi256_ps(eq)))) << i;
    }
#endif
    for (; i < n; ++i)
        result |= Word(keys[i] == key) << i;
    return result;
}




template <size_t W> Form<W> bit_score_form(const std::array<Word, W> &valid, Word active) {
    std::array<Word, std::bit_width(W)> planes{};
    int offset = 0;


    std::array<Word, W> operands{};
    size_t count = 0;
    for (auto input : valid) {
        input &= active;
        if (input == active)
            ++offset;
        else if (input)
            operands[count++] = input;
    }
    for (size_t h = 0; count; h++) {
        std::array<Word, W> carry{};
        size_t next = 0;
        while (count >= 3) {
            Word a = operands[--count], b = operands[--count], c = operands[--count], ab = a ^ b;
            operands[count++] = ab ^ c;
            carry[next++] = (a & b) | (ab & c);
        }
        if (count == 2) {
            planes[h] = operands[0] ^ operands[1];
            carry[next++] = operands[0] & operands[1];
        } else
            planes[h] = operands[0];
        for (size_t j = 0; j < next; ++j)
            operands[j] = carry[j];
        count = next;
    }
    Form<W> form;
    form.bias = offset;
    for (size_t h = 0; h < planes.size(); ++h)
        form.add(planes[h], 1 << h, active);
    form.compact();
    return form;
}

template <size_t W> struct Scores {
    std::array<Word, 64> masks{};
    std::array<int, 64> score{};
    size_t size = 1;



    bool split(const Form<W> &f, Word occupied, size_t cap) {
        masks[0] = occupied;
        score[0] = f.bias;
        for (size_t j = 0; j < f.size; ++j) {
            const size_t old = size;
            for (size_t i = 0; i < old; ++i) {
                Word matched = masks[i] & f.masks[j];
                if (!matched)
                    continue;
                if (matched == masks[i]) {
                    score[i] += f.scale[j];
                    continue;
                }
                masks[size] = matched;
                score[size++] = score[i] + f.scale[j];
                masks[i] ^= matched;
            }
            for (size_t i = 0; i < size; ++i) {
                for (size_t k = i + 1; k < size;) {
                    if (score[i] != score[k]) {
                        ++k;
                        continue;
                    }
                    masks[i] |= masks[k];
                    --size;
                    masks[k] = masks[size];
                    score[k] = score[size];
                }
            }
            if (size > cap)
                return false;
        }
        return true;
    }
};
template <size_t W>
void weighted_scatter(Groups<1> &groups, const Key *keys, size_t n, Word occupied,
                      const Form<W> &f) {


    std::array<int, 64> weights;
    weights.fill(f.bias);
    for (size_t j = 0; j < f.size; ++j) {
        Word bits = f.masks[j] & occupied;
        while (bits) {
            unsigned k = std::countr_zero(bits);
            bits &= bits - 1;
            weights[k] += f.scale[j];
        }
    }
    for (size_t k = 0; k < n; ++k)
        if (occupied >> k & 1) {
            auto &counts = groups.counter(keys[k]);
            ++counts[0];
            counts[1] += weights[k];
        }
}

template <size_t W, bool atoms, bool residual>
void cover_tile(Groups<1> &groups, const Key *keys, size_t n, Word occupied,
                const std::array<Word, W> &valid) {
    if (occupied != mask_for(n)) {

        weighted_scatter<W>(groups, keys, n, occupied, Form<W>(valid, occupied));
        return;
    }
    const Form<W> f(valid, occupied);
    Word breaks = transitions(keys, n);
    if (std::popcount(breaks) <= 4) {
        while (breaks) {
            size_t first = std::countr_zero(breaks);
            breaks &= breaks - 1;
            size_t last = breaks ? std::countr_zero(breaks) : n;
            Word subset = mask_for(last) & ~mask_for(first);
            auto &c = groups.counter(keys[first]);
            c[0] += last - first;
            c[1] += f.sum(subset);
        }
        return;
    }


    Key sample[8]{};
    int distinct = 0;
    for (size_t i = 0; i < n; i += 8) {
        bool seen = false;
        for (int j = 0; j < distinct; ++j)
            seen |= sample[j] == keys[i];
        if (!seen)
            sample[distinct++] = keys[i];
    }
    if (distinct >= 7) {
        weighted_scatter<W>(groups, keys, n, occupied, f);
        return;
    }
    std::array<Word, 64> selectors;
    std::array<Key, 64> ids;
    size_t count = 0;
    Word left = occupied;
    while (left) {
        unsigned k = std::countr_zero(left);
        Key key = keys[k];
        Word select = equal_keys(keys, n, key);
        ids[count] = key;
        selectors[count++] = select;
        left &= ~select;
    }


    Form<W> binary;
    auto *best = &f;
    if constexpr (atoms) {
        if (f.size >= 3 && count >= 3) {
            binary = bit_score_form<W>(valid, occupied);
            if (binary.size <= f.size)
                best = &binary;
        }
    }
    Scores<W> scores;
    bool use_atoms = atoms && best->size >= 2 && count >= 3 &&
                     scores.split(*best, occupied, std::min(best->size, size_t(8))) &&
                     scores.size - 1 < best->size;
    int total = residual ? best->sum(occupied) : 0, prior = 0;
    for (size_t g = 0; g < count; ++g) {
        const Word key_mask = selectors[g];
        int number = std::popcount(key_mask), value = 0;
        if (residual && g + 1 == count)
            value = total - prior;
        else if (use_atoms) {
            const int reference = scores.score[0];
            value = number * reference;
            for (size_t s = 1; s < scores.size; ++s)
                value += (scores.score[s] - reference) * std::popcount(key_mask & scores.masks[s]);
        } else
            value = best->sum(key_mask);
        prior += value;
        auto &c = groups.counter(ids[g]);
        c[0] += number;
        c[1] += value;
    }
}

template <size_t W, bool use_cover, bool atoms, bool residual>
void weight_update(duckdb_function_info info, duckdb_data_chunk in,
                   duckdb_aggregate_state *states) {
    try {
        size_t n = duckdb_data_chunk_get_size(in);
        if (!n)
            return;
        auto keycol = duckdb_data_chunk_get_vector(in, 0);
        auto keys = static_cast<const Key *>(duckdb_vector_get_data(keycol));
        auto keyok = duckdb_vector_get_validity(keycol);
        std::array<const Word *, W> validity;
        for (size_t j = 0; j < W; ++j)
            validity[j] = duckdb_vector_get_validity(duckdb_data_chunk_get_vector(in, j + 1));
        bool shared = std::memcmp(states, states + 1, (n - 1) * sizeof(*states)) == 0;
        if constexpr (use_cover) {
            if (shared && all_keys_valid(keyok, n) && constant_key(keys, n)) {
                Counts<W> totals{};
                reduce_uniform<W>(totals, n, validity);
                auto &c = reinterpret_cast<Groups<1> *>(states[0])->counter(keys[0]);
                c[0] += n;
                for (size_t j = 1; j <= W; ++j)
                    c[1] += totals[j];
                return;
            }
        }
        for (size_t pos = 0; pos < n; pos += 64) {
            size_t len = std::min(size_t(64), n - pos);
            Word active = mask_for(len) & (keyok ? keyok[pos / 64] : ~Word(0));
            if (!active)
                continue;
            std::array<Word, W> words;
            for (size_t j = 0; j < W; ++j)
                words[j] = validity[j] ? validity[j][pos / 64] : ~Word(0);
            if constexpr (use_cover)
                if (shared) {
                    cover_tile<W, atoms, residual>(*reinterpret_cast<Groups<1> *>(states[0]),
                                                   keys + pos, len, active, words);
                    continue;
                }
            for (size_t k = 0; k < len; ++k)
                if (active >> k & 1) {
                    int score = 0;
                    for (auto w : words)
                        score += w >> k & 1;
                    auto &c =
                        reinterpret_cast<Groups<1> *>(states[pos + k])->counter(keys[pos + k]);
                    ++c[0];
                    c[1] += score;
                }
        }
    } catch (const std::exception &e) {
        duckdb_aggregate_function_set_error(info, e.what());
    }
}
