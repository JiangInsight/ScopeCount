# ScopeCount

A DuckDB extension for *Exact Grouped Completeness Audits from Score Margins and Boundary Prefixes*.

<img src="figures/group-scores.png" width="590" alt="Boundary prefixes recover missing-field totals for three groups across twelve rows.">

### Run an audit

On x64 Windows with Visual Studio C++ Build Tools and Python 3.11–3.13:

```powershell
python -m pip install -r requirements.txt
python build.py
python run_example.py
```

The [example](run_example.py) writes a small Parquet file and loads the extension. This is the prepared DuckDB query for the endpoint plan. Its parameters are the first row, the exclusive end row and the file path.

```sql
SELECT unnest(scope_page_counts(content, 0, '2/0,4/0', ?, ?, 'endpoint'))
FROM read_blob(?);
```

All six plans return the same group counts as SQL on the four example intervals.

### Audit results

![Group audit times for weekly and hourly periods relative to DuckDB SQL.](figures/audit-periods.png)

Over ten rounds on the 25 weekly and hourly traffic-stop queries, the endpoint plan had the lowest median time on 24. Its per-query medians summed to **3.32 s**. Choosing the fastest of SQL, dense rank, CRoaring and packed row scores separately for each query gave **4.09 s**. [Trial timings](data/file-trials.tsv)
