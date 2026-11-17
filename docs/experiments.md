# Paper-to-driver map

Paths below are relative to `research/artifact/`. [Reproduction commands](reproduce.md) supply repository-local paths. Every driver checks exact answers against SQL or an independent frozen source oracle outside timing.

| Experiment | Implementation/driver | Frozen input and evidence | Entry point |
|---|---|---|---|
| Resident per-check and scalar score projection | `fused/fused.cpp`, `word_cover.hpp`; `livegroups/bench.py` | 19 sources, 25 queries; `livegroups/evidence` 20-round trials and five builds | `benchmark --suite stops --repeats 20` |
| Margins and residual forest | `word_cover.hpp`, `forest_verify.py`, `verify_cover.py` | Exhaustive binary tables and measurement schedules | `verify` |
| FCC original/shuffled | `fused/fcc.py` | 10,087,929 rows; `fused/evidence` | `benchmark --suite fcc --repeats 24` |
| Resident factorial controls | `fused/controls.py` | Six layouts, 524,288 rows, 24 fields; `fused/evidence/controls` | `benchmark --suite controls --repeats 14` |
| File certificates and literal/score merges | `pageaudit/extension.cpp`, `streams.hpp`, `scores.hpp`, `packed.hpp` | `pageaudit/results/full`, `boundary`, `bitmap` | File ablations below |
| Boundary-prefix/segment plans | `pageaudit/endpoints.hpp`, `pivot.hpp`, `segments.hpp` | `results/endpoint`, `cuts`, `segments`, `confirm` | `benchmark --suite file --repeats 10` |
| Dense rank and CRoaring construction | `pageaudit/bitmap.hpp`, `benchmark.py` | Same files/outputs as endpoint | File confirmation/bitmap controls |
| Typed source sensitivity | `livegroups/typed.py`; `pageaudit/benchmark.py` | Five locally rebuilt raw-valued projections; `results/typed*` | Typed commands below |
| Row-degree build repayment | `pageaudit/degree.py` | One/two queries per source; `results/degree` | `benchmark --suite stops` |
| SQLShare logged counts | `sqlshare_groups/prepare.py`, `benchmark.py` | 27 requests, 13 tables, 926,833 rows; `evidence.zip`, `endpoint` | `benchmark --suite sqlshare` |
| Retained representation and scalar/bundle/synopsis/cache controls | Native `runner`, `bundles`, `cut`, `gate`, `topology`; `engine/scopecount.cpp` | Eight streams, 288 requests each; `evidence.zip`, `revision/evidence/engine*` | `research/artifact/reproduce.py run`; `engine/seeded.py` |
| Online bitmap admission/cut | `revision/prefix_policy.hpp`, `online_engine.hpp`, `base_admission.py`, `online_controls.py` | `revision/model_evidence.zip` | `verify`; `revision/online_controls.py` |
| Transport reports | `operational/pan.py`; `revision/transport_replay.py` | 1,064 snapshots, 3,581,416 rows/1,064 requests; `operational_traces.zip` | `benchmark --suite retained --limit 0` |
| Validator CI, caching, repayment | `operational/ci_*`; `revision/ci_replay.py`, `ci_payback.py`, `order_sensitivity.py` | 1,226 tables, 6,733,663 rows/49,040 requests; `revision/evidence/ci-*` | `ci_replay.py pair/memo/fresh`; frozen summary |
| Fair retained CRoaring | `engine/roaring_index.hpp`, `roaring_suite.py` | Eight domains, 128 CI tables, BTS; `revision/evidence/roaring-*` | `engine/roaring_suite.py` |
| Monthly flight windows | `revision/bts.py`, `bts_replay.py` | 36 Jan 2022–Dec 2024 releases; `bts_input.zip` | BTS commands in reproduction guide |
| NHANES routing | `published_rules.py`, `published_run.cpp` | Three releases; necessary-nullness and coded answers separately | `published_rules.py --binary compiled/published_run.exe` |
| Cold layout/boundary sensitivity | `cases.py`, `extensions.py`, native controls | Eight public inputs; `evidence.zip` | `research/artifact/reproduce.py run` |

## File ablations

```powershell
python research/artifact/pageaudit/benchmark.py --fcc datasets/fcc --stops datasets/stops/panels --methods sql cert merge score scorelocal --repeats 5 --out outputs/file-full
python research/artifact/pageaudit/benchmark.py --fcc datasets/fcc --stops datasets/stops/panels --methods sql merge packed boundary_pos boundary --repeats 5 --out outputs/file-boundary
python research/artifact/pageaudit/benchmark.py --fcc datasets/fcc --stops datasets/stops/panels --methods sql dense roaring boundary residual --repeats 5 --out outputs/file-bitmap
python research/artifact/pageaudit/benchmark.py --fcc datasets/fcc --stops datasets/stops/panels --methods sql dense boundary endpoint_dense endpoint --repeats 5 --out outputs/file-endpoint
python research/artifact/pageaudit/benchmark.py --fcc datasets/fcc --stops datasets/stops/panels --methods sql endpoint_sparse endpoint_dense endpoint endpoint8 --repeats 5 --out outputs/file-cuts
python research/artifact/pageaudit/benchmark.py --fcc datasets/fcc --stops datasets/stops/panels --methods sql endpoint segment_one segment packed --repeats 5 --out outputs/file-segments
python research/artifact/pageaudit/profile_work.py --exe compiled/native/profile_segments.exe --panels datasets/stops/panels --out outputs/segment-work.csv
```

Structural profiling reports actual probes/segment work. The small schedule enumerations in `verify` do not replace real-input comparisons. For typed sensitivity:

```powershell
python research/artifact/livegroups/typed.py --cache datasets/stops --out outputs/typed-checks.json ca_bakersfield co_aurora mn_saint_paul oh_statewide wa_statewide
```

Then add `--typed datasets/stops/typed` and an explicit `--only` query list to the file driver. `publication_checks.py --cache datasets/stops --out outputs/publication-checks.json` independently checks source cardinalities and plotted Ohio rates.

The `cert` operator returns per-check information. Scalar operators do not recover field identity. Resident, file, and retained representations are separate execution contracts; no driver treats them as an automatically selected single pipeline.
