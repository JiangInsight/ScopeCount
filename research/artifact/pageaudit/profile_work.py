

import argparse
import csv
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panels", type=Path, required=True)
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    a = parser.parse_args()
    with a.out.open("w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(
            [
                "dataset",
                "dim",
                "words",
                "eligible",
                "improved",
                "one",
                "segmented",
                "literal_one",
                "literal_segmented",
            ]
        )
        for path in sorted(a.panels.glob("*/case.json")):
            case = json.loads(path.read_text())
            for dim in case["queries"]:
                cond = "date" if dim == "week" else "time"
                mask = sum(1 << i for i, f in enumerate(case["fields"]) if f != cond)
                line = subprocess.check_output(
                    [
                        a.exe,
                        path.parent / (dim + ".i32"),
                        path.parent / "masks.i32",
                        str(mask),
                    ],
                    text=True,
                )
                writer.writerow(
                    [case["dataset"], dim, *map(int, line.strip().split(","))]
                )


if __name__ == "__main__":
    main()
