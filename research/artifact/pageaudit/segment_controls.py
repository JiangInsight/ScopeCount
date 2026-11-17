

import argparse
import hashlib
from pathlib import Path
import random
import tempfile
import time
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from benchmark import commands
from check import connect


def run(out):
    rng = np.random.default_rng(68178)
    n = 64 * 16384
    cols = 24
    missing = rng.integers(0, 2, (n, cols), dtype=np.uint8).astype(bool)
    pairs = [
        (0, 7),
        (1, 6),
        (0, 7),
        (2, 6),
        (0, 6),
        (3, 7),
        (4, 6),
        (3, 7),
        (5, 6),
        (3, 6),
    ]
    cases = {
        "two_epochs": list(range(10)),
        "interleaved": [0, 5, 1, 2, 7, 3, 4, 6, 9, 8],
    }
    table = {
        f"v{j}": pa.array(np.ones(n, dtype=bool), mask=missing[:, j])
        for j in range(cols)
    }
    samples = []
    with tempfile.TemporaryDirectory() as tmp, connect() as db:
        for case, order in cases.items():
            ids = np.tile(
                np.concatenate([np.repeat(pairs[i][0], pairs[i][1]) for i in order]),
                n // 64,
            ).astype(np.uint32)
            path = Path(tmp) / (case + ".parquet")
            pq.write_table(
                pa.table({"g": pa.array(ids), **table}),
                path,
                compression="zstd",
                row_group_size=122880,
            )
            scores = missing.sum(axis=1)
            gold = [
                (int(k), int((ids == k).sum()), int(scores[ids == k].sum()))
                for k in np.unique(ids)
            ]
            sql = commands(path, "g", list(table), True, n)[0]
            ops = ["sql", "packed", "endpoint", "segment_one", "segment"]
            rand = random.Random(case)
            file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            for block in range(2):
                rand.shuffle(ops)
                shifts = list(range(len(ops)))
                rand.shuffle(shifts)
                for t, shift in enumerate(shifts):
                    for pos, m in enumerate(ops[shift:] + ops[:shift]):
                        start = time.perf_counter_ns()
                        actual = db.execute(sql[m]).fetchall()
                        ns = time.perf_counter_ns() - start
                        assert actual == gold
                        samples.append(
                            [case, file_sha, n, cols, block * 5 + t, pos, m, ns]
                        )
    frame = pd.DataFrame(
        samples,
        columns=[
            "layout",
            "file_sha256",
            "rows",
            "fields",
            "rep",
            "position",
            "method",
            "ns",
        ],
    )
    out.parent.mkdir(exist_ok=True, parents=True)
    frame.to_csv(out, sep="\t", index=False)
    print(frame.groupby(["layout", "method"]).ns.median().unstack() / 1e6)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    run(p.parse_args().out)
