
import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from summarize import summarize


HERE = Path(__file__).resolve().parent
REVISION = HERE.parents[2] / "revision"
EXPECTED_TABLES = {"ci-pair": 1226, "ci-memo": 1226, "ci-fresh": 128}


def repayment(cross, method):
    tree = cross[cross.method.eq(method)].copy()
    assert len(tree) == 1226 and tree.dataset.is_unique and tree.n.eq(40).all()
    tree["feed"] = tree.dataset.str.rsplit("-", n=1).str[0]
    tree["premium"] = tree.build_delta_ns.gt(0)
    tree["repaid"] = tree.premium & tree.sustained.gt(0)
    cohort = tree.groupby("feed")[["repaid", "premium"]].sum().to_numpy()
    assert len(cohort) == 649
    generator = np.random.default_rng(20261109)
    estimates = []
    for _ in range(20):
        indices = generator.integers(len(cohort), size=(500, len(cohort)))
        samples = cohort[indices].sum(axis=1)
        estimates.extend(samples[:, 0] / samples[:, 1])
    low, high = np.quantile(estimates, [.025, .975]) * 100
    h = tree.loc[tree.premium, "sustained"]
    return {
        "premium": len(h), "by_one": int(h.eq(1).sum()),
        "by_ten": int(h.between(2, 10).sum()),
        "by_forty": int(h.between(11, 40).sum()), "censored": int(h.eq(0).sum()),
        "repaid_pct": float(tree.repaid.sum() / len(h) * 100),
        "ci95": [float(low), float(high)],
        "endpoint_win": int(tree.end_delta_ns.lt(0).sum()),
        "unanimous_win": int(tree.allfive.sum()),
        "unanimous_loss": int(tree.allfive_loss.sum()),
    }


def cache_latencies(source):


    timings = []
    for path in sorted(source.glob("*.tsv")):
        data = pd.read_csv(path, sep="\t", usecols=[
            "backend", "ordinal", "rep", "request_ns", "index_build_ns",
            "result_cache_hits", "rules"
        ])
        assert len(data) == 3 * 40 * 5
        assert not data.duplicated(["backend", "rep", "ordinal"]).any()
        for method, frame in data.groupby("backend"):
            misses = frame[frame.ordinal.eq(1)]
            hits = frame[frame.ordinal.gt(1)]
            assert len(misses) == 5 and misses.result_cache_hits.eq(0).all()
            assert len(hits) == 195 and (hits.result_cache_hits == hits.rules).all()
            timings.append({
                "method": method, "table": path.stem,
                "first_paid_us": float((misses.request_ns + misses.index_build_ns).median() / 1000),
                "later_hit_us": float(hits.request_ns.median() / 1000),
            })
    results = {}
    for method, rows in pd.DataFrame(timings).groupby("method"):
        results[method] = {
            col: [float(v) for v in rows[col].quantile([.5, .95])]
            for col in ("first_paid_us", "later_hit_us")
        }
    return results


def collect(root):
    summary_dir = root / "summaries"
    result = {}
    datasets = {}
    for name, n in EXPECTED_TABLES.items():
        directory = root / name
        files = list(directory.glob("*.tsv"))
        if len(files) != n:
            raise ValueError(f"{directory}: expected {n} completed tables, found {len(files)}")
        datasets[name] = {file.stem for file in files}
        summarize(directory, summary_dir, expected_repeats=5, expected_requests=40)
        cross = pd.read_csv(summary_dir / f"{name}-cross.csv")
        totals = pd.read_csv(summary_dir / f"{name}-totals.csv")
        assert totals.n.eq(40).all() and totals.groupby("method").size().eq(n).all()
        totals = totals.groupby("method").paid_ns.sum() / 1e9
        arm = {"tables": n, "paid_seconds": totals.to_dict()}
        if name != "ci-fresh":
            method = "tree_direct_memo" if name == "ci-memo" else "tree_direct"
            arm.update(repayment(cross, method))
        result[name] = arm
    trace_archive = HERE.parent / "operational" / "operational_traces.zip"
    with zipfile.ZipFile(trace_archive) as archive, archive.open("ci/manifest.tsv") as stream:
        manifest = pd.read_csv(stream, sep="\t")
    confirmed = manifest.loc[manifest.status.eq("ok")].copy()
    confirmed["dataset"] = confirmed.feed + "-" + confirmed.table
    assert datasets["ci-pair"] == datasets["ci-memo"] == set(confirmed.dataset)
    assert datasets["ci-fresh"] <= datasets["ci-pair"]
    confirmed = confirmed.sort_values(["table", "rows", "feed"])
    ranks = confirmed.groupby("table").rows.rank(method="first")
    confirmed["octile"] = ranks.groupby(confirmed.table).transform(lambda x: pd.qcut(x, 8, labels=False))
    selected = confirmed[confirmed.dataset.isin(datasets["ci-fresh"])]
    assert selected.groupby(["table", "octile"]).size().tolist() == [8] * 16
    result["memo_latency_quantiles_us"] = cache_latencies(root / "ci-memo")
    return result


