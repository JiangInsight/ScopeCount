

import os, tempfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def connect():
    if os.name == "nt":

        import pyarrow._parquet
    db = duckdb.connect(config={"allow_unsigned_extensions": "true", "threads": "1"})
    file = (
        Path(os.environ.get("SCOPEPAGE_BUILD", ROOT / "compiled/scopepages"))
        / "scopepages.duckdb_extension"
    )
    db.execute("LOAD '" + file.as_posix().replace("'", "''") + "'")
    return db


def quote(x):
    return "'" + str(x).replace("'", "''") + "'"


def pagequery(path, group, rules, l, r, mode):
    pairs = ",".join(f"{a}/{b}" for a, b in rules)
    return f"SELECT unnest(scope_page_counts(content,{group},{quote(pairs)},{l},{r},{quote(mode)})) AS v FROM read_blob({quote(path.as_posix())})"


def main():
    con = connect()
    rng = np.random.default_rng(247)
    with tempfile.TemporaryDirectory() as tmp:
        for version in ["1.0", "2.0"]:
            for dictionary in [False, True]:
                for stats in [False, True]:
                    for n in [0, 1, 63, 64, 65, 2217]:
                        k = rng.integers(-3, 3, size=n)
                        k[k == -2] = -100
                        a = rng.random(n) < 0.35
                        b = rng.random(n) < 0.2
                        tab = pa.table(
                            {
                                "g": pa.array(k.astype("int32"), mask=k == -100),
                                "a": pa.array(np.ones(n, dtype="bool"), mask=a),
                                "b": pa.array(np.ones(n, dtype="int16"), mask=b),
                            }
                        )
                        path = Path(tmp) / "x.parquet"
                        pq.write_table(
                            tab,
                            path,
                            use_dictionary=dictionary,
                            data_page_version=version,
                            write_statistics=stats,
                            row_group_size=127,
                        )
                        rules = [(0, 0), (2, 0), (0, 2), (2, 4), (2, 2), (2, 0)]
                        for group in [-1, 0]:
                            for l, r in [(0, n), (n // 3, n // 2), (n, n)]:
                                gold = {}
                                if group < 0:
                                    gold[0] = [0] * 7
                                for i in range(l, r):
                                    if group == 0 and k[i] == -100:
                                        continue
                                    val = gold.setdefault(
                                        0 if group == -1 else k[i], [0] * 7
                                    )
                                    mask = (2 if a[i] else 0) | (4 if b[i] else 0)
                                    val[0] += 1
                                    for j, (p, q) in enumerate(rules):
                                        val[j + 1] += int(
                                            (mask & p) == p and not (mask & q)
                                        )
                                for mode in [
                                    "runs",
                                    "nosub",
                                    "cert",
                                    "incidence",
                                    "positive",
                                    "local",
                                    "local_nopivot",
                                ]:
                                    result = con.execute(
                                        pagequery(path, group, rules, l, r, mode)
                                    ).fetchall()
                                    assert {v[0]: v[1:-4] for v, in result} == gold, (
                                        n,
                                        group,
                                        version,
                                        stats,
                                        mode,
                                        result,
                                        gold,
                                    )
                                for mode in [
                                    "merge",
                                    "score",
                                    "scorelocal",
                                    "packed",
                                    "boundary",
                                    "boundary_pos",
                                    "dense",
                                    "roaring",
                                    "residual",
                                    "endpoint",
                                    "endpoint_dense",
                                    "endpoint8",
                                    "endpoint_sparse",
                                    "segment",
                                    "segment_one",
                                ]:
                                    result = con.execute(
                                        pagequery(path, group, rules, l, r, mode)
                                    ).fetchall()
                                    assert {v[0]: v[1:-4] for v, in result} == {
                                        g: [a[0], sum(a[1:])] for g, a in gold.items()
                                    }
    con.close()
    print(
        "All encoded-stream, footer, grouping and half-open slice regressions passed."
    )


if __name__ == "__main__":
    main()
