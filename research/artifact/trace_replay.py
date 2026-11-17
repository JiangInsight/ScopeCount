

import argparse
import hashlib
import json
from pathlib import Path

from engine.replay import run, save

HERE = Path(__file__).resolve().parent
TRACE = HERE.parents[1] / "traces" / "matched"
OUTPUT = HERE.parents[1] / "runs" / "matched_engine"
CASES = (
    "agency_providers",
    "press_facebook",
    "press_ftc",
    "press_icf",
    "press_insurance",
    "sql_table_cttdb_requestors_csv",
    "sql_table_enriched_proteins_for_s4_txt",
    "sql_table_fish546tjgr_cds_int_mcpg_2",
)
METHODS = (
    "tree_direct",
    "bitmap_direct",
    "sql_opt",
    "tree_direct_memo",
    "bitmap_direct_memo",
    "sql_opt_memo",
)


def replay(source, out, repeats):
    for case in CASES:
        folder = source / case
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf8"))
        rows = folder / "input.rows"
        if hashlib.sha256(rows.read_bytes()).hexdigest() != metadata["mask_sha256"]:
            raise ValueError(f"{case}: input digest mismatch")
        recorded = {
            str(q["id"]): tuple(q.get("published_counts", q["expected"]))
            for q in metadata["requests"]
        }
        results = run(rows, folder / "trace.tsv", repeats, METHODS, dataset=case)
        for row in results:
            actual = tuple(map(int, row["results"].split(",")))
            if actual != recorded[row["request_id"]]:
                raise AssertionError((case, row["request_id"], actual, recorded))
        if len(results) != len(recorded) * repeats * len(METHODS):
            raise AssertionError(f"{case}: incomplete timing results")
        save(results, out / f"{case}.tsv")
        print(
            case, len(results), "verified method/request/repetition results", flush=True
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=TRACE)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    replay(args.source, args.out, args.repeats)
