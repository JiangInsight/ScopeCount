

import argparse, collections, csv, os, random, struct, subprocess
from pathlib import Path
import pandas as pd

P = Path(__file__).resolve().parents[3]
DATASETS = ["crash", "diabetes", "maude", "nhanes", "scania", "storm", "survey", "taxi"]


def write(path, requests):
    with path.open("w", newline="") as f:
        out = csv.writer(f, delimiter="\t", lineterminator="\n")
        out.writerow(["request_id", "l", "r", "must_null", "must_present"])
        for i, (bounds, predicates) in enumerate(requests):
            for pos, neg in predicates:
                out.writerow([i, *bounds, pos, neg])


def run(rows, trace, out, check=False):
    args = [P / "compiled" / "prefix.exe", rows, trace, out]
    if check:
        args.append("--exhaustive")
    subprocess.run(args, check=True)


def main():
    dest = P / "revision" / "online"
    dest.mkdir(exist_ok=True, parents=True)
    for d in DATASETS:
        groups = collections.OrderedDict()
        for line in (P / "data" / f"{d}.queries").read_text().splitlines():
            ident, a, b, l, r = line.split()
            group, slot = ident.rsplit("-", 1)
            slots = groups.setdefault(group, {})
            preds, windows = slots.setdefault(int(slot), ((int(a), int(b)), []))
            windows.append((int(l), int(r)))
        requests = []
        for g in groups.values():
            for z in g[0][1]:
                requests.append((z, [g[i][0] for i in range(8)]))
        write(dest / (d + ".tsv"), requests)
        run(P / "data" / (d + ".rows"), dest / (d + ".tsv"), dest / (d + ".out.tsv"))

    rng = random.Random(290032)
    f = dest / "edge.rows"
    masks = [rng.randrange(64) for _ in range(1024)]
    f.write_bytes(struct.pack("<" + "Q" * len(masks), *masks))
    pool = [(1, 2), (0, 6), (8, 16), (0, 48), (3, 0), (1, 0), (4, 0), (16, 8)]
    checks = []
    for seed in range(24):
        r = random.Random(seed)
        requests = []
        for i in range(20):
            selected = r.sample(pool, r.randint(1, 5))
            if i % 6 == 5:
                selected.append(selected[0])
            low = r.randrange(512)
            requests.append(((low, low + 256), selected))
        write(dest / "edge.tsv", requests)
        run(f, dest / "edge.tsv", dest / "edge.out.tsv", True)
        checks.append(pd.read_csv(dest / "edge.out.tsv", sep="\t").assign(seed=seed))
    pd.concat(checks).to_csv(dest / "exhaustive.tsv", sep="\t", index=False)


if __name__ == "__main__":
    main()
