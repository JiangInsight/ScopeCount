

import argparse, hashlib, json, sys
from pathlib import Path
import pandas as pd

H = Path(__file__).resolve()
ROOT = H.parents[3]
sys.path.insert(0, str(H.parents[1] / "engine"))
import replay

MEMO = ["tree_direct_memo", "bitmap_direct_memo", "sql_opt_memo"]
FULL = [
    "tree_direct",
    "bitmap_direct",
    "online_direct",
    "lazy",
    "synopsis",
    "sql_opt",
    "independent",
    "words",
    "leaf",
]


def select(base):
    data = pd.read_csv(base / "manifest.tsv", sep="\t", keep_default_na=False)
    frame = data[data.status == "ok"].copy()
    assert not frame[["feed", "table"]].duplicated().any()
    frame["rows"] = pd.to_numeric(frame.rows).astype(int)
    frame["draw"] = frame.apply(
        lambda r: hashlib.sha256(
            ("scope5-ci-before-timing:" + r.feed + ":" + r.table).encode()
        ).hexdigest(),
        axis=1,
    )

    frame = frame.sort_values(["table", "rows", "feed"])
    frame["bucket"] = frame.groupby("table")["rows"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 8, labels=False, duplicates="drop")
    )
    subset = (
        frame.sort_values("draw").groupby(["table", "bucket"], group_keys=False).head(8)
    )
    return frame, subset


def run(base, out, mode, repeats):
    frame, subset = select(base)
    methods = {"memo": MEMO, "fresh": FULL, "pair": ["tree_direct", "bitmap_direct"]}[
        mode
    ]
    frame = subset if mode == "fresh" else frame
    out.mkdir(parents=True, exist_ok=True)
    con = replay.connect()
    try:
        for k, row in enumerate(frame.itertuples(), start=1):
            key = row.feed + "-" + row.table
            path = base / "feeds" / row.feed / row.table
            target = out / (key + ".tsv")
            if target.exists():
                saved = pd.read_csv(
                    target,
                    sep="\t",
                    usecols=["backend", "rep", "ordinal", "results"],
                    dtype={"results": str},
                )
                expected = ",".join(map(str, json.loads(row.observed)))
                counts = saved.groupby(["backend", "rep"]).ordinal.agg(
                    ["size", "nunique", "min", "max"]
                )
                n = int(row.requests)
                if (
                    set(saved.backend) != set(methods)
                    or set(saved.rep) != set(range(repeats))
                    or len(counts) != len(methods) * repeats
                    or not (saved.results == expected).all()
                    or not (counts[["size", "nunique", "max"]] == n).all().all()
                    or not (counts["min"] == 1).all()
                ):
                    raise ValueError(
                        f"Existing timing has different coverage or answers: {target}"
                    )
                continue
            result = replay.run(
                path.with_suffix(".rows"),
                path.with_suffix(".tsv"),
                repeats=repeats,
                methods=methods,
                con=con,
                dataset=key,
            )
            expected = tuple(json.loads(row.observed))
            if not all(
                tuple(map(int, x["results"].split(","))) == expected for x in result
            ):
                raise AssertionError(key)
            replay.save(result, target)
            if k % 25 == 0:
                print(mode, k, len(frame), flush=True)
    finally:
        con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["memo", "fresh", "pair"])
    p.add_argument("--repeats", type=int, default=5)
    a = p.parse_args()
    run(ROOT / "traces" / "ci", ROOT / "revision" / ("ci-" + a.mode), a.mode, a.repeats)
