

import argparse
import csv
import hashlib
import io
import json
import random
import re
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from engine.replay import connect
from trace_fetch import (
    ARCHIVE,
    BASE,
    LOG,
    HttpZip,
    download_log,
    in_archive,
    normalize_sql,
)

MEMBER = "sqlshare_data_release1/data/1267/table_h2_w_1.csv"
TABLE = "table_h2_w_1.csv"
IDS = ("6930", "6931")
DEFAULT = BASE / "sqlshare_scoped"
OUT = BASE.parent / "revision" / "sqlshare_scoped"
CLOCK = time.perf_counter_ns


def prepare(base):
    base.mkdir(exist_ok=True, parents=True)
    cache = BASE / "sqlshare"
    cache.mkdir(exist_ok=True, parents=True)
    log = cache / "query-log.raw"
    download_log(log)
    with zipfile.ZipFile(HttpZip(ARCHIVE)) as z:
        raw = z.read(MEMBER)
        statements = z.read("sqlshare_data_release1/queries.txt").decode(
            "utf8", "replace"
        )
    public_queries = {normalize_sql(s) for s in re.split(r"_{40,}", statements)}
    evidence = {}
    with log.open("rb") as src:
        for line in src:
            data = line.rstrip(b"\r\n").split(b"|", 8)
            if data[0].decode(errors="replace") not in IDS:
                continue
            qid = data[0].decode()
            sql = data[5].decode()
            owner = re.search(r"FROM\s+\[([^\]]+)\]", sql, re.I).group(1).lower()
            if data[4] != b"success" or not in_archive(
                dict(sql=sql, owner=owner, table=TABLE), MEMBER, public_queries
            ):
                raise ValueError("query absent from the archive")
            stem = "SELECT count(charge) FROM [1267].[table_h2_w_1.csv] where gaps = 0"
            if qid == "6930":
                stem += " AND pdb_id IS NOT NULL"
            if normalize_sql(stem) != normalize_sql(
                sql.replace(f"[{owner}].", "[1267].")
            ):
                raise ValueError("unexpected SQL shape")
            evidence[qid] = dict(start=data[2].decode(), end=data[3].decode(), sql=stem)
    if set(evidence) != set(IDS):
        raise ValueError("incomplete execution pair")
    reader = csv.DictReader(io.StringIO(raw.decode("latin1"), newline=""))
    records = list(reader)
    if any(None in r or None in r.values() for r in records):
        raise ValueError("ragged source")
    gaps = np.array([int(r["gaps"]) for r in records], dtype=np.int32)
    true = np.ones(len(records), dtype=np.bool_)
    src = {"gaps": gaps}
    for column in ("charge", "pdb_id"):
        src[column] = pa.array(
            true, mask=np.array([not r[column] for r in records], dtype=np.bool_)
        )
    table = pa.table(src)
    pq.write_table(table, base / "input.parquet")
    selected = gaps == 0
    runs = np.count_nonzero(selected & ~np.r_[False, selected[:-1]])
    for id_, cols in zip(IDS, [("charge", "pdb_id"), ("charge",)]):
        expected = sum(
            all(r[c] != "" for c in cols) for r in records if int(r["gaps"]) == 0
        )
        evidence[id_]["archive_count"] = expected
    receipt = dict(
        member=MEMBER,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        archive=ARCHIVE,
        log=LOG,
        rows=len(table),
        selected=int(selected.sum()),
        runs=int(runs),
        requests=evidence,
    )
    (base / "evidence.json").write_text(json.dumps(receipt, indent=2), encoding="utf8")
    print(receipt)


def ranges(con, rows):


    con.execute(f"""
        CREATE TEMP TABLE spans AS
        WITH marked AS (
            SELECT rid AS l, gaps=0 AS eligible, lag(gaps=0) OVER () AS prior
            FROM source
        ), boundaries AS (
            SELECT l,eligible FROM marked WHERE l=0 OR eligible IS DISTINCT FROM prior
        ), endpoints AS (
            SELECT eligible,l,lead(l,1,{rows}::UINTEGER) OVER (ORDER BY l) AS r FROM boundaries
        )
        SELECT l,r FROM endpoints WHERE eligible
    """)


