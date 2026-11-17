

from pathlib import Path
import numpy as np
import pandas as pd

here = Path(__file__).resolve()
root = here.parents[2]
P = root.parent


def curves(d, m):
    x = d[d.backend == m].sort_values(["rep", "ordinal"])
    q = x.request_ns.to_numpy().reshape(5, -1)
    b = x.groupby("rep").index_build_ns.first().to_numpy()
    return b[:, None] + q.cumsum(axis=1)


def stable(a, b):
    lead = np.median(a - b, axis=0) <= 0
    if not lead[-1]:
        return None
    losses = np.flatnonzero(~lead)
    return int(losses[-1] + 2 if len(losses) else 1)


def make():
    out = []
    full = []
    for name in [
        "diabetes",
        "nhanes",
        "scania",
        "storm",
        "crash",
        "survey",
        "taxi",
        "maude",
    ]:
        d = pd.read_csv(P / "runs" / "engine" / (name + ".tsv"), sep="\t")
        methods = ["sql_opt", "bitmap_direct", "tree_direct", "online_direct"]
        sql, bitmap, tree, online = map(lambda m: curves(d, m), methods)
        times = np.array(
            [np.median(x[:, -1]) / 1e6 for x in [sql, bitmap, tree, online]]
        )
        crosses = [
            stable(x, ref) for x, ref in [(tree, sql), (bitmap, sql), (tree, bitmap)]
        ]
        reps = int((tree[:, -1] < bitmap[:, -1]).sum())
        crossing_labels = [f"Not by {tree.shape[1]}" if n is None else str(n) for n in crosses]
        out.append(
            (
                "NHANES"
                if name == "nhanes"
                else "MAUDE" if name == "maude" else name.title()
            )
            + " & "
            + " & ".join(f"{t:,.1f}" for t in times)
            + " & "
            + " & ".join(crossing_labels)
            + " & "
            + str(reps)
            + r" \\"
        )
        full.append([name, *times, *crosses, reps])
    (root / "revision_engine_rows.tex").write_text(
        "\n".join(out) + r"\bottomrule" + "\n"
    )
    print(pd.DataFrame(full).to_string(index=False, header=False))


if __name__ == "__main__":
    make()
