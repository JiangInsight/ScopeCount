



import argparse, csv, json, sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve()
P = HERE.parents[3]
sys.path.insert(0, str(HERE.parents[1] / "engine"))
import replay


def process(base, out, repeats, methods):
    sources = pd.read_csv(base / "manifest.tsv", sep="\t", keep_default_na=False)
    eligible = (
        sources.loc[sources.status == "ok"].copy().sort_values(["resource", "table"])
    )
    assert not eligible[["resource", "table"]].duplicated().any()
    out.mkdir(exist_ok=True, parents=True)
    con = replay.connect()
    try:
        for k, row in enumerate(eligible.itertuples(index=False), start=1):
            key = f"{row.resource}-{row.table}"
            path = base / "resources" / str(row.resource) / row.table
            target = out / (key + ".tsv")
            if target.exists():
                saved = pd.read_csv(target, sep="\t")
                assert len(saved) == repeats * len(methods) and set(
                    saved.backend
                ) == set(methods)
                continue
            result = replay.run(
                path.with_suffix(".rows"),
                path.with_suffix(".tsv"),
                repeats=repeats,
                methods=methods,
                con=con,
                dataset=key,
            )
            expected = tuple(json.loads(row.observed))
            if not all(
                tuple(map(int, item["results"].split(","))) == expected
                for item in result
            ):
                raise AssertionError(f"Published result mismatch {key}")
            replay.save(result, target)
            if k % 50 == 0:
                print(k, len(eligible), flush=True)
    finally:
        con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", type=Path, default=P / "traces" / "transport")
    p.add_argument("--out", type=Path, default=P / "revision" / "pan-runs")
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument(
        "--methods",
        nargs="+",
        default=["tree", "independent", "bitmap", "lazy", "synopsis", "sql", "sql_opt"],
    )
    args = p.parse_args()
    process(args.base, args.out, args.repeats, args.methods)
