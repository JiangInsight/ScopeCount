

from pathlib import Path
from hashlib import sha256
import argparse, json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq


def verify(folder):
    total = 0
    indexes = sorted(folder.glob("*.json"))
    if not indexes:
        raise ValueError("No timing manifests")
    for manifest in indexes:
        n = 0
        seen = set()
        for entry in json.loads(manifest.read_text()):
            path = folder / entry["file"]
            assert (
                path.parent == folder
                and sha256(path.read_bytes()).hexdigest() == entry["sha256"]
            ), path
            d = pq.read_table(
                path,
                columns=[
                    "dataset",
                    "backend",
                    "rep",
                    "ordinal",
                    "request_id",
                    "results",
                    "index_build_ns",
                    "request_ns",
                ],
            ).to_pandas()
            assert len(d) == entry["records"] and len(d) > 0
            datasets = set(d.dataset)
            assert not (seen & datasets) and len(datasets) == entry["tables"]
            seen |= datasets
            assert not d.duplicated(["dataset", "backend", "rep", "ordinal"]).any()
            requests = d.groupby(["dataset", "ordinal"])
            assert (
                requests.results.nunique().eq(1).all()
                and requests.request_id.nunique().eq(1).all()
            )
            assert (d.index_build_ns >= 0).all() and (d.request_ns >= 0).all()
            g = d.groupby(["dataset", "backend", "rep"])
            assert g.index_build_ns.nunique().eq(1).all()
            assert g.ordinal.min().eq(1).all() and (g.ordinal.max() == g.size()).all()
            assert set(d.rep) == set(range(5))
            expected = d.groupby("dataset").backend.nunique() * 5
            size = requests.size().rename("observed").reset_index()
            assert (size.observed == size.dataset.map(expected)).all()
            n += len(d)
        print(manifest.stem, len(seen), "snapshots", n, "records")
        total += n
    print("Verified", total, "timed method-request observations")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "folder", type=Path, nargs="?", default=Path(__file__).parent / "evidence"
    )
    verify(p.parse_args().folder.resolve())
