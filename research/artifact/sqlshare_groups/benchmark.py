

import argparse
from pathlib import Path
from hashlib import sha256
import json
import os
import random
import time

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LIB = ROOT / "compiled" / "duckdb155_fused" / "scopefused.duckdb_extension"


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def statement(method, q, path=None, rows=None):
    source = "src" if path is None else f"read_parquet({literal(path.as_posix())})"
    if method in ("sql", "metadata_star"):
        agg = "count(v0)" if method == "sql" else "count(*)"
        inner = f"SELECT g, {agg} AS k FROM {source} GROUP BY g"
    elif path is not None:

        raw = f"read_blob({literal(path.as_posix())})"
        data = f"SELECT UNNEST(scope_page_counts(content,0,'0/2',0,{rows},{literal(method)})) AS v FROM {raw}"
        inner = f"SELECT v[1] AS g, v[3] AS k FROM ({data}) c"
    else:
        inner = f"SELECT x.key AS g,x.c1 AS k FROM (SELECT UNNEST(scope_{method}1(g,v0)) AS x FROM src)"
    fields = "g,k" if q["include_key"] else "k"
    return (
        "SELECT "
        + fields
        + " FROM ("
        + inner
        + ") c"
        + (" WHERE k=1" if q["count_one"] else "")
        + (" ORDER BY g" if q["ordered"] else "")
    )


def benchmark(data, out, repeats, file_replay=False, methods_override=None):
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    methods = (
        ["sql", "metadata_star", "cert", "positive", "incidence", "local"]
        if file_replay
        else ["sql", "metadata_star", "rows", "stream", "runs"]
    )
    if methods_override:
        methods = methods_override
    library = (
        ROOT / "compiled/scopepages/scopepages.duckdb_extension" if file_replay else LIB
    )
    if file_replay and os.getenv("SCOPEPAGE_BUILD"):
        library = Path(os.environ["SCOPEPAGE_BUILD"]) / "scopepages.duckdb_extension"
    out.mkdir(exist_ok=True, parents=True)
    manifest = json.loads((data / "manifest.json").read_text())
    rec = []
    coverage = []
    for s in manifest["sources"]:
        name = s["dataset"]
        path = data / (name + ".parquet")
        assert sha256(path.read_bytes()).hexdigest() == s["file_sha256"]
        src = pq.read_table(path)
        g = src["g"].to_numpy()
        values = src["v0"].combine_chunks().is_valid().to_numpy(zero_copy_only=False)
        sizes = np.bincount(g)
        hits = np.bincount(g[values], minlength=len(sizes))
        oracle = list(zip(range(len(sizes)), map(int, sizes), map(int, hits)))
        assert (
            sha256(np.asarray(oracle, dtype="<u8").tobytes()).hexdigest()
            == s["answers_sha256"]
        )


        assert s["null_counts"] == 0 and np.array_equal(sizes, hits)
        with duckdb.connect(
            config={"allow_unsigned_extensions": "true", "threads": "1"}
        ) as db:
            db.execute("LOAD " + literal(library.as_posix()))
            load = 0
            if not file_replay:
                start = time.perf_counter_ns()
                db.execute(
                    "CREATE TEMP TABLE src AS SELECT * FROM read_parquet(?)",
                    [str(path)],
                )
                load = time.perf_counter_ns() - start
            queries = {}
            for q in s["requests"]:
                result = [
                    (i, k) if q["include_key"] else (k,)
                    for i, n, k in oracle
                    if not q["count_one"] or k == 1
                ]
                if not q["ordered"]:
                    result.sort()
                for m in methods:
                    queries[q["id"], m] = (
                        statement(m, q, path if file_replay else None, s["rows"]),
                        result,
                    )

            rng = random.Random(417 + int(name[1:]))
            for startrep in range(0, repeats, len(methods)):
                order = methods.copy()
                rng.shuffle(order)
                rotations = list(range(len(methods)))
                rng.shuffle(rotations)
                for off, rot in enumerate(rotations[: repeats - startrep]):
                    rep = startrep + off
                    for slot, m in enumerate(order[rot:] + order[:rot]):
                        for q in s["requests"]:
                            sql, want = queries[q["id"], m]
                            tic = time.perf_counter_ns()
                            actual = db.execute(sql).fetchall()
                            dt = time.perf_counter_ns() - tic
                            if not q["ordered"]:
                                actual.sort()
                            assert actual == want, (q["id"], m)
                            rec.append(
                                dict(
                                    dataset=name,
                                    query=q["id"],
                                    method=m,
                                    rep=rep,
                                    slot=slot,
                                    request_ns=dt,
                                    rows=s["rows"],
                                    groups=s["groups"],
                                    runs=s["runs"],
                                    outputs=len(actual),
                                    load_ns=load,
                                    count_projection=q["count_projection"],
                                )
                            )
            coverage.append(
                dict(
                    dataset=name,
                    n=len(s["requests"]),
                    pure=sum(not q["count_projection"] for q in s["requests"]),
                )
            )
    frame = pd.DataFrame(rec)
    frame.to_csv(out / "timings.tsv", index=False, sep="\t")
    trace = (
        frame.groupby(["dataset", "method", "rep"]).request_ns.sum().unstack("method")
    )
    medians = trace.groupby("dataset").median() / 1e6
    summary = dict(
        records=len(rec),
        requests=int(frame["query"].nunique()),
        groups=len(coverage),
        rows=sum(s["rows"] for s in manifest["sources"]),
        paid_ms=medians.sum().to_dict(),
        full_count_queries=sum(s["pure"] for s in coverage),
    )
    if file_replay:
        for method in methods[2:]:
            for baseline in methods[:2]:
                paired = trace[method] - trace[baseline]
                summary[f"wins_{method}_{baseline}"] = int(
                    (paired.groupby("dataset").median() < 0).sum()
                )
        summary["extension_sha256"] = sha256(library.read_bytes()).hexdigest()
    else:
        for cmp in ["rows", "stream", "sql", "metadata_star"]:
            paired = trace["runs"] - trace[cmp]
            summary["wins_" + cmp] = int((paired.groupby("dataset").median() < 0).sum())
            summary["alltrials_" + cmp] = int(
                (paired < 0).groupby("dataset").all().sum()
            )
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(summary, flush=True)
    print(medians.round(3))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, default=ROOT / "traces" / "service_groups")
    p.add_argument("--out", type=Path)
    p.add_argument("--repeats", type=int, default=15)
    p.add_argument(
        "--file-replay",
        action="store_true",
        help="Read the frozen Parquet projection anew per request",
    )
    p.add_argument(
        "--methods",
        nargs="+",
        help="Use SQL and informed SQL first, then the selected file operators",
    )
    a = p.parse_args()
    output = a.out or ROOT / "revision" / (
        "service_file" if a.file_replay else "service_groups"
    )
    benchmark(a.data, output, a.repeats, a.file_replay, a.methods)
