

import argparse, os, sys
from pathlib import Path

here = Path(__file__).resolve()
sys.path.insert(0, str(here.parents[1] / "engine"))
import replay

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--base",
        type=Path,
        default=here.parents[3] / "datasets/bts",
    )
    p.add_argument(
        "--out", type=Path, default=here.parents[3] / "revision" / "bts" / "months.tsv"
    )
    p.add_argument("--repeats", type=int, default=5)
    args = p.parse_args()
    base = args.base
    con = replay.connect()
    try:
        temp = (base / "duck-tmp").resolve().as_posix().replace("'", "''")
        con.execute("SET temp_directory='" + temp + "'")
        runs = replay.run(
            base / "bts.rows",
            base / "bts.trace.tsv",
            repeats=args.repeats,
            methods=["tree_direct", "bitmap_direct", "online_direct", "sql_opt"],
            con=con,
            dataset="BTS",
        )
        replay.save(runs, args.out)
    finally:
        con.close()
