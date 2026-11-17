# Reproduction

Run from the repository root. `requirements.txt` pins dependencies. The validated environment uses Python 3.13, DuckDB 1.5.5, PyArrow 24.0.0, x64 Windows, and Visual Studio C++ Build Tools. Builders also supply GCC/Clang commands; that platform has not been validated in this release. Network access obtains pinned DuckDB libraries, CRoaring 5.5.5, and original traffic-stop releases.

```powershell
python -m pip install -r requirements.txt
python reproduce.py build
python reproduce.py fetch --names ca_bakersfield
python reproduce.py quick --out outputs/validation --limit 8
```

The build produces three DuckDB operator families (four extension binaries, including the CRoaring-enabled retained build) and twelve native programs. `quick` restores and verifies frozen inputs, checks kernels and exact answers, replays SQLShare and FCC, runs available reconstructed traffic-stop panels, and selects eight snapshots per retained corpus. Each snapshot retains all recorded requests. Selection covers table types, small/median/large inputs, and a positive-result case where available. This is validation, not the full timing campaign.

Each command writes `run-STAGE.json` with commands, exit status, versions, and output. Generated files remain under `compiled/`, `datasets/`, `traces/`, `runs/`, `revision/`, or `outputs/`. Frozen records under `research/artifact/` stay unchanged. Use fresh output directories for new campaigns. Timings collected alongside other jobs must not replace isolated paper measurements.

## Full grouped workload

```powershell
python reproduce.py fetch --all-sources
python reproduce.py restore
python reproduce.py benchmark --suite sqlshare --repeats 15 --out outputs/sqlshare
python reproduce.py benchmark --suite fcc --repeats 24 --out outputs/fcc
python reproduce.py benchmark --suite stops --repeats 20 --out outputs/stops
python reproduce.py benchmark --suite file --repeats 10 --out outputs/file
python reproduce.py benchmark --suite controls --repeats 14 --out outputs/controls
python reproduce.py summarize --out outputs/stops
python reproduce.py summarize --out outputs/file
```

Full extraction reconstructs 19 releases and needs considerably more disk/memory. Python reconstruction must match independent base-R oracle hashes before accepting a panel. Append `--rscript Rscript` to use the original base-R extraction. The stops suite uses only locally reconstructed panels; all 19 are required for the paper workload. Resident plans share one loaded relation. File plans read the same projected Parquet; bitmap plans pay first-use construction per row group. The wrapper rounds repetitions to complete method rotations where Latin-square ordering is used.

## Retained requests and repayment

```powershell
python reproduce.py benchmark --suite retained --limit 0 --repeats 5 --out outputs/retained
python reproduce.py summarize --out outputs/retained
python research/artifact/engine/seeded.py --repeats 5 --out outputs/controlled-retained
python research/artifact/revision/online_controls.py
python research/artifact/revision/order_sensitivity.py
```

`--limit 0` uses all 1,064 transport and 1,226 CI snapshots with SQL/tree/dense-bitmap/CRoaring/online alternatives. `amortization.tsv` and prefix tables charge one index build plus cumulative dispatched request time. Common import is separate. Cached methods compare only against cached references. A blank sustained-crossing field means no sustained repayment within the observed horizon; requests are not extrapolated.

The paper's CI backend selections are also available via `python research/artifact/revision/ci_replay.py pair`, `memo`, and `fresh`; the last uses the fixed 128-table stratum. For monthly flight windows and the exact CRoaring campaign:

```powershell
python research/artifact/revision/freeze_bts.py restore --base datasets/bts
python research/artifact/revision/bts_replay.py --base datasets/bts --out outputs/bts/months.tsv --repeats 5
python research/artifact/engine/roaring_suite.py --groups domains ci bts --bts datasets/bts --out outputs/roaring
```

BTS restoration expands the full validity row array. Its eight checks are user-defined. CRoaring shares DuckDB extraction, predicate semantics, timed dispatch, and cache policy with its references.

## Frozen results

```powershell
python reproduce.py summarize --frozen --out outputs/published
```

This verifies 1,936,080 retained method/request observations and archive hashes, checks the traffic confirmation totals, writes 250 resident case/method medians, and recomputes full CI repayment. Outputs are regenerated summaries of archived measurements, not new performance runs.

For new runs, `query-summary.tsv` contains medians/p95/p99; `row-degree-paid.tsv` charges materialization once over each jurisdiction's actual one or two queries; `resident-setup.tsv` separates common import and row-degree construction. Prefix repayment uses paired repetitions and exact request order.
