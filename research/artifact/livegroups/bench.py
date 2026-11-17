

import argparse
import csv
import json
import random
import statistics
import time
from pathlib import Path

import duckdb
import numpy as np

from stops import DEFAULT, MISSING, WEEKLY

METHODS = [
    "sql_count",
    "sql_row",
    "scope_rows",
    "scope_stream",
    "scope_runs",
    "scope_wrows",
    "scope_wliteral",
    "scope_wmargin",
    "scope_weight",
    "row_degree",
]


def statements(dim, fields):
    inputs = [
        "v_" + field
        for field in fields
        if field != {"week": "date", "hour": "time"}[dim]
    ]
    width = len(inputs)
    select = f"SELECT {dim} AS key, count(*)::BIGINT AS n, "
    group = f" FROM src WHERE {dim} IS NOT NULL GROUP BY {dim} ORDER BY key"
    counts = " + ".join("COUNT(" + field + ")" for field in inputs)
    absent = " + ".join("(" + field + " IS NULL)::INTEGER" for field in inputs)
    sql = {
        "sql_count": select + f"{width}*COUNT(*) - ({counts}) AS missing" + group,
        "sql_row": select + f"SUM({absent})::BIGINT AS missing" + group,
    }
    total = " + ".join(f"x.c{i + 1}" for i in range(width))
    for method in METHODS[2:-1]:
        count = (
            "x.c1"
            if method
            in ("scope_wrows", "scope_wliteral", "scope_wmargin", "scope_weight")
            else total
        )
        args = ", ".join([dim] + inputs)
        sql[method] = (
            f"SELECT x.key, x.n, {width}*x.n - ({count}) AS missing "
            f"FROM (SELECT UNNEST({method}{width}({args})) AS x "
            f"FROM src WHERE {dim} IS NOT NULL) ORDER BY x.key"
        )
    sql["row_degree"] = (
        f"SELECT {dim} AS key, count(*)::BIGINT AS n, sum(degree)::BIGINT AS missing "
        f"FROM row_degrees WHERE {dim} IS NOT NULL GROUP BY {dim} ORDER BY key"
    )
    return sql


def run_panel(db, panel, dim, meta, reps, output):
    with (panel / f"oracle-{dim}.csv").open() as f:
        oracle = [
            tuple(map(int, (r["key"], r["n"], r["missing"]))) for r in csv.DictReader(f)
        ]
    keys = np.memmap(panel / (dim + ".i32"), "<i4", "r")
    valid = keys[keys != MISSING]
    runs = (1 + np.count_nonzero(valid[1:] != valid[:-1])) if valid.size else 0
    sql = statements(dim, meta["fields"])
    schedule = []
    rng = random.Random(meta["dataset"] + dim)
    for start in range(0, reps, len(METHODS)):
        order = METHODS.copy()
        rng.shuffle(order)
        for offset in range(min(len(order), reps - start)):
            schedule.append(order[offset:] + order[:offset])
    samples = []
    for method in METHODS:
        db.execute("PREPARE replay_" + method + " AS " + sql[method])
        if db.execute("EXECUTE replay_" + method).fetchall() != oracle:
            raise AssertionError((meta["dataset"], dim, method, "warmup"))
    for round_id, order in enumerate(schedule):
        for position, method in enumerate(order):
            start = time.perf_counter_ns()
            actual = db.execute("EXECUTE replay_" + method).fetchall()
            ns = time.perf_counter_ns() - start
            if actual != oracle:
                raise AssertionError((meta["dataset"], dim, method, round_id))
            samples.append(
                dict(
                    dataset=meta["dataset"],
                    dim=dim,
                    method=method,
                    round=round_id,
                    position=position,
                    ns=ns,
                    rows=int(valid.size),
                    groups=len(oracle),
                    runs=int(runs),
                    width=len(meta["fields"]) - 1,
                )
            )
    dst = output / (meta["dataset"] + "-" + dim + ".csv")
    with dst.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(samples[0]))
        w.writeheader()
        w.writerows(samples)
    summary = {
        k: round(
            statistics.median(s["ns"] for s in samples if s["method"] == k) / 1e6, 2
        )
        for k in METHODS
    }
    print(meta["dataset"], dim, len(oracle), int(runs), summary, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reps", type=int, default=20)
    parser.add_argument("names", nargs="*")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name in args.names or WEEKLY:
        panel = args.cache / "panels" / name
        meta = json.loads((panel / "case.json").read_text())
        db = duckdb.connect(config={"threads": 1, "allow_unsigned_extensions": True})
        dll = args.extension.as_posix().replace("'", "''")
        db.execute(f"LOAD '{dll}'")
        start = time.perf_counter_ns()
        db.execute(
            "CREATE TABLE src AS FROM read_parquet(?)", [str(panel / "input.parquet")]
        )
        load_ns = time.perf_counter_ns() - start
        missing = " + ".join("(v_" + f + " IS NULL)::INTEGER" for f in meta["fields"])
        degree_build_ns = []
        for i in range(5):
            if i:
                db.execute("DROP TABLE row_degrees")
            start = time.perf_counter_ns()
            db.execute(
                "CREATE TEMP TABLE row_degrees AS SELECT week, hour, ("
                + missing
                + ")::UTINYINT AS degree FROM src"
            )
            degree_build_ns.append(time.perf_counter_ns() - start)
        setup = dict(
            load_ns=load_ns,
            row_degree_build_ns=degree_build_ns,
            duckdb=duckdb.__version__,
        )
        (args.out / (name + "-setup.json")).write_text(json.dumps(setup))
        for dim in meta["queries"]:
            run_panel(db, panel, dim, meta, args.reps, args.out)
        db.close()


if __name__ == "__main__":
    main()
