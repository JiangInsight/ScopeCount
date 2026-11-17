

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import zipfile

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import sqlglot
from sqlglot import exp

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import trace_fetch as source

ROOT = HERE.parents[2]
CACHE = ROOT / "traces" / "sqlshare"
OUT = ROOT / "traces" / "service_groups"


def screen(cache, archive):
    source.download_log(cache / "query-log.raw")
    members = [n for n in archive.namelist() if "/data/" in n and not n.endswith("/")]

    def resource(name):
        return archive.read("sqlshare_data_release1/" + name).decode(
            "utf8", errors="replace"
        )

    views = resource("view_script.txt")
    statements = {
        source.normalize_sql(text)
        for text in re.split(r"_{40,}", resource("queries.txt"))
    }
    stats = Counter()
    matches = []
    with (cache / "query-log.raw").open("rb") as log:
        for row in log:
            f = row.rstrip(b"\r\n").split(b"|", 8)
            if len(f) != 9 or f[4] != b"success" or not f[0].isdigit():
                continue
            stats["successful"] += 1
            sql = f[5].decode("utf8", "replace")
            if not re.search(r"group\s+by", sql, re.I) or not re.search(
                r"count\s*\(", sql, re.I
            ):
                continue
            stats["group_count_text"] += 1
            try:
                s = sqlglot.parse_one(sql, read="tsql")
            except sqlglot.errors.SqlglotError:
                continue
            if not isinstance(s, exp.Select) or not s.args.get("group"):
                continue
            tables = list(s.find_all(exp.Table))
            keys = s.args["group"].expressions
            if (
                len(tables) != 1
                or len(keys) != 1
                or not isinstance(keys[0], exp.Column)
            ):
                continue
            counts = [
                v.this.name.lower()
                for v in s.find_all(exp.Count)
                if isinstance(v.this, exp.Column)
            ]
            if not counts:
                continue
            table = tables[0]
            member = source.resolve(table.name.lower(), members, views)
            candidate = dict(sql=sql, table=table.name.lower(), owner=table.db.lower())
            if not member or not source.in_archive(candidate, member, statements):
                continue
            stats["grouped_member_and_statement_matched"] += 1


            if s.args.get("where") or len(set(counts)) != 1:
                continue
            having = s.args.get("having")
            if having and not (
                isinstance(having.this, exp.EQ)
                and isinstance(having.this.this, exp.Count)
                and isinstance(having.this.expression, exp.Literal)
                and having.this.expression.name == "1"
            ):
                continue
            outputs = [x.unalias() for x in s.expressions]
            extra = any(not isinstance(x, (exp.Column, exp.Count)) for x in outputs)
            key_output = any(
                isinstance(x, exp.Column) and x.name.lower() == keys[0].name.lower()
                for x in outputs
            )
            matches.append(
                dict(
                    id=int(f[0]),
                    time=datetime.strptime(
                        f[2].decode(), "%m/%d/%Y %I:%M:%S %p"
                    ).isoformat(),
                    member=member,
                    group=keys[0].name.lower(),
                    field=counts[0],
                    count_one=bool(having),
                    include_key=key_output,
                    ordered=s.args.get("order") is not None,
                    count_projection=extra,
                )
            )
    return matches, dict(stats)


