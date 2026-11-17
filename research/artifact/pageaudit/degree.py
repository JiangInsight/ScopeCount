

import argparse
import json
import os
import random
import time
from pathlib import Path

import duckdb
import pandas as pd

from benchmark import commands, ident, jobs
from check import quote


def run(cache, output, repeats, fcc):
    db = duckdb.connect(config={"threads": 1})
    cases = {}
    for name, file, group, fields, missing, n, gold in jobs(
        cache / "panels", fcc, False
    ):
        if missing:
            cases.setdefault(file, []).append((name, group, fields, n, sorted(gold)))
    samples = []
    for file, tasks in cases.items():
        meta = json.loads((file.parent / "case.json").read_text())
        source = f"read_parquet({quote(file.as_posix())})"
        terms = [f"({ident('v_'+f)} IS NULL)::INTEGER" for f in meta["fields"]]
        create = (
            "CREATE TEMP TABLE degrees AS SELECT week,hour,("
            + "+".join(terms)
            + f")::UTINYINT AS d FROM {source}"
        )
        rng = random.Random(file.parent.name)
        for rep in range(repeats):
            methods = ["degree", "inline", "counts"]
            rng.shuffle(methods)
            for method in methods:
                build = 0
                if method == "degree":
                    start = time.perf_counter_ns()
                    db.execute(create)
                    build = time.perf_counter_ns() - start
                for name, group, fields, n, gold in tasks:
                    if method == "degree":
                        sql = f"SELECT {group},count(*),sum(d) FROM degrees WHERE {group} IS NOT NULL GROUP BY 1 ORDER BY 1"
                    elif method == "inline":
                        expr = "+".join(
                            f"({ident(f)} IS NULL)::INTEGER" for f in fields
                        )
                        sql = f"SELECT {group},count(*),sum({expr}) FROM {source} WHERE {group} IS NOT NULL GROUP BY 1 ORDER BY 1"
                    else:
                        sql = commands(file, group, fields, True, n)[0]["sql"]
                    start = time.perf_counter_ns()
                    actual = db.execute(sql).fetchall()
                    elapsed = time.perf_counter_ns() - start
                    assert gold == actual
                    samples.append(
                        [file.parent.name, name, rep, method, build, elapsed]
                    )
                    build = 0
                if method == "degree":
                    db.execute("DROP TABLE degrees")
        output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            samples,
            columns=["table", "dataset", "rep", "method", "build_ns", "query_ns"],
        ).to_csv(output, sep="\t", index=False)
        print(file.parent.name, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--cache",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "datasets/stops",
    )
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--fcc", type=Path, default=Path(__file__).resolve().parents[3]/"datasets/fcc")
    p.add_argument("--repeats", type=int, default=5)
    a = p.parse_args()
    run(a.cache, a.out, a.repeats, a.fcc)
