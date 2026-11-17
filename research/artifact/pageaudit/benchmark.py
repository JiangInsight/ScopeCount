

import argparse, csv, hashlib, json, os, random, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from check import connect, pagequery, quote, ROOT


def ident(s):
    return '"' + s.replace('"', '""') + '"'


def jobs(stops, fcc, pilot):
    meta = json.loads((fcc / "evidence.json").read_text())
    rows = int(meta["rows"])
    yield "fcc", fcc / "input.parquet", "uploader", ["email"], False, rows, [
        tuple(map(int, x[:3])) for x in meta["expected"]
    ]
    for path in sorted(stops.glob("*/case.json")):
        case = json.loads(path.read_text())
        file = path.parent / "input.parquet"
        if pilot and case["dataset"] not in (
            "ca_bakersfield",
            "co_aurora",
            "mn_saint_paul",
        ):
            continue
        for dim in case["queries"]:
            fields = [
                "v_" + v
                for v in case["fields"]
                if v != ("date" if dim == "week" else "time")
            ]
            oracle = pd.read_csv(path.parent / f"oracle-{dim}.csv")
            yield case["dataset"] + "-" + dim, file, dim, fields, True, case[
                "vehicular_rows"
            ], list(oracle.itertuples(index=False, name=None))


def commands(file, group, fields, missing, n):
    schema = pq.ParquetFile(file).schema_arrow.names
    ks = schema.index(group)
    cs = [schema.index(f) for f in fields]
    rules = [(1 << c, 0) if missing else (0, 1 << c) for c in cs]
    threshold = "" if missing else " WHERE n>=10000"
    finish = lambda inner: f"SELECT g,n,k FROM ({inner}) t" + threshold + " ORDER BY g"
    counts = " + ".join("count(" + ident(f) + ")" for f in fields)
    summary = f"{len(fields)}*count(*)-({counts})" if missing else counts
    source = f"read_parquet({quote(file.as_posix())})"
    native = finish(
        f"SELECT {ident(group)} AS g,count(*) AS n,{summary} AS k FROM {source} WHERE {ident(group)} IS NOT NULL GROUP BY 1"
    )
    queries = {"sql": native}
    for mode in (
        "cert",
        "nosub",
        "runs",
        "incidence",
        "positive",
        "local",
        "local_nopivot",
        "merge",
        "score",
        "scorelocal",
        "packed",
        "boundary",
        "boundary_pos",
        "dense",
        "roaring",
        "residual",
        "endpoint",
        "endpoint_dense",
        "endpoint8",
        "endpoint_sparse",
        "segment",
        "segment_one",
    ):
        core = pagequery(file, ks, rules, 0, n, mode)
        total = "+".join(f"v[{i+3}]" for i in range(len(fields)))
        if mode in (
            "merge",
            "score",
            "scorelocal",
            "packed",
            "boundary",
            "boundary_pos",
            "dense",
            "roaring",
            "residual",
            "endpoint",
            "endpoint_dense",
            "endpoint8",
            "endpoint_sparse",
            "segment",
            "segment_one",
        ):
            total = "v[3]"
        queries[mode] = finish(
            f"SELECT v[1] AS g,v[2] AS n,{total} AS k FROM ({core}) q"
        )
    return queries, ks, rules


def run(args):
    con = connect()
    records = []
    profiles = []
    for name, file, group, fields, missing, n, oracle in jobs(
        args.stops, args.fcc, args.pilot
    ):
        if args.only and name not in args.only:
            continue
        if args.typed and name != "fcc":
            file = args.typed / file.parent.name / file.name
        queries, ks, rules = commands(file, group, fields, missing, n)
        gold = sorted(oracle)
        if args.methods:
            queries = {m: queries[m] for m in args.methods}
        schedule = list(queries)
        rng = random.Random(
            int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big")
        )
        for block in range(0, args.repeats, len(schedule)):
            rng.shuffle(schedule)
            offsets = list(range(len(schedule)))
            rng.shuffle(offsets)
            for j, offset in enumerate(offsets[: args.repeats - block]):
                for slot, m in enumerate(schedule[offset:] + schedule[:offset]):
                    a = time.perf_counter_ns()
                    rows = con.execute(queries[m]).fetchall()
                    dt = time.perf_counter_ns() - a
                    assert rows == gold, (name, m, rows[:2], gold[:2])
                    records.append(
                        [
                            name,
                            m,
                            block + j,
                            slot,
                            n,
                            len(fields),
                            len(rows),
                            file.stat().st_size,
                            dt,
                        ]
                    )
        for m in queries:
            if m == "sql":
                continue
            core = pagequery(file, ks, rules, 0, n, m)
            v = con.execute("SELECT v FROM (" + core + ") q LIMIT 1").fetchone()[0]
            profiles.append([name, m, *v[-4:]])
        args.out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            records,
            columns=[
                "dataset",
                "method",
                "rep",
                "slot",
                "rows",
                "fields",
                "groups",
                "bytes",
                "ns",
            ],
        ).to_csv(args.out / "trials.tsv", sep="\t", index=False)
        pd.DataFrame(
            profiles,
            columns=[
                "dataset",
                "method",
                "row_groups",
                "decoded",
                "certified",
                "skipped_words",
            ],
        ).to_csv(args.out / "profiles.tsv", sep="\t", index=False)
        print(name, len(gold), flush=True)
    con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    local = Path(__file__).resolve().parents[3] / "datasets"
    p.add_argument("--fcc", type=Path, default=local / "fcc")
    p.add_argument("--stops", type=Path, default=local / "stops/panels")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--only", nargs="+")
    p.add_argument("--methods", nargs="+")
    p.add_argument("--typed", type=Path)
    p.add_argument("--repeats", type=int, default=16)
    p.add_argument("--pilot", action="store_true")
    run(p.parse_args())
