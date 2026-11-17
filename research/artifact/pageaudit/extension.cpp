#define DUCKDB_EXTENSION_NAME scopepages
#include "duckdb_extension.h"
DUCKDB_EXTENSION_EXTERN
#include "plan.hpp"

namespace {
using namespace pages;
std::string str(duckdb_vector v, idx_t row) {
    auto &s = static_cast<duckdb_string_t *>(duckdb_vector_get_data(v))[row];
    return std::string(duckdb_string_t_data(&s), duckdb_string_t_length(s));
}


void count_pages(duckdb_function_info info, duckdb_data_chunk args, duckdb_vector output) {
    try {
        idx_t outer_count = 0, values = 0;
        for (idx_t i = 0; i < duckdb_data_chunk_get_size(args); ++i) {
            auto arg = [&](idx_t k) { return duckdb_data_chunk_get_vector(args, k); };
            auto &b = static_cast<duckdb_string_t *>(duckdb_vector_get_data(arg(0)))[i];
            auto key = static_cast<int32_t *>(duckdb_vector_get_data(arg(1)))[i];
            auto lo = static_cast<int64_t *>(duckdb_vector_get_data(arg(3)))[i];
            auto hi = static_cast<int64_t *>(duckdb_vector_get_data(arg(4)))[i];
            for (idx_t j = 0; j < 6; ++j) {
                auto valid = duckdb_vector_get_validity(arg(j));
                require(!valid || duckdb_validity_row_is_valid(valid, i), "null function argument");
            }
            Stats stats;
            auto req = rules(str(arg(2), i));
            auto result =
                execute(reinterpret_cast<const uint8_t *>(duckdb_string_t_data(&b)),
                        duckdb_string_t_length(b), key, req, lo, hi, str(arg(5), i), stats);
            result.erase(missing_key);
            auto *parents = static_cast<duckdb_list_entry *>(duckdb_vector_get_data(output));
            parents[i] = {outer_count, result.size()};
            require(duckdb_list_vector_reserve(output, outer_count + result.size()) ==
                        DuckDBSuccess,
                    "result allocation");
            auto sub = duckdb_list_vector_get_child(output);
            auto width = (result.empty() ? 0 : result.begin()->second.size() + 5);
            require(duckdb_list_vector_reserve(sub, values + width * result.size()) ==
                        DuckDBSuccess,
                    "answer allocation");
            auto *spans = static_cast<duckdb_list_entry *>(duckdb_vector_get_data(sub));
            auto *dest =
                static_cast<Count *>(duckdb_vector_get_data(duckdb_list_vector_get_child(sub)));
            for (auto &[id, answer] : result) {
                spans[outer_count++] = {values, width};
                dest[values++] = id;
                for (auto val : answer)
                    dest[values++] = val;
                for (auto val : {stats.groups, stats.columns, stats.certified, stats.omitted_words})
                    dest[values++] = val;
            }
            duckdb_list_vector_set_size(output, outer_count);
            duckdb_list_vector_set_size(sub, values);
        }
    } catch (const std::exception &e) {
        duckdb_scalar_function_set_error(info, e.what());
    }
}
}
DUCKDB_EXTENSION_ENTRYPOINT(duckdb_connection con, duckdb_extension_info info,
                            struct duckdb_extension_access *access) {
    auto fn = duckdb_create_scalar_function();
    duckdb_scalar_function_set_name(fn, "scope_page_counts");
    for (auto t : {DUCKDB_TYPE_BLOB, DUCKDB_TYPE_INTEGER, DUCKDB_TYPE_VARCHAR, DUCKDB_TYPE_BIGINT,
                   DUCKDB_TYPE_BIGINT, DUCKDB_TYPE_VARCHAR}) {
        auto lt = duckdb_create_logical_type(t);
        duckdb_scalar_function_add_parameter(fn, lt);
        duckdb_destroy_logical_type(&lt);
    }
    auto i = duckdb_create_logical_type(DUCKDB_TYPE_BIGINT);
    auto v = duckdb_create_list_type(i);
    auto vv = duckdb_create_list_type(v);
    duckdb_scalar_function_set_return_type(fn, vv);
    duckdb_scalar_function_set_function(fn, count_pages);
    auto ok = duckdb_register_scalar_function(con, fn);
    duckdb_destroy_scalar_function(&fn);
    for (auto x : {&i, &v, &vv})
        duckdb_destroy_logical_type(x);
    if (ok != DuckDBSuccess)
        access->set_error(info, "Failed to register scope_page_counts");
    return ok == DuckDBSuccess;
}
