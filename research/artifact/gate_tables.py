
import argparse
from itertools import product
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parents[1]

def small_tree_oracle():


    checked = certificates = always_false = 0
    for edge in ((0, 5, 5, 5, 5, 5, 5), (0, 2, 17, 4, 21, 11, 3)):
        for leaves in product(range(4), repeat=4):
            lower, true_tree = {}, {}
            for keep in (1, 2, 3):
                targets = [x & keep for x in leaves]
                allowed = [x for x in range(4) if not x & ~keep]
                best = float("inf")
                for root, left, right in product(allowed, repeat=3):
                    labels = [root, left, right, *targets]
                    full = 0
                    for j in range(1, 7):
                        diff = labels[j] ^ labels[(j-1)//2]
                        if diff:
                            full += edge[j] + diff.bit_count()
                    best = min(best, full)
                true_tree[keep] = best
                diff1, diff2 = targets[0] ^ targets[1], targets[2] ^ targets[3]
                lower[keep] = (min(edge[3:5])*bool(diff1) + diff1.bit_count() +
                               min(edge[5:7])*bool(diff2) + diff2.bit_count())
                if lower[keep] > best:
                    raise ValueError((edge, leaves, keep, lower[keep], best))
            for h in (1, 24):


                group_sets = [[(1, 0), (2, 0)], [(1, 13), (2, 30)]]
                if all(x in (0, 3) for x in leaves):
                    group_sets.append([(3, 13)])
                for groups in group_sets:
                    cache = sum(p for _, p in groups) + 10*h
                    def mixed(keep, tree):
                        return (h*tree[keep] + h*5*(2-keep.bit_count()) +
                                sum(p for bits, p in groups if bits & ~keep))
                    claimed = all(mixed(s, lower) >= cache for s in (1, 2, 3))
                    optimal = min([cache] + [mixed(s, true_tree) for s in (1, 2, 3)])
                    if claimed and optimal != cache:
                        raise ValueError("False certificate on tiny tree")
                    if leaves == (0, 0, 0, 0):
                        if claimed or optimal:
                            raise ValueError("Incorrect constant-false control")
                        always_false += 1
                    checked += 1
                    certificates += int(claimed)
    return checked, certificates, always_false

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=HERE.parent/"runs/gate.tsv")
    p.add_argument("--out", type=Path, default=HERE/"gate_numbers.tex")
    opts = p.parse_args()
    data = pd.read_csv(opts.input, sep="\t", dtype={"digest":str})
    key = ["dataset", "bundle"]
    methods = {"cached_bitmaps", "frontier_joint", "portfolio", "gated_portfolio"}
    groups = data.groupby(key)
    if (data.duplicated(key+["rep","method"]).any() or
        set(data.method) != methods or set(data.rep) != {0, 1, 2} or
        not groups.size().eq(12).all() or len(groups) != 168 or
        not data.groupby("dataset").bundle.nunique().eq(21).all() or
        not groups[["digest","inspected","certified","full_proof"]].nunique().eq(1).all().all() or
        (data.certified > data.full_proof).any()):
        raise ValueError("Incomplete or inconsistent gate timing records")
    correct = data.pivot(index=key+["rep"], columns="method", values="keep")
    if not correct["portfolio"].equals(correct["gated_portfolio"]):
        raise ValueError("Placement differs")
    if not data.loc[(data.certified == 1) & data.method.eq("portfolio"),"keep"].eq(0).all():
        raise ValueError("False admission")
    bundle = data.loc[data.method.eq("gated_portfolio") & data.rep.eq(0)].set_index(key)
    tagged = bundle.certified.astype(bool)
    t = data.assign(total=data.compile_ns+data.exec_ns).groupby(key+["method"]).total.median().unstack()
    times = t.groupby("dataset").sum()/1e6
    subset = t.loc[tagged]
    tests, tiny_yes, negative = small_tree_oracle()
    v = dict(
        GateCount=len(bundle), GateYes=int(tagged.sum()), GateAll=int(bundle.full_proof.sum()),
        GateSurvey=int(bundle.loc["survey"].certified.sum()),
        GateCostLow=f"{data.loc[data.method.eq('gated_portfolio'),'gate_ns'].min()/1e3:.1f}",
        GateCostHi=f"{data.loc[data.method.eq('gated_portfolio'),'gate_ns'].quantile(.95)/1e3:.1f}",
        GateSurveyBase=f"{times.loc['survey','portfolio']:.2f}",
        GateSurveyGated=f"{times.loc['survey','gated_portfolio']:.2f}",
        GateSurveyCache=f"{times.loc['survey','cached_bitmaps']:.2f}",
        GateSurveyGain=f"{times.loc['survey','portfolio']/times.loc['survey','gated_portfolio']:.2f}",
        GateSurveyTree=f"{times.loc['survey','frontier_joint']:.2f}",
        GateNhaBase=f"{times.loc['nhanes','portfolio']:.2f}",
        GateNhaGated=f"{times.loc['nhanes','gated_portfolio']:.2f}",
        GateSlower=int((times.gated_portfolio>times.portfolio).sum()),
        GateCacheWin=int(subset.cached_bitmaps.lt(subset.frontier_joint).sum()),
        GateTiny=f"{tests:,}", GateTinyYes=f"{tiny_yes:,}", GateTinyNeg=negative,
        GateCatalog=f"{bundle.catalog_bytes.max()/1024:.1f}",
        GateCatalogMs=f"{bundle.catalog_ns.max()/1e6:.2f}",
    )
    opts.out.write_text("% Generated by artifact/gate_tables.py from gate.tsv\n"+
                        "".join("\\newcommand{\\"+k+"}{"+str(val)+"}\n" for k,val in v.items()),
                        encoding="utf-8")
    print("Median of three complete calls, summed over each dataset's 21 bundles (ms)")
    print(times.to_string())
    print(v)

if __name__=="__main__":
    main()
