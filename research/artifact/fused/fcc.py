

import argparse
from hashlib import sha256
import json, os, random, statistics, time
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LIB = Path(
    os.environ.get(
        "SCOPEFUSED_EXTENSION",
        HERE.parents[2]
        / "compiled"
        / "duckdb155_fused"
        / "scopefused.duckdb_extension",
    )
)
SOURCE = HERE.parents[2] / "datasets/fcc"
OUT = HERE.parents[2] / "revision" / "fused"


def connect(threads=1):
    con = duckdb.connect(
        config={"allow_unsigned_extensions": "true", "threads": str(threads)}
    )
    con.execute("LOAD '" + str(LIB).replace("'", "''") + "'")
    return con


def sql(method):
    if method == "sql":
        inner = "SELECT uploader AS key, count(*) AS n, count(email) AS k FROM src WHERE uploader IS NOT NULL GROUP BY uploader"
    else:
        inner = f"SELECT x.key,x.n,x.c1 AS k FROM (SELECT unnest(scope_{method}1(uploader,email)) AS x FROM src)"
    return f"SELECT key,n,k,round_even(k::DOUBLE/n,4) FROM ({inner}) g WHERE n>=10000 ORDER BY n DESC,key"


def benchmark(base, out, reps, layouts):
    evidence = json.loads((base / "evidence.json").read_text())
    expected = [(*x, float(np.round(x[2] / x[1], 4))) for x in evidence["expected"]]
    out.mkdir(exist_ok=True, parents=True)
    con = connect()
    methods = ["sql", "rows", "stream", "runs"]
    try:
        for layout in layouts:


            start = time.perf_counter_ns()
            order = (
                ""
                if layout == "original"
                else "ORDER BY hash(row_number() OVER (),20261109)"
            )
            con.execute(
                "CREATE OR REPLACE TEMP TABLE src AS SELECT uploader,email FROM read_parquet(?) "
                + order,
                [str(base / "input.parquet")],
            )
            load = time.perf_counter_ns() - start
            rng = random.Random(137831)
            records = []
            for block in range(0, reps, len(methods)):
                base_order = methods.copy()
                rng.shuffle(base_order)
                shifts = list(range(len(methods)))
                rng.shuffle(shifts)
                for shift in shifts[: reps - block]:
                    order = base_order[shift:] + base_order[:shift]
                    rep = block + shifts.index(shift)
                    for slot, method in enumerate(order):
                        q = sql(method)
                        start = time.perf_counter_ns()
                        actual = con.execute(q).fetchall()
                        duration = time.perf_counter_ns() - start
                        if actual != expected:
                            raise AssertionError((layout, method, actual, expected))
                        records.append(
                            dict(
                                layout=layout,
                                method=method,
                                rep=rep,
                                slot=slot,
                                load_ns=load,
                                request_ns=duration,
                                digest=sha256(json.dumps(actual).encode()).hexdigest(),
                            )
                        )
            frame = pd.DataFrame(records)
            frame.to_csv(out / (layout + ".tsv"), sep="\t", index=False)
            print(
                layout,
                frame.groupby("method").request_ns.median().div(1e6).round(3).to_dict(),
                flush=True,
            )
    finally:
        con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", type=Path, default=SOURCE)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--reps", type=int, default=21)
    p.add_argument(
        "--layouts",
        nargs="+",
        default=["original", "shuffled"],
        choices=["original", "shuffled"],
    )
    a = p.parse_args()
    benchmark(a.base, a.out, a.reps, a.layouts)
