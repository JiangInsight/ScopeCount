# DuckDB resident grouped aggregates

The extension registers grouped aggregates taking an unsigned grouping key followed by 1–24 nullable Boolean columns. A Boolean encodes source validity; the payload value does not affect the answer. The output is a DuckDB list of structs with a key, a count and one or more observed-cell counts. The SQL wrappers in the drivers restore the requested missingness convention.

From the repository root:

```text
python research/artifact/fused/build.py
python research/artifact/fused/verify.py
python research/artifact/fused/verify_cover.py
python research/artifact/fused/forest_verify.py
python research/artifact/fused/fcc.py --reps 24 --out RUNS/fcc
python research/artifact/fused/controls.py --reps 14 --out RUNS/controls
python research/artifact/fused/report.py
```

The FCC driver accepts `--base` for the extracted `research/artifact/operational/grouped_fcc.zip` directory. `SCOPEFUSED_OUTPUT` and `SCOPEFUSED_EXTENSION` override the build location and runtime library path. The report reads the frozen timings in `evidence`. The six factorial controls vary grouped-key order and the number of distinct scores at fixed width, row count and random seed. The compiler selects the AVX2 implementation on the measured x64 machine. Each trial checks every returned key and integer against the reference.