def restore_run_files(evidence, root):

    import pyarrow.parquet as parquet

    for cohort in EXPECTED_TABLES:
        destination = root / cohort
        destination.mkdir()
        metadata = json.loads((evidence / (cohort + ".json")).read_bytes())
        for part in metadata:
            name = part["file"]
            if Path(name).name != name:
                raise ValueError(name)
            shard = evidence / name
            if hashlib.sha256(shard.read_bytes()).hexdigest() != part["sha256"]:
                raise ValueError(shard)
            rows = parquet.ParquetFile(shard)
            assert rows.metadata.num_rows == part["records"]
            table = rows.read().to_pandas()
            groups = table.groupby('dataset', sort=False)
            assert len(groups) == part['tables']
            for dataset, data in groups:
                if Path(dataset).name != dataset:
                    raise ValueError(dataset)
                with (destination / (dataset + ".tsv")).open("x", encoding="utf-8", newline="") as out:
                    data.to_csv(out, index=False, sep="\t")


def format_tex(result):
    fresh = result["ci-pair"]
    memo = result["ci-memo"]
    rows = [f"No positive build premium & {fresh['tables'] - fresh['premium']} & {memo['tables'] - memo['premium']} " + r"\\"]
    for label, key in [
        ("Positive build premium", "premium"),
        ("Repaid at request 1", "by_one"),
        ("Repaid at requests 2--10", "by_ten"),
        ("Repaid at requests 11--40", "by_forty"),
        ("Unrepaid at request 40", "censored"),
        ("Tree faster in all five at 40", "unanimous_win"),
        ("Bitmap faster in all five at 40", "unanimous_loss"),
    ]:
        rows.append(f"{label} & {fresh[key]:,} & {memo[key]:,} " + r"\\")
    table = r"""
\begin{table}[t]
\centering
\caption{Tree repayment on 1,226 recurring CI tables.}
\label{tab:ci-payback}
\begin{tabular}{lrr}
\toprule
Build or service outcome & Recompute & Cache answers \\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
\end{table}
"""
    ci = lambda x: f"{x['ci95'][0]:.1f}--{x['ci95'][1]:.1f}\\%"
    seconds = memo["paid_seconds"]
    subset = result["ci-fresh"]["paid_seconds"]
    sql = result["memo_latency_quantiles_us"]["sql_opt_memo"]
    first = sql["first_paid_us"]
    later = sql["later_hit_us"]
    return (
        r"Table~\ref{tab:ci-payback} compares the tree with the direct bitmap through the 40 recorded exposures of each table. "
        "The first two rows partition all 1,226 tables by construction cost. The four repayment rows cover only those with a positive tree premium. "
        f"Across the full cohort, recomputing the answers cost {fresh['paid_seconds']['tree_direct']:.3f}~s "
        f"for the tree and {fresh['paid_seconds']['bitmap_direct']:.3f}~s for the bitmap. "
        f"The tree recovered its premium on {fresh['repaid_pct']:.1f}\\% of the premium cases when answers were recomputed "
        f"and {memo['repaid_pct']:.1f}\\% with answer caching. The 95\\% bootstrap intervals "
        f"were {ci(fresh)} and {ci(memo)}, resampling all tables of each feed together. "
        "The last two rows count five-repeat agreement across the entire cohort.\n"
        + table + "\n"
        + "With the same answer cache, the summed per-table median cost for 40 requests was "
        f"{seconds['sql_opt_memo']:.3f}~s for SQL, {seconds['bitmap_direct_memo']:.3f}~s for the bitmap "
        f"and {seconds['tree_direct_memo']:.3f}~s for the tree. Across tables, the median and 95th percentile "
        f"of first-call SQL latency were {first[0]:.0f} and {first[1]:.0f}~$\\mu$s. "
        f"For each table's median subsequent hit they were {later[0]:.1f} and {later[1]:.1f}~$\\mu$s. "
        "With answer caching disabled on 128 tables stratified by file type and size, the same 40 calls cost "
        f"{subset['sql_opt']:.3f}~s for SQL, {subset['bitmap_direct']:.3f}~s for the bitmap, "
        f"{subset['tree_direct']:.3f}~s for the tree and {subset['online_direct']:.3f}~s for the online policy with both base representations included.\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=REVISION)
    parser.add_argument("--packed", type=Path, help="Use existing Parquet timing shards and their manifests")
    parser.add_argument("--tex", type=Path, default=HERE.parents[1] / "operational_payback.tex")
    parser.add_argument("--json", type=Path, default=HERE / "ci_payback_summary.json")
    args = parser.parse_args()
    if args.packed is None:
        results = collect(args.root)
    else:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            restore_run_files(args.packed, root)
            results = collect(root)
    args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    args.tex.write_text(format_tex(results), encoding="utf-8")
