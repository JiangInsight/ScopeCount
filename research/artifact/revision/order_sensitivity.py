

import json, hashlib, sys
from pathlib import Path
import pandas as pd

here = Path(__file__).resolve()
p = here.parents[3]
sys.path.insert(0, str(here.parents[1] / "engine"))
import replay, ci_replay


def run():
    con = replay.connect()
    try:
        ci = p / "traces" / "ci"
        _, subset = ci_replay.select(ci)
        pan = p / "traces" / "transport"
        f = pd.read_csv(pan / "manifest.tsv", sep="\t", keep_default_na=False)
        f = f[f.status == "ok"].copy()
        f["rank"] = [
            hashlib.sha256(f"order:{r.resource}/{r.table}".encode()).hexdigest()
            for r in f.itertuples()
        ]
        for group, frame, methods in [
            ("ci-order", subset, ci_replay.MEMO),
            (
                "pan-order",
                f.sort_values("rank").groupby("table").head(64),
                ["tree_direct", "bitmap_direct", "sql_opt"],
            ),
        ]:
            for r in frame.itertuples():
                source = (
                    ci / "feeds" / r.feed / r.table
                    if group == "ci-order"
                    else pan / "resources" / str(r.resource) / r.table
                )
                key = source.parent.name + "-" + r.table
                out = p / "revision" / group / (key + ".tsv")
                result = replay.run(
                    source.with_suffix(".rows"),
                    source.with_suffix(".tsv"),
                    5,
                    methods,
                    con=con,
                    dataset=key,
                    balanced=True,
                )
                expected = ",".join(map(str, json.loads(r.observed)))
                assert all(d["results"] == expected for d in result)
                replay.save(result, out)
    finally:
        con.close()


if __name__ == "__main__":
    run()
