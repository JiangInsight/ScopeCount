

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import requests

HERE = Path(__file__).resolve().parent
DEFAULT = HERE.parents[2] / "datasets/stops"
EDITION = "9abc320a6b1bf7fd27ea3c7964dd9ed8a69a81f6"
BASE = "https://stacks.stanford.edu/file/druid:"
HOURLY = {
    "oh_statewide",
    "il_chicago",
    "md_statewide",
    "nj_statewide",
    "wa_statewide",
    "wi_statewide",
}

WEEKLY = (
    "ia_statewide",
    "ky_louisville",
    "tn_nashville",
    "mn_saint_paul",
    "sc_statewide",
    "ks_wichita",
    "ca_los_angeles",
    "ca_bakersfield",
    "fl_tampa",
    "az_statewide",
    "co_aurora",
    "ca_statewide",
    "il_chicago",
    "co_statewide",
    "md_statewide",
    "nj_statewide",
    "oh_statewide",
    "wa_statewide",
    "wi_statewide",
)
NEW = {"co_aurora", "il_chicago", "ks_wichita", "ky_louisville", "ca_statewide"}
MISSING = np.iinfo("int32").min


def source(name):
    entry, date = (
        ("wb225bk3255", "2023_01_26") if name in NEW else ("yg821jf8611", "2020_04_01")
    )
    fname = f"{entry}_{name}_{date}.rds"
    return f"{BASE}{entry}/{fname}", fname


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def oracle_sha(path):
    return hashlib.sha256(path.read_text().encode()).hexdigest()


def prepare(name, cache, rscript):
    assert name in WEEKLY
    url, fname = source(name)
    raw = cache / fname
    out = cache / "panels" / name
    out.mkdir(parents=True, exist_ok=True)
    if not raw.exists():
        tmp = raw.with_suffix(".new")
        with requests.get(url, stream=True, timeout=(20, 300)) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for block in r.iter_content(1 << 20):
                    f.write(block)
        tmp.replace(raw)
    manifest = HERE / "results" / "source_manifest.json"
    expected = (
        {c["dataset"]: c for c in json.loads(manifest.read_text())}
        if manifest.exists()
        else {}
    )
    raw_digest = sha(raw)
    if name in expected and raw_digest != expected[name]["source_sha256"]:
        raise ValueError(f"Archived source checksum changed: {name}")
    dims = ["week"] + (["hour"] if name in HOURLY else [])
    subprocess.run(
        [rscript, "--vanilla", HERE / "extract.R", raw, out, ",".join(dims)], check=True
    )
    fields = (out / "fields.txt").read_text().splitlines()
    masks = np.memmap(out / "masks.i32", dtype="<i4", mode="r")
    raw_rows, n = map(int, (out / "sizes.txt").read_text().split())
    assert n == len(masks)
    data = {}
    for key in ("week", "hour"):
        keys = np.memmap(out / (key + ".i32"), dtype="<i4", mode="r")
        assert len(keys) == n and np.all((keys == MISSING) | (keys >= 0))
        data[key] = pa.array(keys.astype("uint32"), mask=keys == MISSING)
    truth = np.ones(n, dtype=bool)
    for j, field in enumerate(fields):
        data["v_" + field] = pa.array(truth, mask=(masks & (1 << j)) != 0)
    table = pa.table(data)
    target = out / "input.parquet"
    pq.write_table(table, target, compression="zstd", row_group_size=122880)
    evidence = dict(
        dataset=name,
        release=fname,
        source=url,
        source_sha256=raw_digest,
        raw_rows=raw_rows,
        vehicular_rows=n,
        fields=fields,
        queries=dims,
        projected_sha256=sha(target),
        program="https://github.com/saatvikkher/missing-traffic/blob/" + EDITION,
        oracle={d: oracle_sha(out / f"oracle-{d}.csv") for d in dims},
    )
    if name in expected and evidence["oracle"] != expected[name]["oracle"]:
        raise ValueError(
            f"Reconstructed counts disagree with frozen R reference: {name}"
        )
    (out / "case.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(name, n, dims, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT)
    parser.add_argument("--rscript", default="Rscript")
    parser.add_argument("names", nargs="*")
    args = parser.parse_args()
    for name in args.names or WEEKLY:
        prepare(name, args.cache, args.rscript)
