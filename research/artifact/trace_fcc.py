

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import random
import time
import zipfile
import struct
import zlib

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
BASE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "scope5-sources" / "fcc"
OUT = HERE.parents[1] / "revision" / "fcc"
NOTEBOOK = "https://raw.githubusercontent.com/BuzzFeedNews/2019-10-fcc-comments/8f10873fa3e6d91bbb2396485d159a27c8e8e775/notebooks/analyze-fcc-comments.ipynb"
ZIP = "https://archive.org/download/fcc-comments-and-bulk-uploads/bulk-uploads-17-108-with-uuids.csv.zip"
SHA1 = "31bff75b0c2c837242e217253c7d42496aaf145d"
CLOCK = time.perf_counter_ns


def extract_csv(archive, output):



    with zipfile.ZipFile(archive) as z:
        member = z.getinfo("bulk-uploads-17-108-with-uuids.csv")
    with archive.open("rb") as src, output.open("wb") as dest:
        src.seek(member.header_offset)
        head = struct.unpack("<I5H3I2H", src.read(30))
        if head[0] != 0x04034B50 or head[3] != zipfile.ZIP_DEFLATED:
            raise ValueError("unexpected local ZIP header")
        src.seek(head[-2] + head[-1], 1)
        left = member.compress_size
        decoder = zlib.decompressobj(-15)
        crc = size = 0
        while left:
            chunk = src.read(min(1 << 20, left))
            if not chunk:
                raise ValueError("truncated ZIP data")
            left -= len(chunk)
            data = decoder.decompress(chunk)
            crc = zlib.crc32(data, crc)
            size += len(data)
            dest.write(data)
        if (
            not decoder.eof
            or decoder.unused_data
            or crc != member.CRC
            or size % (1 << 32) != member.file_size
        ):
            raise ValueError("invalid original DEFLATE data or uncompressed CRC")
        return size


def prepare(base):
    base.mkdir(parents=True, exist_ok=True)
    archive = base / "bulk.zip"
    if not archive.exists():
        with requests.get(ZIP, stream=True, timeout=(20, 240)) as response:
            response.raise_for_status()
            with archive.with_suffix(".partial").open("wb") as dest:
                for block in response.iter_content(1 << 20):
                    dest.write(block)
        archive.with_suffix(".partial").replace(archive)
    with archive.open("rb") as src:
        digest = hashlib.file_digest(src, "sha1").hexdigest()
    if digest != SHA1:
        raise ValueError("source archive digest mismatch")
    res = requests.get(NOTEBOOK, timeout=90)
    res.raise_for_status()
    cell = res.json()["cells"][11]
    if cell["execution_count"] != 6:
        raise ValueError("unexpected notebook execution")
    stored = "".join(cell["outputs"][0]["data"]["text/html"])
    original = {}
    for row in BeautifulSoup(stored, "html.parser").select("tbody tr"):
        name, count, _, ratio = [
            v.get_text(strip=True) for v in row.find_all(["th", "td"])
        ]
        original[name] = (int(count), Decimal(ratio))



    ids = {}
    counts = Counter()
    present = Counter()
    runs = 0
    last = -2
    dropped = 0
    parquet = base / "input.parquet"
    schema = pa.schema([("uploader", pa.uint32()), ("email", pa.bool_())])
    csv = base / "input.csv"
    size = extract_csv(archive, csv)
    print("Verified raw CSV bytes", size, flush=True)
    with pq.ParquetWriter(parquet, schema) as sink:
        with csv.open("rb") as raw:
            for frame in pd.read_csv(
                raw, dtype=str, usecols=["uploader", "email_address"], chunksize=250000
            ):
                codes, keys = pd.factorize(frame["uploader"])
                local = [ids.setdefault(name, len(ids)) for name in keys]
                group = np.array(local + [-1], dtype=np.int32)[codes]
                missing = frame["email_address"].isna().to_numpy()

                keep = group >= 0
                dropped += int((~keep).sum())
                ordered = group[keep]
                if len(ordered):
                    runs += int(ordered[0] != last) + int(
                        (ordered[1:] != ordered[:-1]).sum()
                    )
                    last = int(ordered[-1])
                all_count = np.bincount(group[keep], minlength=len(ids))
                good_count = np.bincount(group[keep & ~missing], minlength=len(ids))
                counts.update({i: int(v) for i, v in enumerate(all_count) if v})
                present.update({i: int(v) for i, v in enumerate(good_count) if v})
                sink.write_table(
                    pa.table(
                        {
                            "uploader": pa.array(
                                np.maximum(group, 0).astype(np.uint32), mask=~keep
                            ),
                            "email": pa.array(
                                np.ones(len(group), dtype=np.bool_), mask=missing
                            ),
                        }
                    )
                )
    visible = {
        name: (counts[i], Decimal(str(round(present[i] / counts[i], 4))))
        for name, i in ids.items()
        if counts[i] >= 10000
    }
    if visible != original:
        raise ValueError(
            "group set, group count or rounded ratio differs from published output"
        )
    expected = [[g, counts[g], present[g]] for g in counts if counts[g] >= 10000]
    expected.sort(key=lambda row: -row[1])
    info = dict(
        notebook=NOTEBOOK,
        notebook_sha256=hashlib.sha256(res.content).hexdigest(),
        execution=6,
        archive=ZIP,
        archive_sha1=digest,
        uncompressed_bytes=size,
        rows=sum(counts.values()) + dropped,
        excluded_null_uploader=dropped,
        groups=len(counts),
        source_group_runs=runs,
        published_groups=len(original),
        expected=expected,
        masks="email: nullable true; uploader: anonymized ordinal key",
    )
    (base / "evidence.json").write_text(json.dumps(info, indent=2), encoding="utf8")
    print(
        {
            k: info[k]
            for k in (
                "rows",
                "groups",
                "source_group_runs",
                "published_groups",
                "excluded_null_uploader",
            )
        },
        flush=True,
    )


