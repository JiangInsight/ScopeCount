

import argparse
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from stops import DEFAULT, WEEKLY


def package(cache, timings, out):
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    oracles = []
    runs = []
    setup = []
    for name in WEEKLY:
        panel = cache / "panels" / name
        meta = json.loads((panel / "case.json").read_text())
        cases.append(meta)
        setup.append(
            dict(
                dataset=name,
                **json.loads((timings / (name + "-setup.json")).read_text()),
            )
        )
        for dim in meta["queries"]:
            o = pd.read_csv(panel / ("oracle-" + dim + ".csv"))
            o.insert(0, "dim", dim)
            o.insert(0, "dataset", name)
            oracles.append(o)
            runs.append(pd.read_csv(timings / f"{name}-{dim}.csv"))
    (out / "source_manifest.json").write_text(json.dumps(cases, indent=2) + "\n")
    pd.DataFrame(setup).to_csv(out / "load.csv", index=False)
    frame = pd.concat(runs, ignore_index=True)

    for name, data in [
        ("oracles.csv.gz", pd.concat(oracles)),
        ("trials.csv.gz", frame),
    ]:
        dst = out / name
        dst.write_bytes(
            gzip.compress(
                data.to_csv(index=False, lineterminator="\n").encode(), mtime=0
            )
        )
    med = frame.groupby(["dataset", "dim", "method"]).ns.median().unstack() / 1e6
    tails = (
        frame.groupby(["dataset", "dim", "method"]).ns.quantile(0.95).unstack() / 1e6
    )
    sizes = frame.groupby(["dataset", "dim"])[
        ["rows", "groups", "runs", "width"]
    ].first()
    summary = sizes.join(med.add_suffix("_ms")).join(tails.add_suffix("_p95_ms"))
    summary.to_csv(out / "panels.csv", float_format="%.6f")
    for meth in med:
        print(
            meth,
            "sum of medians ms",
            round(med[meth].sum(), 2),
            "wins vs sql_count",
            int((med[meth] < med.sql_count).sum()),
            "geomean speedup",
            round(np.exp(np.log(med.sql_count / med[meth]).mean()), 3),
        )
    horizons = []
    for entry in setup:
        name = entry["dataset"]
        point = med.loc[name]
        direct = point[["sql_count", "sql_row"]].min(axis=1).sum()
        weighted, degree = point.scope_weight.sum(), point.row_degree.sum()
        build = float(np.median(entry["row_degree_build_ns"])) / 1e6
        horizons.append(
            dict(
                dataset=name,
                observed_queries=len(point),
                build_ms=build,
                direct_sql_ms=direct,
                unindexed_weight_ms=weighted,
                degree_query_ms=degree,
                charged_degree_ms=build + degree,
                degree_repeats_vs_weight=(
                    int(np.floor(build / (weighted - degree))) + 1
                    if weighted > degree
                    else None
                ),
                degree_repeats_vs_sql=(
                    int(np.floor(build / (direct - degree))) + 1
                    if direct > degree
                    else None
                ),
            )
        )
    horizon = pd.DataFrame(horizons)
    horizon.to_csv(out / "observed_horizons.csv", index=False, float_format="%.6f")
    print(
        "observed totals",
        horizon[
            [
                "build_ms",
                "direct_sql_ms",
                "unindexed_weight_ms",
                "degree_query_ms",
                "charged_degree_ms",
            ]
        ]
        .sum()
        .to_dict(),
    )
    print(
        "raw rows",
        sum(c["raw_rows"] for c in cases),
        "vehicular",
        sum(c["vehicular_rows"] for c in cases),
        "query rows",
        sizes.rows.sum(),
        "groups",
        sizes.groups.sum(),
        "widths",
        min(sizes.width),
        max(sizes.width),
        "trials",
        len(frame),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=DEFAULT)
    p.add_argument("--timings", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    package(args.cache, args.timings, args.out)