def load_columns(raw, key, field):
    text = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "latin1")
    reader = csv.reader(io.StringIO(text, newline=""))
    names = [x.casefold() for x in next(reader)]
    if len(set(names)) != len(names) or key not in names or field not in names:
        raise ValueError("ambiguous/missing column")
    gi, vi = names.index(key), names.index(field)
    keys, valid = [], []
    for row in reader:
        if not row:
            continue
        if len(row) != len(names):
            raise ValueError("ragged CSV")
        keys.append(row[gi])
        valid.append(row[vi] != "")


    vocab = set(keys) - {""}
    if len({k.casefold().rstrip() for k in vocab}) != len(vocab):
        raise ValueError("release grouping depends on collation")
    try:
        numeric = {k: float(k) for k in vocab}
    except ValueError:
        names_by_order = sorted(vocab)
    else:
        if len(set(numeric.values())) != len(vocab):
            raise ValueError("release grouping depends on numeric parsing")
        names_by_order = sorted(vocab, key=numeric.get)
    if "" in keys:
        names_by_order.insert(0, "")
    code = {k: i for i, k in enumerate(names_by_order)}
    g = np.fromiter((code[k] for k in keys), dtype=np.uint32, count=len(keys))
    v = np.asarray(valid, dtype=np.bool_)
    tbl = pa.table({"g": g, "v0": pa.array(np.ones(len(g), dtype=bool), mask=~v)})


    counts = Counter(keys)
    counted = Counter(k for k, ok in zip(keys, valid) if ok)
    expected = [
        (i, counts[k], counted[k])
        for k, i in sorted(code.items(), key=lambda kv: kv[1])
    ]
    with duckdb.connect() as db:
        db.register("encoded", tbl)
        actual = db.sql(
            "SELECT g,count(*),count(v0) FROM encoded GROUP BY g ORDER BY g"
        ).fetchall()
        assert actual == expected
    return tbl, {
        "rows": len(g),
        "groups": len(expected),
        "runs": int(1 + np.count_nonzero(g[1:] != g[:-1])),
        "null_counts": int((~v).sum()),
        "null_group_rows": keys.count(""),
        "answers_sha256": hashlib.sha256(
            np.asarray(expected, dtype="<u8").tobytes()
        ).hexdigest(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=OUT)
    args = ap.parse_args()
    dest = args.root
    dest.mkdir(exist_ok=True, parents=True)
    CACHE.mkdir(exist_ok=True, parents=True)
    rawcache = CACHE / "group-download"
    rawcache.mkdir(exist_ok=True)
    with zipfile.ZipFile(source.HttpZip(source.ARCHIVE)) as archive:
        matches, stats = screen(CACHE, archive)
        grouped = defaultdict(list)
        for q in matches:
            grouped[(q["member"], q["group"], q["field"])].append(q)
        sources, exclusions = [], []
        for (member, key, field), qs in sorted(grouped.items()):
            rid = hashlib.sha256(member.encode()).hexdigest()[:12]
            path = rawcache / (rid + ".csv")
            if not path.exists():
                path.write_bytes(archive.read(member))
            raw = path.read_bytes()
            if (
                len(raw) != archive.getinfo(member).file_size
                or zipfile.crc32(raw) != archive.getinfo(member).CRC
            ):
                raise ValueError(f"checksum mismatch for {member}")
            try:
                tbl, summary = load_columns(raw, key, field)
            except ValueError as e:
                exclusions.append(
                    dict(member=member, reason=str(e), ids=[q["id"] for q in qs])
                )
                continue
            dataset = "q" + str(min(q["id"] for q in qs))
            pq.write_table(tbl, dest / (dataset + ".parquet"), compression="zstd")
            sources.append(
                dict(
                    dataset=dataset,
                    member=member,
                    key=key,
                    field=field,
                    file_sha256=hashlib.sha256(
                        (dest / (dataset + ".parquet")).read_bytes()
                    ).hexdigest(),
                    source_sha256=hashlib.sha256(raw).hexdigest(),
                    **summary,
                    requests=sorted(qs, key=lambda q: (q["time"], q["id"])),
                )
            )
        manifest = dict(
            log=source.LOG,
            log_sha256=source.LOG_SHA256,
            archive=source.ARCHIVE,
            screen=stats,
            sources=sources,
            exclusions=exclusions,
        )
        (dest / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf8"
        )
        print(stats)
        print(
            "included",
            len(sources),
            sum(len(s["requests"]) for s in sources),
            sum(x["rows"] for x in sources),
        )
        for s in sources:
            print(s["dataset"], s["rows"], s["groups"], s["runs"], len(s["requests"]))
        print("exclusions", exclusions)


if __name__ == "__main__":
    main()
