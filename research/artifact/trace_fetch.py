





import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import zipfile
import requests
import numpy as np
import sqlglot
from sqlglot import exp

BASE = Path(__file__).resolve().parents[2] / "traces"
ARCHIVE = "https://shrquerylogs.s3.amazonaws.com/public/sqlshare_data_release1.zip"
LOG = "https://shrquerylogs.s3.amazonaws.com/public/QueriesWithPlan.csv"
LOG_SHA256 = "b8e11f6763ca2bba8fbcdc0d102513bc5391571beb72a67ce51ea86dbaa47c6c"
logging.getLogger("sqlglot").setLevel(logging.ERROR)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_log(path):
    with path.open("rb") as data:
        if hashlib.file_digest(data, "sha256").hexdigest() != LOG_SHA256:
            raise ValueError(
                "SQLShare log differs from the released snapshot used here"
            )


def download_log(dest):
    size = int(requests.head(LOG, timeout=30).headers["Content-Length"])
    if dest.exists() and dest.stat().st_size == size:
        verify_log(dest)
        return
    tmp = dest.with_suffix(".part")
    with tmp.open("wb") as stream:
        stream.truncate(size)

    def block(start):
        stop = min(size, start + (16 << 20)) - 1
        for attempt in range(4):
            try:
                res = requests.get(
                    LOG, headers={"Range": f"bytes={start}-{stop}"}, timeout=180
                )
                res.raise_for_status()
                if len(res.content) != stop - start + 1:
                    raise ValueError("partial log transfer")
                with tmp.open("r+b") as stream:
                    stream.seek(start)
                    stream.write(res.content)
                return
            except (ValueError, requests.RequestException):
                if attempt == 3:
                    raise

    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        list(pool.map(block, range(0, size, 16 << 20)))
    verify_log(tmp)
    tmp.replace(dest)


class HttpZip(io.RawIOBase):
    def __init__(self, url):
        self.client = requests.Session()
        self.url = url
        self.size = int(self.client.head(url, timeout=30).headers["Content-Length"])
        self.pos = 0

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: 0, 1: self.pos, 2: self.size}[whence] + offset
        return self.pos

    def read(self, size=-1):
        n = min(size if size >= 0 else self.size - self.pos, self.size - self.pos)
        if n <= 0:
            return b""
        r = self.client.get(
            self.url, headers={"Range": f"bytes={self.pos}-{self.pos+n-1}"}, timeout=180
        )
        r.raise_for_status()
        if len(r.content) != n:
            raise ValueError("range mismatch")
        self.pos += n
        return r.content


def require(v):
    if not v:
        raise ValueError("outside supported SQL grammar")


def conjunct(v):
    if v is None:
        return [], []
    if isinstance(v, exp.Paren):
        return conjunct(v.this)
    if isinstance(v, exp.And):
        a, b = conjunct(v.this)
        c, d = conjunct(v.expression)
        return a + c, b + d
    neg = isinstance(v, exp.Not)
    inner = v.this if neg else v
    require(
        isinstance(inner, exp.Is)
        and isinstance(inner.this, exp.Column)
        and isinstance(inner.expression, exp.Null)
    )
    c = inner.this.name.lower()
    return ([], [c]) if neg else ([c], [])


def query_shape(txt):
    stmts = sqlglot.parse(txt, read="tsql")
    require(len(stmts) == 1)
    s = stmts[0]
    require(isinstance(s, exp.Select))
    require({k for k, v in s.args.items() if v} <= {"expressions", "from_", "where"})
    tbl = s.args["from_"].this
    require(isinstance(tbl, exp.Table))
    where = s.args.get("where")
    p, n = conjunct(where.this if where is not None else None)
    rules = []
    for out in s.expressions:
        v = out.unalias()
        require(isinstance(v, exp.Count))
        col = v.this
        require(
            isinstance(col, (exp.Column, exp.Star))
            or isinstance(col, exp.Literal)
            and col.name == "1"
        )
        require(bool(p or n) or isinstance(col, exp.Column))
        rules.append(
            (
                sorted(set(p)),
                sorted(
                    set(n + ([col.name.lower()] if isinstance(col, exp.Column) else []))
                ),
            )
        )
    return tbl.name.lower(), rules, where is not None, tbl.db.lower()


def readlog(path):
    counts = {
        "physical_log_rows": 0,
        "success": 0,
        "null_count_grammar": 0,
        "explicit_null_filter": 0,
    }
    candidates = []
    with path.open("rb") as f:
        next(f)
        for line in f:
            fields = line.rstrip(b"\r\n").split(b"|", 8)
            counts["physical_log_rows"] += 1
            if len(fields) != 9 or fields[4] != b"success" or not fields[0].isdigit():
                continue
            counts["success"] += 1
            if not re.search(rb"\bcount\s*\(", fields[5], re.I):
                continue
            try:
                sql = fields[5].decode("utf8", "replace")
                table, rules, explicit, owner = query_shape(sql)
            except (ValueError, KeyError, AttributeError, sqlglot.errors.SqlglotError):
                continue
            counts["null_count_grammar"] += 1
            counts["explicit_null_filter"] += explicit
            timestamp = lambda t: dt.datetime.strptime(
                t.decode(), "%m/%d/%Y %I:%M:%S %p"
            ).isoformat()
            candidates.append(
                {
                    "id": int(fields[0]),
                    "start": timestamp(fields[2]),
                    "end": timestamp(fields[3]),
                    "table": table,
                    "rules": rules,
                    "explicit": explicit,
                    "sql": sql,
                    "owner": owner,
                }
            )
    return counts, candidates


