# Grouped-count service replay

The University of Washington SQLShare release contains a timestamped SQL Server execution log and a separate archive of SQL text and user tables. The released table snapshot supplies the comparison input for each matched statement. It need not equal the live table at its historical execution time. See the [SQLShare data release](https://uwescience.github.io/sqlshare/data_release.html).

The screen finds 26,746 successful records, 2,306 with textual GROUP BY and COUNT, and 33 with a single GROUP BY column and matching COUNT(column), owner, archived query text and table. Two of the 33 contain value filters and four use a ragged CSV. The remaining 27 records use 13 released tables totaling 926,833 rows. Eleven are count-only statements. The other sixteen contain extra numeric aggregates and contribute just their count component. The log records when these historical requests occurred and how often they recur. Some requests repeat the same count component. File versions with identical validity/key projections retain their own manifest entry and source digest.

Within each table, g is a non-null integer dictionary encoding of the source grouping equality classes. Empty source keys, when present, have their own class. Column v0 is a nullable Boolean whose value is TRUE for present source cells and NULL for absent cells. The CSV reader verifies that key equality on these instances survives case folding, trailing-space removal and numeric conversion where applicable. Source order is preserved. Every counted field happens to be fully present. An informed SQL sensitivity runs COUNT(*) after the artifact has verified this fact on the entire released column. Tables contain 2 to 63,544 distinct keys.

The bundle contains projected Parquets, source and answer digests, log times, exclusions, and both timing archives. It omits original cell values, group labels and analyst identities. The current operator includes the empty-slice regression; the frozen full-table queries do not contain empty internal slices.

## Running

Use Python with DuckDB 1.5.5, PyArrow 24.0.0, NumPy 2.4.6, pandas 2.2.3, and sqlglot 30.30.0 for the source screen. From the repository root:

```text
python -m zipfile -e research/artifact/sqlshare_groups/evidence.zip revision/sqlshare-frozen
python research/artifact/fused/build.py
python research/artifact/pageaudit/build.py
python research/artifact/sqlshare_groups/benchmark.py --data revision/sqlshare-frozen/data --out revision/sqlshare-resident --repeats 15
python research/artifact/sqlshare_groups/benchmark.py --file-replay --data revision/sqlshare-frozen/data --out revision/sqlshare-file --repeats 12
```

To repeat source matching and rebuild inputs from the public release, run `python research/artifact/sqlshare_groups/prepare.py`. It caches the query log and only the original table members required by the screen. Frozen input files avoid this download.

For resident replay, each table is loaded once as the same in-memory DuckDB relation for all five methods. Table loading is saved separately as load_ns. For file replay, SQL reads the projected Parquet from its path on every request, and the four encoded operators read the same file through read_blob. The warmed OS file cache is shared. Neither experiment measures preparing a projection or dictionary-encoding raw CSV values. Every request includes SQL dispatch, aggregation, required ordering, and fetching the selected results. For unordered requests, output verification sorts the results after stopping the timer. Every method uses one thread. Method order rotates in complete randomly ordered Latin squares within each table; repetitions estimate timing variation and retain one logical workload demand.

## Results

| Input boundary | Method | Sum of per-table median log totals (ms) |
|---|---|---:|
| Resident | Native SQL | 170.31 |
| Resident | Informed SQL | 170.05 |
| Resident | Fused row | 220.64 |
| Resident | Scalar stream | 208.99 |
| Resident | Word segments | 213.74 |
| Projected file | Native SQL | 231.84 |
| Projected file | Informed SQL | 219.07 |
| Projected file | Word residual | 663.28 |
| Projected file | Positive incidence | 660.03 |
| Projected file | Signed incidence | 648.81 |
| Projected file | Group-local incidence | 655.30 |

For each method and repetition, sum the request times for a table, then take that table's median across repetitions. The table above sums those medians over the 13 inputs. Using the median of paired table differences, the resident word method beats standard SQL on 0/13 tables. The file group-local method beats standard SQL on 1/13 and informed SQL on 0/13. The constant-predicate certificate applies to every certified file query. The small differences among the four encoded modes on this case do not identify a polarity effect. The resident and file runs verified 2,025 and 1,944 dispatched outputs respectively against the frozen source counts.

The endpoint confirmation (`endpoint/timings.tsv` and `endpoint/summary.json`) uses ten rotations with the same logged queries and source digests. Build the current page extension and run the file replay with `--methods sql metadata_star dense roaring endpoint --repeats 10`. The five methods share the same input and grouped output. The two SQL controls run through DuckDB's native Parquet scan.
