



import argparse, concurrent.futures, hashlib, json, os, zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import requests


def fetch(month, base):
    year, month_no = map(int, month.split("-"))
    url = f"https://transtats.bts.gov/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month_no}.zip"
    dest = base / (month + ".zip")
    if not dest.exists():
        with requests.get(url, stream=True, timeout=(20, 120)) as response:
            response.raise_for_status()
            tmp = dest.with_suffix(".partial")
            with tmp.open("wb") as f:
                for chunk in response.iter_content(1 << 20):
                    f.write(chunk)
            with zipfile.ZipFile(tmp) as archive:
                assert any(x.lower().endswith(".csv") for x in archive.namelist())
            tmp.replace(dest)
    return month, dest, url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "datasets/bts",
    )
    args = parser.parse_args()
    base = args.dir
    base.mkdir(parents=True, exist_ok=True)
    months = [f"{y}-{m:02}" for y in range(2022, 2025) for m in range(1, 13)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        sources = list(ex.map(lambda m: fetch(m, base), months))
    schema = None
    offset = 0
    manifest = []
    with (base / "bts.rows").open("wb") as output:
        for month, path, url in sources:
            with zipfile.ZipFile(path) as arc:
                csv = next(k for k in arc.namelist() if k.lower().endswith(".csv"))
                with arc.open(csv) as f:
                    cols = pd.read_csv(f, nrows=0).columns.tolist()
                names = [
                    k
                    for k in cols[cols.index("CRSDepTime") :]
                    if not k.startswith("Unnamed")
                ][:63]
                if schema is None:
                    schema = names
                if schema != names:
                    raise ValueError((month, names))
                count = 0
                with arc.open(csv) as f:
                    for tb in pd.read_csv(
                        f, usecols=names, dtype=str, na_filter=False, chunksize=65000
                    ):
                        masks = np.zeros(len(tb), dtype="<u8")
                        for j, name in enumerate(names):
                            masks |= (tb[name].to_numpy() == "").astype("uint64") << j
                        output.write(masks.tobytes())
                        count += len(masks)
            with path.open("rb") as source:
                sha = hashlib.file_digest(source, "sha256").hexdigest()
            manifest.append(
                dict(month=month, start=offset, end=offset + count, sha256=sha, url=url)
            )
            offset += count
            print(month, count, flush=True)
    rows = np.memmap(base / "bts.rows", dtype="<u8", mode="r")
    d = {
        "names": schema,
        "sources": manifest,
        "rows": offset,
        "shapes": len(np.unique(rows)),
    }
    (base / "bts.json").write_text(json.dumps(d, indent=2))


    pairs = [
        ("DepTime", "ArrTime"),
        ("WheelsOff", "WheelsOn"),
        ("TaxiOut", "TaxiIn"),
        ("CarrierDelay", "WeatherDelay"),
        ("ArrDelay", "DepDelay"),
        ("AirTime", "ActualElapsedTime"),
        ("NASDelay", "LateAircraftDelay"),
        ("CancellationCode", "DepTime"),
    ]
    with (base / "bts.trace.tsv").open("w") as f:
        f.write("request_id\tl\tr\tmust_null\tmust_present\n")
        for i, rec in enumerate(manifest):
            for j, (a, b) in enumerate(pairs):
                pa, pb = 1 << schema.index(a), 1 << schema.index(b)
                f.write(
                    f"{i}\t{rec['start']}\t{rec['end']}\t{pa if j%2 else 0}\t{pb if j%2 else pa|pb}\n"
                )
    print("rows", offset, "shapes", d["shapes"], "cols", len(schema))


if __name__ == "__main__":
    main()