def install_ranges(con, rows):


    con.execute(f"""
        CREATE TEMP TABLE spans AS
        WITH marked AS (
            SELECT rid AS l, uploader, lag(uploader) OVER () AS previous
            FROM source
        ), boundaries AS (
            SELECT l,uploader FROM marked
            WHERE l=0 OR uploader IS DISTINCT FROM previous
        ), endpoints AS (
            SELECT uploader,l,lead(l,1,{rows}::UINTEGER) OVER (ORDER BY l) AS r
            FROM boundaries
        )
        SELECT uploader,l,r FROM endpoints WHERE uploader IS NOT NULL
    """)


def source_ranges(file):

    col = pq.read_table(file, columns=["uploader"]).column(0).combine_chunks()
    keys = col.cast(pa.int32()).fill_null(-1).to_numpy()
    starts = np.r_[0, np.flatnonzero(keys[1:] != keys[:-1]) + 1]
    ends = np.r_[starts[1:], len(keys)]
    return [
        (int(keys[i]), int(i), int(j)) for i, j in zip(starts, ends) if keys[i] >= 0
    ]


def benchmark(base, out):
    from engine.replay import connect

    receipt = json.loads((base / "evidence.json").read_text(encoding="utf8"))
    expected = [
        (*row, float(np.round(row[2] / row[1], 4))) for row in receipt["expected"]
    ]
    expected_ranges = source_ranges(base / "input.parquet")
    con = connect()
    con.execute("SET preserve_insertion_order=true")
    records = []
    try:
        start = CLOCK()
        con.execute(
            "CREATE TEMP TABLE source AS SELECT "
            "(row_number() OVER ()-1)::UINTEGER AS rid, uploader, email FROM read_parquet(?)",
            [str(base / "input.parquet")],
        )
        load = CLOCK() - start
        methods = ["tree", "bitmap", "sql"]
        rng = random.Random(99117)
        for rep in range(5):
            order = methods[:]
            rng.shuffle(order)
            for slot, method in enumerate(order):
                spans = layout = build = 0
                handle = None
                if method == "sql":
                    grouped = """SELECT uploader, count(*) AS n, count(email) AS k
                        FROM source WHERE uploader IS NOT NULL
                        GROUP BY uploader HAVING count(*) >= 10000"""
                else:
                    start = CLOCK()
                    install_ranges(con, receipt["rows"])
                    layout = CLOCK() - start
                    start = CLOCK()
                    handle = int(
                        con.execute(
                            f"SELECT scope_attach('{method}', count(*)::UINTEGER, "
                            "[0]::UBIGINT[], [scope_validity(rid,email)]) FROM source"
                        ).fetchone()[0]
                    )
                    build = CLOCK() - start
                    grouped = f"""SELECT uploader, sum(r-l)::BIGINT AS n,
                        sum(scope_count({handle}::UBIGINT,l,r,[0]::UBIGINT[],[1]::UBIGINT[])[1])::BIGINT AS k
                        FROM spans GROUP BY uploader HAVING sum(r-l) >= 10000"""
                start = CLOCK()
                actual = con.execute(
                    f"SELECT uploader,n,k,round_even(k::DOUBLE/n,4) "
                    f"FROM ({grouped}) grouped ORDER BY n DESC, uploader"
                ).fetchall()
                query = CLOCK() - start
                if actual != expected:
                    raise AssertionError((method, actual, expected))
                if handle is not None:
                    observed_ranges = con.execute(
                        "SELECT uploader,l,r FROM spans ORDER BY l"
                    ).fetchall()
                    if observed_ranges != expected_ranges:
                        raise AssertionError("range bounds differ from source order")
                    spans = len(observed_ranges)
                    con.execute(f"SELECT scope_drop({handle}::UBIGINT)")
                    con.execute("DROP TABLE spans")
                records.append(
                    dict(
                        rep=rep,
                        slot=slot,
                        method=method,
                        load_ns=load,
                        layout_ns=layout,
                        build_ns=build,
                        request_ns=query,
                        total_ns=layout + build + query,
                        rows=receipt["rows"],
                        groups=receipt["groups"],
                        spans=spans,
                        outputs=len(actual),
                        results=json.dumps(actual, separators=(",", ":")),
                    )
                )
                print(rep, method, (layout + build + query) / 1e6, flush=True)
    finally:
        con.close()
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_csv(out / "grouped.tsv", sep="\t", index=False)
    (out / "evidence.json").write_text(json.dumps(receipt, indent=2), encoding="utf8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "benchmark"])
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.base)
    else:
        benchmark(args.base, args.out)
