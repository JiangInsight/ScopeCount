

from pathlib import Path
import json
import pandas as pd
import numpy as np

R = Path(__file__).resolve().parents[3]


def make():
    d = pd.read_csv(R / "revision" / "bts" / "months.tsv", sep="\t")
    assert len(d) == 36 * 4 * 5 and d.groupby("ordinal").results.nunique().max() == 1
    times = {}
    for m, g in d.groupby("backend"):
        g = g.sort_values(["rep", "ordinal"])
        q = g.request_ns.to_numpy().reshape(5, -1)
        b = g.groupby("rep").index_build_ns.first().to_numpy()
        times[m] = b[:, None] + q.cumsum(axis=1)

    def sec(m):
        return np.median(times[m][:, -1]) / 1e9

    def lead(a, b):
        good = np.median(times[a] - times[b], axis=0) <= 0
        if not good[-1]:
            return "none"
        lost = np.flatnonzero(~good)
        return str(lost[-1] + 2 if lost.size else 1)

    names = ["tree_direct", "bitmap_direct", "online_direct", "sql_opt"]
    data = {
        m: dict(
            seconds=sec(m),
            cross_dense=lead(m, "bitmap_direct"),
            cross_sql=lead(m, "sql_opt"),
        )
        for m in names
    }
    print(json.dumps(data, indent=2))
    text = (
        r"\emph{Monthly airline windows.} The BTS extract contains 20,656,085 rows and 46 observed signatures across 63 consecutive source fields. "
        r"The eight specified conjunctions span 36 actual monthly file windows, so every request has different endpoints. "
        + "From initial construction through the final month, the tree, dense bitmap, online policy and native SQL took "
        + ", ".join(f"{sec(m):.2f}" for m in names[:3])
        + f" and {sec(names[3]):.2f} seconds, respectively. "
        + "The largest snapshot tests whether the representations remain usable when the row count grows faster than the signature vocabulary. "
        + "The monthly intervals come from the publisher, while the audit definitions and their repetition over those intervals are experimental choices.\n"
    )
    (R / "research" / "bts_results.tex").write_text(text, encoding="utf8")


if __name__ == "__main__":
    make()
