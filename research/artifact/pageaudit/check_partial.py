

from pathlib import Path
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq

from check import connect, pagequery


def run():


    n = 257
    g = [0] * 192 + [1] * 65
    v = [None if (i * 19 + 7) % 23 < 5 else 9 for i in range(n)]
    table = pa.table({"g": pa.array(g, "int32"), "v": pa.array(v, "int16")})
    trials = 0
    with connect() as db, tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "two-groups.parquet"
        for footer in [True, False]:
            for version in ["1.0", "2.0"]:
                pq.write_table(
                    table,
                    path,
                    row_group_size=n,
                    write_statistics=footer,
                    data_page_version=version,
                )
                for lo, hi, net in [
                    (0, n, 3),
                    (1, 256, 1),
                    (64, 192, 0),
                    (0, 192, 1),
                    (65, 65, 0),
                ]:
                    gold = {
                        group: (len(indices), sum(v[i] is None for i in indices))
                        for group in [0, 1]
                        if (indices := [i for i in range(lo, hi) if g[i] == group])
                    }
                    for mode in [
                        "cert",
                        "nosub",
                        "runs",
                        "incidence",
                        "positive",
                        "local",
                    ]:
                        rows = db.execute(
                            pagequery(path, 0, [(2, 0)], lo, hi, mode)
                        ).fetchall()
                        assert {r[0]: tuple(r[1:3]) for (r,) in rows} == gold
                        if rows:
                            expected = net if footer and mode == "cert" else 0
                            assert rows[0][0][-1] == expected, (
                                mode,
                                footer,
                                lo,
                                hi,
                                rows,
                                expected,
                            )
                        trials += 1
    print(f"{trials} file-to-result slice checks passed.")


if __name__ == "__main__":
    run()
