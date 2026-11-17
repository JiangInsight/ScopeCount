

import random
from fcc import connect
import numpy as np
import pyarrow as pa


def check(n, w, threads, mode):
    rng = np.random.default_rng(11 + n + 91 * w)
    base = rng.choice(
        np.array([0, 2, 3, 4095, 4096, 271195, 2**32 - 1], dtype=np.uint32), n
    )
    if mode == "runs":
        base = np.repeat(base[::97], 97)[:n]
    elif mode == "one":
        base = np.zeros(n, dtype=np.uint32)
    elif mode == "cross":
        base = (np.arange(n) // 2047 % 16).astype("uint32")
    nullgroup = (rng.random(n) < 0.1) if mode == "mixed" else np.zeros(n, dtype=bool)
    col = {"g": pa.array(base, mask=nullgroup)}
    for j in range(w):
        prob = [0, 1, 0.1, 0.47][j % 4]
        col["v" + str(j)] = pa.array(rng.random(n) > 0.5, mask=(rng.random(n) < prob))
    col["h"] = np.arange(n, dtype="uint64") % 7
    vals = ",".join(f"v{j}" for j in range(w))
    cc = ",".join(f"COUNT(v{j})" for j in range(w))
    output = ",".join(f"x.c{j+1}" for j in range(w))
    c = connect(threads)
    try:
        c.register("input", pa.table(col))
        c.execute("CREATE TABLE d AS SELECT * FROM input")
        for grouped in (False, True):
            sql = (
                f"SELECT h,g,count(*),{cc} FROM d WHERE g IS NOT NULL GROUP BY h,g ORDER BY h,g"
                if grouped
                else f"SELECT g,count(*),{cc} FROM d WHERE g IS NOT NULL GROUP BY g ORDER BY g"
            )
            expected = c.execute(sql).fetchall()
            for op in ("rows", "stream", "runs"):
                grouped_on = "GROUP BY h" if grouped else ""
                h = "h," if grouped else ""
                out = c.execute(
                    f"SELECT {h}x.key,x.n,{output} FROM (SELECT {h}unnest(scope_{op}{w}(g,{vals})) AS x FROM d {grouped_on}) GROUPS ORDER BY {h}x.key"
                ).fetchall()
                assert out == expected, (n, w, threads, mode, grouped, op)
    finally:
        c.close()


if __name__ == "__main__":
    sizes = [0, 1, 63, 64, 65, 2047, 2048, 2049, 8193]
    checks = 0
    for i, n in enumerate(sizes):
        for j, w in enumerate([1, 2, 7, 16, 24]):
            check(n, w, 1, ["mixed", "runs", "one", "cross"][(i + j) % 4])
            checks += 6
    for mode in ("mixed", "runs", "cross"):
        check(290123, 8, 4, mode)
        checks += 6
    print(checks, "ordered full-result comparisons against native SQL passed")
