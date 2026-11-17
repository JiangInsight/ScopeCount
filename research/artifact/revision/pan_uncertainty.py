

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

here = Path(__file__).resolve()
root = here.parents[3]


def calculate():
    frame = pd.read_csv(root / "revision" / "summaries" / "pan-direct-totals.csv")
    ms = frame.pivot(index="dataset", columns="method", values="paid_ns")
    ms["resource"] = [n.split("-")[0] for n in ms.index]
    group = ms.groupby("resource").sum()
    assert len(group) == 532
    rng = np.random.default_rng(4731)
    draw = rng.integers(0, len(group), size=(2000, len(group)))
    for m, ref in [
        ("tree_direct", "bitmap_direct"),
        ("tree_direct", "sql_opt"),
        ("online_direct", "bitmap_direct"),
    ]:
        x = group[m].to_numpy()
        y = group[ref].to_numpy()
        print(
            m,
            ref,
            "total ratio",
            x.sum() / y.sum(),
            "95% resource bootstrap",
            np.quantile(x[draw].sum(axis=1) / y[draw].sum(axis=1), [0.025, 0.975]),
        )


if __name__ == "__main__":
    calculate()
