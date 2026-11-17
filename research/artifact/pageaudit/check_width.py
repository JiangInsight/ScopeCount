

import tempfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from check import connect, pagequery


def run():
    checks = 0
    rng = np.random.default_rng(7149)
    n = 12317
    groups = rng.choice(np.array([0, 3, 2**32 - 1], dtype=np.uint32), n)
    groups[:4096] = 2**32 - 1
    missing = rng.random((63, n)) < 0.36
    missing[1] = ~missing[0]
    missing[:, 4095:4163] = True
    missing[:, 8190:8238] = False
    fields = {
        f"v{i}": pa.array(np.ones(n, dtype=bool), mask=missing[i]) for i in range(63)
    }
    fields["g"] = pa.array(groups)
    rules = [(1 << i, 0) for i in range(63)] + [(1, 0)]
    scores = missing.sum(axis=0) + missing[0]
    with tempfile.TemporaryDirectory() as tmp, connect() as db:
        file = Path(tmp) / "wide.parquet"
        for ver in ("1.0", "2.0"):
            pq.write_table(
                pa.table(fields),
                file,
                data_page_version=ver,
                row_group_size=4101,
                data_page_size=512,
            )
            for a, b in [(0, n), (63, 8250), (4096, 4161), (8222, 8222)]:
                expected = {
                    int(k): (
                        int(np.sum(groups[a:b] == k)),
                        int(scores[a:b][groups[a:b] == k].sum()),
                    )
                    for k in np.unique(groups[a:b])
                }
                for m in (
                    "endpoint",
                    "endpoint_dense",
                    "endpoint8",
                    "endpoint_sparse",
                    "segment",
                    "segment_one",
                    "dense",
                    "roaring",
                    "residual",
                    "boundary",
                    "packed",
                    "merge",
                ):
                    checks += 1
                    result = db.execute(pagequery(file, 63, rules, a, b, m)).fetchall()
                    assert {v[0]: (v[1], v[2]) for v, in result} == expected, (
                        m,
                        ver,
                        a,
                        b,
                    )
    print(f"{checks} wide-score results agree on clipped and complete pages.")


if __name__ == "__main__":
    run()