def benchmark(base, out):
    receipt = json.loads((base / "evidence.json").read_text(encoding="utf8"))
    records = []
    keys = (
        pq.read_table(base / "input.parquet", columns=["gaps"])
        .column(0)
        .combine_chunks()
        .to_numpy()
    )
    selected = keys == 0
    starts = np.flatnonzero(selected & ~np.r_[False, selected[:-1]])
    ends = np.flatnonzero(selected & ~np.r_[selected[1:], False]) + 1
    expected_ranges = list(zip(starts.tolist(), ends.tolist()))
    con = connect()
    con.execute("SET preserve_insertion_order=true")
    try:
        start = CLOCK()
        con.execute(
            "CREATE TEMP TABLE source AS SELECT (row_number() OVER ()-1)::UINTEGER AS rid,* FROM read_parquet(?)",
            [str(base / "input.parquet")],
        )
        load = CLOCK() - start
        rng = random.Random(99117)
        for rep in range(5):
            order = ["tree", "bitmap", "sql", "sql_reused"]
            rng.shuffle(order)
            for slot, method in enumerate(order):
                handle = None
                layout = build = 0
                if method == "sql_reused":
                    start = CLOCK()
                    con.execute(
                        "CREATE TEMP TABLE selected AS SELECT charge,pdb_id FROM source WHERE gaps=0"
                    )
                    layout = CLOCK() - start
                elif method in ("tree", "bitmap"):
                    start = CLOCK()
                    ranges(con, receipt["rows"])
                    layout = CLOCK() - start
                    start = CLOCK()
                    handle = int(
                        con.execute(
                            f"SELECT scope_attach('{method}',count(*)::UINTEGER,[0,1]::UBIGINT[],"
                            "[scope_validity(rid,charge),scope_validity(rid,pdb_id)]) FROM source"
                        ).fetchone()[0]
                    )
                    build = CLOCK() - start
                cumulative = layout + build
                for ordinal, qid in enumerate(IDS, 1):
                    if handle is None:
                        where = [] if method == "sql_reused" else ["gaps=0"]
                        if qid == "6930":
                            where.append("pdb_id IS NOT NULL")
                        table = "selected" if method == "sql_reused" else "source"
                        cmd = (
                            "SELECT count(charge) FROM "
                            + table
                            + (" WHERE " + " AND ".join(where) if where else "")
                        )
                    else:
                        mask = 3 if qid == "6930" else 1
                        cmd = f"SELECT sum(scope_count({handle}::UBIGINT,l,r,[0]::UBIGINT[],[{mask}]::UBIGINT[])[1]) FROM spans"
                    start = CLOCK()
                    actual = int(con.execute(cmd).fetchone()[0])
                    dt = CLOCK() - start
                    if actual != receipt["requests"][qid]["archive_count"]:
                        raise ValueError((qid, actual))
                    cumulative += dt
                    records.append(
                        dict(
                            rep=rep,
                            slot=slot,
                            method=method,
                            request_id=qid,
                            ordinal=ordinal,
                            load_ns=load,
                            layout_ns=layout,
                            build_ns=build,
                            request_ns=dt,
                            paid_ns=cumulative,
                            result=actual,
                        )
                    )
                if handle is not None:
                    observed_ranges = con.execute(
                        "SELECT l,r FROM spans ORDER BY l"
                    ).fetchall()
                    if observed_ranges != expected_ranges:
                        raise ValueError(
                            "scope endpoints differ from the original row-order predicate"
                        )
                    con.execute(f"SELECT scope_drop({handle}::UBIGINT)")
                    con.execute("DROP TABLE spans")
                if method == "sql_reused":
                    con.execute("DROP TABLE selected")
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(records).to_csv(out / "scoped.tsv", sep="\t", index=False)
        (out / "evidence.json").write_text(
            json.dumps(receipt, indent=2), encoding="utf8"
        )
    finally:
        con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["prepare", "benchmark"])
    p.add_argument("--base", type=Path, default=DEFAULT)
    p.add_argument("--out", type=Path, default=OUT)
    a = p.parse_args()
    if a.stage == "prepare":
        prepare(a.base)
    else:
        benchmark(a.base, a.out)
