# Grouped completeness from Parquet

The loadable DuckDB C extension reads flat nullable columns, a signed or unsigned INT32 key, and a physical half-open interval. Group keys support plain values and dictionary codes; levels use the Parquet RLE/bit-packed hybrid. DuckDB's `read_blob` supplies the file under its normal access permissions. Each query reads the whole projected file. Internal accounting measures row groups, decoded level streams, certified clauses and omitted word visits; the latter are opportunities under the relevant plan, not bytes of avoided I/O. A missing key participates in conservation but is excluded from the SQL output. A key column of -1 requests an ungrouped total. Weighted modes accept up to 64 checks; field masks address the first 64 columns.

The endpoint operator evaluates an integral of the row score at group boundaries. The dense-prefix control always forms local row prefixes. Word dispatch uses group-run popcounts, sparse signed exceptions or row scores in packed bytes. The other comparisons merge literal/score runs, recover a residual group from a known total, use rank on dense bitmaps, or intersect CRoaring key and predicate sets. The bitmap plans pay their first-use construction per row group. SQL sees the very same file and can apply its normal projection and aggregation optimizations.

## Replay

Run from the repository root. Install the pinned numeric, Arrow and DuckDB packages in `research/artifact/requirements.txt`. The C++ build uses an x64 MSVC toolchain on Windows; on Linux the scripts supply GCC/Clang build commands. Published timings are from Windows. The builder obtains CRoaring 5.5.5 from the pinned release via the existing engine builder. For the study tables follow [the source reconstruction instructions](../livegroups/README.md). The FCC inputs are available in `research/artifact/operational/grouped_fcc.zip`. Supply the extracted directory to `--fcc` when using a nondefault location.

```text
python research/artifact/pageaudit/build.py
python research/artifact/pageaudit/check_width.py
python research/artifact/pageaudit/check.py
python research/artifact/pageaudit/check_partial.py
python research/artifact/fused/forest_verify.py
artifact\pageaudit\check_pivot.cmd
python research/artifact/pageaudit/example.py
python research/artifact/pageaudit/report.py
python research/artifact/pageaudit/confirmation.py
```

The report reads checked-in trial records. The file benchmarks check every sorted integer result against an independent oracle outside the timed interval. Each full-method rotation uses random order with every method in each slot equally often. A campaign writes its own results directory, so the reported comparisons use matched runs. For a fresh reproduction use separate destination directories:

```text
python research/artifact/pageaudit/benchmark.py --methods sql cert merge score scorelocal --repeats 5 --out RUNS/page-full
python research/artifact/pageaudit/benchmark.py --methods sql merge packed boundary_pos boundary --repeats 5 --out RUNS/page-boundary
python research/artifact/pageaudit/benchmark.py --methods sql dense roaring boundary residual --repeats 5 --out RUNS/page-bitmap
python research/artifact/pageaudit/benchmark.py --methods sql dense boundary endpoint_dense endpoint --repeats 5 --out RUNS/page-endpoint
python research/artifact/pageaudit/benchmark.py --methods sql dense roaring packed endpoint --repeats 10 --out RUNS/page-confirm
python research/artifact/pageaudit/benchmark.py --methods sql endpoint_sparse endpoint_dense endpoint endpoint8 --repeats 5 --out RUNS/page-cuts
python research/artifact/pageaudit/benchmark.py --methods sql endpoint segment_one segment packed --repeats 5 --out RUNS/page-segments
python research/artifact/pageaudit/degree.py --out RUNS/page-degree/trials.tsv
```

Repeat the boundary, bitmap and endpoint suites with `--typed CACHE/typed --only ca_bakersfield-week co_aurora-week mn_saint_paul-week --repeats 10` and output names `page-typed`, `page-typed-bitmap` and `page-typed-endpoint`. Repeat the confirmation suite on the original-type Ohio and Washington files with `--typed CACHE/typed --only oh_statewide-week oh_statewide-hour wa_statewide-week wa_statewide-hour` and output name `page-typed-states`. Statewide projections preserve the audited source fields and both time keys. Local decoded source values are excluded from the artifact. `scope_page_counts` returns one list per group with the key, group size, answers and four integer instrumentation counters. The FCC file study times the group count and email-present count, filters the original minimum group size and sorts by key for validation. The resident FCC study also applies the published rounding and display order.

The standalone segment verifier enumerates all admissible schedules against binary mass assignments on short run sequences. To recompute structural counts over the real workload, build the verifier/diagnostic using `check_pivot.cmd`, then run `python research/artifact/pageaudit/profile_work.py --exe ../compiled/profile_segments.exe --panels CACHE/panels --out RUNS/segment_work.csv`. The DP installs anchors per word with up to twelve runs, and caches canonical key sequences per row group.

To repeat the ten-fragment controls, run `python research/artifact/pageaudit/segment_controls.py --out RUNS/segment_controls.tsv`. Each layout preserves the same ordered validity matrix, multiset of key fragments and group frequencies.
