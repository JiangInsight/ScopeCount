

from pathlib import Path
import argparse, json, random, time
import numpy as np
import pandas as pd
import pyarrow as pa
from fcc import connect

HERE = Path(__file__).resolve().parent
CASES = [
    (g, s)
    for g in ("runs", "interleaved", "many")
    for s in ("few_scores", "independent")
]
W = 16
METHODS = [
    "sql_counts",
    "sql_row_total",
    "wrows",
    "wliteral",
    "wmargin",
    "weight",
    "runs",
]


def inputs(n, group_mode, score_mode):
    rng = np.random.default_rng(20260701)
    if group_mode == "runs":
        groups = (np.arange(n, dtype=np.uint32) // 4096) % 16
    elif group_mode == "interleaved":
        groups = np.arange(n, dtype=np.uint32) % 6
    else:
        groups = rng.integers(0, 4096, n, dtype=np.uint32)
    if score_mode == "few_scores":

        labels = rng.choice(np.array([1, 2, 4]), n)
        perm = np.argsort(rng.random((n, W), dtype=np.float32), axis=1).astype(np.uint8)
        valid = perm < labels[:, None]
    else:
        valid = rng.integers(0, 2, (n, W), dtype=np.uint8).astype(bool)
    cols = {"g": pa.array(groups)}
    values = np.ones(n, dtype=bool)
    for j in range(W):
        cols["v" + str(j)] = pa.array(values, mask=~valid[:, j])
    oracle = np.zeros((int(groups.max()) + 1, 2), dtype=np.int64)
    np.add.at(oracle[:, 0], groups, 1)
    np.add.at(oracle[:, 1], groups, valid.sum(axis=1).astype("int64"))
    expected = [(i, *map(int, row)) for i, row in enumerate(oracle) if row[0]]
    return pa.table(cols), expected


def statement(op):
    cols = [f"v{j}" for j in range(W)]
    if op.startswith("sql_"):
        agg = (
            "+".join(f"count({c})" for c in cols)
            if op == "sql_counts"
            else "sum(" + "+".join(f"({c} IS NOT NULL)::INTEGER" for c in cols) + ")"
        )
        return f"SELECT g,count(*),{agg} FROM src GROUP BY g ORDER BY g"
    projected = "+".join(f"x.c{j+1}" for j in range(W)) if op == "runs" else "x.c1"
    return f"SELECT x.key,x.n,{projected} FROM (SELECT unnest(scope_{op}{W}(g,{','.join(cols)})) AS x FROM src) q ORDER BY x.key"


def run(n, reps, out):
    out.mkdir(exist_ok=True, parents=True)
    c = connect()
    try:
        for k, (groups, scores) in enumerate(CASES):
            t, expected = inputs(n, groups, scores)
            c.register("input_arrow", t)
            c.execute("CREATE OR REPLACE TABLE src AS SELECT * FROM input_arrow")
            c.unregister("input_arrow")
            rng = random.Random(202611 + k)
            records = []
            for block in range(0, reps, len(METHODS)):
                order = METHODS.copy()
                rng.shuffle(order)
                shifts = list(range(len(order)))
                rng.shuffle(shifts)
                for slot_shift, shift in enumerate(shifts[: reps - block]):
                    for slot, op in enumerate(order[shift:] + order[:shift]):
                        q = statement(op)
                        start = time.perf_counter_ns()
                        res = c.execute(q).fetchall()
                        end = time.perf_counter_ns()
                        assert res == expected, (groups, scores, op)
                        records.append(
                            dict(
                                groups=groups,
                                scores=scores,
                                rows=n,
                                fields=W,
                                rep=block + slot_shift,
                                slot=slot,
                                op=op,
                                time_ns=end - start,
                            )
                        )
            d = pd.DataFrame(records)
            d.to_csv(out / f"{groups}-{scores}.tsv", sep="\t", index=False)
            print(
                groups,
                scores,
                d.groupby("op").time_ns.median().div(1e6).round(2).to_dict(),
                flush=True,
            )
    finally:
        c.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=524288)
    p.add_argument("--reps", type=int, default=14)
    p.add_argument("--out", type=Path, default=HERE / "evidence" / "controls")
    a = p.parse_args()
    run(a.rows, a.reps, a.out)
