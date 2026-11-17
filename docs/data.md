# Inputs and provenance

`python reproduce.py restore` verifies and expands bundled validity/key/scope projections and published output counts. Original identifiers/payloads are omitted. Manifests preserve URLs, request identities/timestamps where available, schemas, hashes, and answer digests.

| Input | Public source | Reconstruction |
|---|---|---|
| Traffic stops | [Stanford](https://openpolicing.stanford.edu/data/); [pinned analysis](https://github.com/saatvikkher/missing-traffic/tree/9abc320a6b1bf7fd27ea3c7964dd9ed8a69a81f6) | `python reproduce.py fetch --all-sources` |
| FCC | [BuzzFeed analysis](https://github.com/BuzzFeedNews/2019-10-fcc-comments/tree/8f10873fa3e6d91bbb2396485d159a27c8e8e775); [archive](https://archive.org/details/fcc-comments-and-bulk-uploads) | `python research/artifact/trace_fcc.py prepare --base datasets/fcc-source` |
| SQLShare | [UW release](https://uwescience.github.io/sqlshare/data_release.html) | `python research/artifact/sqlshare_groups/prepare.py --root datasets/sqlshare-source` |
| Transport reports | [transport.data.gouv.fr](https://transport.data.gouv.fr/) | `python research/artifact/operational/pan.py --out traces/transport-new` |
| Validator | [MobilityData](https://github.com/MobilityData/gtfs-validator) Nov 1–7, 2026 acceptance tests | Run `ci_download.py`, `ci_inputs.py`, `ci_trace.py` in `research/artifact/operational` |
| Flights | [BTS original monthly files](https://transtats.bts.gov/PREZIP/) | `python research/artifact/revision/bts.py --dir datasets/bts-source` |
| Eight cold/retained inputs | URLs/hashes in restored `data/*.json` | `python research/artifact/prepare.py --cache datasets/raw --data datasets/rebuilt` |
| NHANES routing | [CDC](https://wwwn.cdc.gov/nchs/nhanes/) | `python research/artifact/published_rules.py --binary compiled/published_run.exe` |

Traffic-stop requests are 19 weekly and six hourly published analyses, not production arrival logs. Manifests pin 92.68 million raw and 90.96 million vehicular rows; overlapping scopes visit 117.28 million rows. All 9,020 grouped tuples are preserved. Python reconstruction requires matching independent base-R oracle hashes; the original base-R extractor remains available.

SQLShare retains 27 logged count components. Eleven statements are count/key-only; sixteen contain other aggregates outside this comparison. Released snapshots need not equal historical live tables. Every counted field is present in this subset, so informed `COUNT(*)` is included. The selection and exclusions are preserved.

Transport/CI requests are observed, and CI retains both zero-result route tables and positive trip cases. Timing repetitions do not create demand. Remote action artifacts and live transport resources can expire/change; use digest-checked frozen projections to reproduce the paper cohort. A fresh scrape is a new cohort.

Typed traffic-stop sensitivity retains original values only in local reconstruction. Original publishers' data-use terms apply; this repository does not expand those rights.
