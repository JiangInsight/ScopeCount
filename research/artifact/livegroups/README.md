# Published traffic-stop audits

Kher and Hardin used Stanford Open Policing Project records to study how missingness varies with the week, hour or location of a stop. The reproducible count workload here includes every distinct weekly and hourly analysis named in their plotting script. It covers 19 weekly queries, with six of those jurisdictions also queried by hour. Chicago's repeated weekly call is counted once. The geographic analysis also filters coordinates, computes geohashes and returns two means. This workload covers time grouping. The sources document the analyses. They do not expose a production request log, arrival times or cache hits.

- [Journal paper by Saatvik Kher and Johanna Hardin](https://doi.org/10.1162/99608f92.c45545cb)
- [Source analyses and exact release names](https://github.com/saatvikkher/missing-traffic/blob/9abc320a6b1bf7fd27ea3c7964dd9ed8a69a81f6/diagnosing_nonMCAR_plots.R)
- [Source conditional missing rate calculation](https://github.com/saatvikkher/missing-traffic/blob/9abc320a6b1bf7fd27ea3c7964dd9ed8a69a81f6/dCMR_func.R)
- [Stanford data archive and attribution terms](https://openpolicing.stanford.edu/data/)
- [Original Stanford data publication, Pierson et al.](https://doi.org/10.1038/s41562-020-0858-1)

## Recovering the queries

The original RDS file fixes both values and row order. The study selects vehicular stops and the available subset of twenty named fields. For each week or hour, it counts eligible stops and sums missing cells over all fields except the conditioning field. Stops without a value for the conditioning field are excluded. In the source implementation the assignment of the row-wise missingness column precedes calculation of the denominator. With W audited fields, the plotted rate is missing/(n*(W+1)). The two integers and the group key determine the complete set of plotted rates. Downstream statistical tests and graphics are outside the query timer.

The direct base-R oracle groups the original data and counts missing cells independently on each source field. The extraction then preserves both time keys and each field's validity in a source-order Parquet projection. Typed sensitivity inputs retain the original field values and types. Only their checksums, schema and build metadata are distributed. The publication check verifies the 19 raw source cardinalities against the authors' published preprint and compares the 24 Ohio hourly rates against marker centers in the authors' archived 2400 × 2400 plot. The journal and GitHub figures have their own numbering.

## Replaying

Use Python with DuckDB 1.5.5, numpy, pandas, pyarrow, requests, scipy, pillow and lxml. Original snapshot extraction uses base R. The typed sensitivity step also uses pyreadr. Build the DuckDB extension in the sibling fused directory first. Replace CACHE and EXTENSION with local paths.

~~~sh
python stops.py --cache CACHE --rscript Rscript
python publication_checks.py --cache CACHE --out publication_checks.json
python typed.py --cache CACHE --out typed_checks.json
python typed.py --cache CACHE --out typed_state_checks.json oh_statewide wa_statewide
python bench.py --cache CACHE --extension EXTENSION --out RUNS --reps 20
python package.py --cache CACHE --timings RUNS --out results
~~~

The resident experiment loads the same normalized table once for every plan. It prepares each statement, runs one untimed correctness check per plan and times materialization of all sorted answer tuples in a single-threaded DuckDB connection. Every timed answer is compared exactly to the R oracle. Two independently shuffled rotations give each plan every execution position twice in 20 rounds. Source reconstruction, shared DuckDB ingestion and statement preparation are outside these operator measurements. File-to-result tests are distributed separately.

The two native SQL plans use either a sum of per-field COUNTs or a sum of per-row null flags. Per-field native extension variants include row-wise counting, scalar run counting and run-aware validity words. The total-only variants comprise scalar row-wise, literal masks, literal masks with one inferred group, and the full weighted cover. A final native SQL plan materializes a single unsigned-byte null degree alongside both grouping keys. Excluding a missing conditioning key ensures that a fully materialized per-row degree is valid for either query. Its build is measured independently five times. Observed-horizon accounting charges the median build once per jurisdiction, then issues the actual one or two distinct queries. Any additional repetitions in the break-even calculation are cost projections.

The source manifest pins each RDS release and SHA-256 hash. Oracle hashes normalize line endings to LF. Normalized Parquet hashes additionally depend on the Arrow writer version. The result directory contains the full 9,020 grouped output tuples, trial timings, group dimensions, p95s and source-level build accounts.
