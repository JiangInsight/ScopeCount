

from verify import check as vector_check
from fcc import connect
import fcc
from pathlib import Path
import numpy as np
import pyarrow as pa
import os


def verify():
    rng = np.random.default_rng(31711)
    checked = 0
    for t in (1, 4):
        c = connect(t)
        try:
            for i, n in enumerate((0, 1, 63, 64, 65, 2047, 2048, 2049, 14583, 321015)):
                w = (1, 2, 8, 16, 24)[i % 5]
                for kind in (0, 1, 2):
                    key = (
                        np.arange(n, dtype=np.uint32) // (3000 if kind == 0 else 1)
                    ) % (3 if kind == 1 else 23)
                    key[key == 2] = 2**32 - 1
                    sig = rng.integers(0, 4, n, dtype="uint32")
                    cols = {
                        "g": pa.array(
                            key,
                            mask=(key == 5 if kind == 2 else np.zeros(n, dtype=bool)),
                        ),
                        "h": np.arange(n, dtype="uint32") % 3,
                    }
                    for j in range(w):
                        mark = (
                            sig < ((j + 1) % 5)
                            if kind != 2
                            else rng.random(n) < (j % 11) / 10
                        )
                        if j % 2:
                            mark = ~mark
                        cols[f"v{j}"] = pa.array(rng.random(n) < 0.5, mask=mark)
                    c.register("q", pa.table(cols))
                    for grouped in (False, True):
                        h = "h," if grouped else ""
                        gb = "GROUP BY h" if grouped else ""
                        vals = ",".join(f"v{j}" for j in range(w))
                        total = "+".join(f"count(v{j})" for j in range(w))
                        oracle = c.execute(
                            f"SELECT {h}g,count(*),{total} FROM q WHERE g IS NOT NULL GROUP BY {h}g ORDER BY {h}g"
                        ).fetchall()
                        for op in ("weight", "wrows"):
                            result = c.execute(
                                f"SELECT {h}x.key,x.n,x.c1 FROM (SELECT {h}unnest(scope_{op}{w}(g,{vals})) AS x FROM q {gb}) t ORDER BY {h}x.key"
                            ).fetchall()
                            assert result == oracle, (t, n, w, kind, grouped, op)
                            checked += 1
                    c.unregister("q")
        finally:
            c.close()
    print(checked, "weighted grouped answers matched native relational aggregation")


if __name__ == "__main__":
    verify()
