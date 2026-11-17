

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pyreadr

from stops import DEFAULT, sha

CASES = ["ca_bakersfield", "co_aurora", "mn_saint_paul"]


def prepare(cache, name):
    start = time.perf_counter()
    panel = cache / "panels" / name
    meta = json.loads((panel / "case.json").read_text())
    source = pyreadr.read_r(cache / meta["release"])[None]
    assert len(source) == meta["raw_rows"]
    rows = source.loc[source["type"].eq("vehicular")]
    ref = pq.read_table(panel / "input.parquet")
    assert len(rows) == len(ref) == meta["vehicular_rows"]
    date = pd.to_datetime(rows["date"])
    days = date.to_numpy(dtype="datetime64[D]").astype("int64")
    data = {
        "week": pa.array(
            ((days + 3) // 7).astype("uint32"), mask=date.isna().to_numpy()
        )
    }
    if "time" in rows:
        seconds = rows["time"].astype(float)
        hrs = (seconds.fillna(0) // 3600).astype("uint32")
        data["hour"] = pa.array(hrs, mask=seconds.isna().to_numpy())
    else:
        data["hour"] = pa.nulls(len(rows), type=pa.uint32())
    for key in data:
        assert data[key].equals(ref[key].combine_chunks()), (name, key)
    for field in meta["fields"]:
        val = rows[field]
        if field == "date":
            arr = pa.array(date, type=pa.date32())
        elif field == "time":
            micros = np.rint(seconds.fillna(0).to_numpy() * 1e6).astype("int64")
            arr = pa.array(micros, mask=seconds.isna().to_numpy()).cast(pa.time64("us"))
        else:
            if isinstance(val.dtype, pd.CategoricalDtype):
                val = val.astype(object)
            arr = pa.array(val, from_pandas=True)
        data["v_" + field] = arr
        assert pc.is_null(arr).equals(pc.is_null(ref["v_" + field].combine_chunks())), (
            name,
            field,
        )
    table = pa.table(data)
    folder = cache / "typed" / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "input.parquet"
    pq.write_table(table, path, compression="zstd", row_group_size=122880)
    seconds_elapsed = time.perf_counter() - start
    assert pq.read_table(path).equals(table)
    result = dict(
        dataset=name,
        rows=len(table),
        schema={f.name: str(f.type) for f in table.schema},
        typed_bytes=path.stat().st_size,
        normalized_bytes=(panel / "input.parquet").stat().st_size,
        sha256=sha(path),
        conversion_seconds=seconds_elapsed,
        matched_masks=len(meta["fields"]),
        matched_keys=["hour", "week"],
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "names", nargs="*", help="Override the three default weekly cases"
    )
    args = parser.parse_args()
    results = []
    for case in args.names or CASES:
        r = prepare(args.cache, case)
        results.append(r)
        print(
            r["dataset"],
            r["rows"],
            r["typed_bytes"],
            r["conversion_seconds"],
            flush=True,
        )
    args.out.write_text(json.dumps(results, indent=2) + "\n")