def write_case(dir, cols, masks, requests_for_case, info):
    dir.mkdir(exist_ok=True, parents=True)
    masks = np.asarray(masks, dtype="<u8")
    masks.tofile(dir / "input.rows")
    with (dir / "trace.tsv").open("w", encoding="utf8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["request_id", "l", "r", "must_null", "must_present"])
        for q in requests_for_case:
            result = []
            for p, n in q["rules"]:
                x = sum(1 << cols.index(c) for c in p)
                y = sum(1 << cols.index(c) for c in n)
                w.writerow([q["id"], 0, len(masks), x, y])
                result.append(
                    int(np.count_nonzero(((masks & x) == x) & ((masks & y) == 0)))
                )
            q["expected"] = result
    info.update(
        rows=len(masks),
        columns=cols,
        distinct_signatures=len(np.unique(masks)),
        requests=requests_for_case,
        mask_sha256=sha(masks.tobytes()),
    )
    (dir / "metadata.json").write_text(
        json.dumps(info, indent=2, sort_keys=True), encoding="utf8"
    )


def resolve(name, members, views):


    matches = []
    for f in members:
        basename = f.rsplit("/", 1)[-1].lower()
        if not basename:
            continue
        if basename == name or basename == "materialized_" + name:
            matches.append(f)
            continue
        if basename != "table_" + name:
            continue
        owner = f.split("/")[-2]
        pattern = (
            r"^create view \["
            + re.escape(owner)
            + r"\]\.\["
            + re.escape(name)
            + r"\] \([^\n]*?\) as select \* from \["
            + re.escape(owner)
            + r"\]\.\["
            + re.escape(basename)
            + r"\]\s*;?\s*$"
        )
        if re.search(pattern, views, re.I | re.M):
            matches.append(f)
    return matches[0] if len(matches) == 1 else None


def normalize_sql(sql):
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).lower()


def in_archive(log_query, member, archived_sql):


    sql = log_query["sql"].lower()
    owner = log_query["owner"]
    if owner:
        archived_owner = member.split("/")[-2]
        pattern = (
            re.escape("[" + owner + "]")
            + r"\s*\.\s*"
            + re.escape("[" + log_query["table"] + "]")
        )
        sql, matched = re.subn(
            pattern, lambda _: f"[{archived_owner}].[{log_query['table']}]", sql
        )
        if matched != 1:
            return False
    return normalize_sql(sql) in archived_sql


def shape_csv(data, needed):
    text = (
        data.decode("utf-8-sig", errors="strict")
        if data.startswith(b"\xef\xbb\xbf")
        else data.decode("latin1")
    )
    reader = csv.reader(io.StringIO(text, newline=""))
    cols = [c.lower() for c in next(reader)]
    require(len(set(cols)) == len(cols))
    require(needed <= set(cols))
    require(len(needed) <= 63)
    retained = cols[:63] if needed <= set(cols[:63]) else list(sorted(needed))
    ids = [cols.index(c) for c in retained]
    out = []
    for row in reader:
        if not row:
            continue
        if len(row) != len(cols):
            raise ValueError("ragged CSV")
        out.append(sum(1 << j for j, i in enumerate(ids) if row[i] == ""))
    return retained, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=BASE)
    args = ap.parse_args()
    cache = args.root / "sqlshare"
    cache.mkdir(parents=True, exist_ok=True)
    raw = cache / "query-log.raw"
    download_log(raw)
    counts, candidates = readlog(raw)
    z = zipfile.ZipFile(HttpZip(ARCHIVE))
    files = [n for n in z.namelist() if "/data/" in n and not n.endswith("/")]
    viewname = "sqlshare_data_release1/view_script.txt"
    views = z.read(viewname).decode("utf8", "replace")
    root = args.root / "matched"
    root.mkdir(parents=True, exist_ok=True)
    mapping = {
        name: resolve(name, files, views) for name in {q["table"] for q in candidates}
    }
    texts = z.read("sqlshare_data_release1/queries.txt").decode("utf8", "replace")
    archived_sql = {normalize_sql(stmt) for stmt in re.split(r"_{40,}", texts)}
    groups = {}
    rejected = []
    unverified = []
    for q in candidates:
        member = mapping[q["table"]]
        if member:
            groups.setdefault(member, []).append(q)
    for member, qs in sorted(groups.items()):
        try:
            data = z.read(member)
            need = {c for q in qs for p, n in q["rules"] for c in p + n}
            cols, masks = shape_csv(data, need)
            require(bool(masks))
            eligible = []
            for q in qs:
                if in_archive(q, member, archived_sql):
                    eligible.append(
                        {k: v for k, v in q.items() if k not in {"owner", "sql"}}
                    )
                else:
                    unverified.append({"id": q["id"], "member": member})
            qs = eligible
            if not qs:
                continue
            slug = "sql_" + re.sub(
                r"[^a-z0-9]+", "_", member.split("/")[-1].lower()
            ).strip("_")
            qs = sorted(qs, key=lambda x: (x["start"], x["id"]))
            write_case(
                root / slug,
                cols,
                masks,
                qs,
                dict(
                    source="SQLShare",
                    member=member,
                    source_sha256=sha(data),
                    archive_url=ARCHIVE,
                    log_url=LOG,
                ),
            )
        except (ValueError, IndexError, StopIteration) as exc:
            rejected.append([member, str(exc)])
    counts.update(
        unique_data_members=len(files),
        matched_names=len(groups),
        owner_or_sql_unconfirmed=unverified,
        rejected=rejected,
        returned_historical_counts_available=False,
    )
    (cache / "screen.json").write_text(json.dumps(counts, indent=2), encoding="utf8")
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
