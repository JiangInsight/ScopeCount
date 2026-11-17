

import argparse
import json
import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from trace_replay import CASES, OUTPUT

PAPER = Path(__file__).resolve().parents[1]
REVISION = PAPER.parent / "revision"


def paid(df):
    df = df.sort_values(["backend", "rep", "ordinal"]).copy()
    df["cost"] = df.index_build_ns + df.groupby(["backend", "rep"]).request_ns.cumsum()
    return df


def ms(x):
    value = x / 1e6
    return f"{value:,.0f}" if value >= 100 else f"{value:.2f}"


def report(small, grouped, scoped):
    frame = pd.concat(
        [paid(pd.read_csv(small / f"{name}.tsv", sep="\t")) for name in CASES]
    )
    if frame.rep.nunique() != 5 or len(frame) != 300:
        raise ValueError("incomplete matched timings")
    provider = (
        frame[frame.dataset.eq("agency_providers") & frame.ordinal.eq(3)]
        .groupby("backend")
        .cost.median()
    )
    final = frame[frame.ordinal.eq(frame.groupby("dataset").ordinal.transform("max"))]
    end = final.groupby(["dataset", "backend"]).cost.median().unstack()
    sql_wins = int(
        ((end.sql_opt < end.tree_direct) & (end.sql_opt < end.bitmap_direct)).sum()
    )
    winners_text = (
        "all eight tables"
        if sql_wins == len(CASES)
        else f"{sql_wins} of the eight tables"
    )
    fcc = pd.read_csv(grouped / "grouped.tsv", sep="\t")
    sqlshare = pd.read_csv(scoped / "scoped.tsv", sep="\t")
    if len(fcc) != 15 or len(sqlshare) != 40:
        raise ValueError("incomplete scoped timings")
    cost = fcc.groupby("method").total_ns.median()
    pair = sqlshare[sqlshare.ordinal.eq(2)].groupby("method").paid_ns.median()
    manifest = json.loads((grouped / "evidence.json").read_text(encoding="utf8"))
    paired = json.loads((scoped / "evidence.json").read_text(encoding="utf8"))
    sqlshare_outs = sqlshare.groupby("request_id").result.unique()
    if not all(len(v) == 1 and v[0] == 1136 for v in sqlshare_outs):
        raise ValueError("unexpected source reconstruction")
    text = rf"""\subsection{{Archived analyst requests and scopes}}
Five public notebooks preserve seven full-table audit invocations and nine scalar outputs. One California transit analysis asks three times about two columns of the same 412-row provider table. The missing counts are 259, 200 and 259, including the numerators of two published percentages. Through the third request, the median paid times with identical result caching were {ms(provider['tree_direct_memo'])}, {ms(provider['bitmap_direct_memo'])} and {ms(provider['sql_opt_memo'])}\,ms for the tree, bitmap and native SQL. Each of the other four notebooks exposes one request. Three additional SQLShare service queries each count one nonnull column on an archived table~\cite{{sqlsharetrace}}. At the last observed request, optimized SQL had the lowest median paid time on {winners_text} with result caching disabled.

One FCC investigation grouped {manifest['rows']:,} comments by uploader and reported the fraction with an email address for accounts with at least 10,000 submissions~\cite{{fcccomments}}. We replayed the completeness projection of that single invocation, recovering all {manifest['published_groups']} published group sizes and rounded fractions. The distinct-address statistic in the same cell requires the addresses themselves. The {manifest['groups']} uploader groups occupy {manifest['source_group_runs']} contiguous runs in file order. The index methods each pay to find these runs, install their endpoints and build the index, then sum across the runs for each uploader. Median total times were {ms(cost['tree'])}\,ms for the tree, {ms(cost['bitmap'])}\,ms for bitmaps and {ms(cost['sql'])}\,ms for one native \texttt{{GROUP BY}}.

Two successive SQLShare requests count nonnull charge values where \texttt{{gaps=0}}. The first also requires a present \texttt{{pdb\_id}}. The second arrived five seconds later. On the released table, {paired['selected']:,} of {paired['rows']:,} rows meet the common filter, in {paired['runs']} runs. Both counts are {paired['selected']:,}. The indexes share the selection directory after charging it to the first request. Median paid time through both requests was {ms(pair['tree'])}\,ms for the tree, {ms(pair['bitmap'])}\,ms for bitmaps and {ms(pair['sql'])}\,ms for the direct SQL filters. SQL that materializes the selected columns once took {ms(pair['sql_reused'])}\,ms. The service records successful executions but omits historical counts and table versions.
"""
    return text


def package(small, grouped, scoped, path):


    summaries = []
    timings = {}
    for case in CASES:
        file = small / f"{case}.tsv"
        timings["matched/" + file.name] = file.read_bytes()
        frame = paid(pd.read_csv(file, sep="\t"))
        for suffix in ("", "_memo"):
            tree = frame[frame.backend.eq("tree_direct" + suffix)]
            for name in ("bitmap_direct", "sql_opt"):
                ref = frame[frame.backend.eq(name + suffix)]
                rows = tree.merge(
                    ref, on=["ordinal", "rep"], suffixes=("_tree", "_ref")
                )
                initial = np.median(
                    rows.loc[rows.ordinal.eq(1), "index_build_ns_tree"].to_numpy()
                    - rows.loc[rows.ordinal.eq(1), "index_build_ns_ref"].to_numpy()
                )
                diff = rows.cost_tree - rows.cost_ref
                med = diff.groupby(rows.ordinal).median().sort_index()
                paid_prefix = [h for h in med.index if med.loc[h:].max() <= 0]
                end = rows[rows.ordinal.eq(rows.ordinal.max())]
                summaries.append(
                    dict(
                        dataset=case,
                        requests=len(med),
                        replicates=5,
                        method="tree_direct" + suffix,
                        reference=name + suffix,
                        paired_build_premium_ms=initial / 1e6,
                        sustained_paid_lead=(paid_prefix[0] if paid_prefix else ""),
                        endpoint_tree_median_ms=end.cost_tree.median() / 1e6,
                        endpoint_reference_median_ms=end.cost_ref.median() / 1e6,
                        endpoint_paired_q25_ms=np.quantile(
                            end.cost_tree - end.cost_ref, 0.25
                        )
                        / 1e6,
                        endpoint_paired_median_ms=np.median(
                            end.cost_tree - end.cost_ref
                        )
                        / 1e6,
                        endpoint_paired_q75_ms=np.quantile(
                            end.cost_tree - end.cost_ref, 0.75
                        )
                        / 1e6,
                        wins=int((end.cost_tree <= end.cost_ref).sum()),
                    )
                )
    timings["matched/paired_summary.tsv"] = (
        pd.DataFrame(summaries)
        .to_csv(sep="\t", index=False, lineterminator="\n")
        .encode()
    )
    for case, folder, filename in [
        ("fcc", grouped, "grouped.tsv"),
        ("scoped_sqlshare", scoped, "scoped.tsv"),
    ]:
        for name in ("evidence.json", filename):
            timings[f"{case}/{name}"] = (folder / name).read_bytes()
    old_layout = grouped.parent / "fcc-client-layout" / "grouped.tsv"
    if old_layout.exists():
        timings["fcc/earlier_client_layout.tsv"] = old_layout.read_bytes()
    old_scope = scoped.parent / "scoped-client-layout" / "scoped.tsv"
    if old_scope.exists():
        timings["scoped_sqlshare/earlier_client_layout.tsv"] = old_scope.read_bytes()
    sums = {name: hashlib.sha256(data).hexdigest() for name, data in timings.items()}
    timings["SHA256.json"] = json.dumps(sums, sort_keys=True).encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, data in sorted(timings.items()):
            z.writestr(
                zipfile.ZipInfo(name),
                data,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=8,
            )
    with zipfile.ZipFile(path) as z:
        for name, checksum in sums.items():
            if hashlib.sha256(z.read(name)).hexdigest() != checksum:
                raise ValueError(name)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--small", type=Path, default=OUTPUT)
    p.add_argument("--grouped", type=Path, default=REVISION / "fcc")
    p.add_argument("--scoped", type=Path, default=REVISION / "sqlshare_scoped")
    p.add_argument("--out", type=Path, default=PAPER / "matched_results.tex")
    p.add_argument(
        "--package",
        type=Path,
        default=PAPER / "artifact" / "operational" / "matched_timings.zip",
    )
    a = p.parse_args()
    package(a.small, a.grouped, a.scoped, a.package)
    a.out.write_text(report(a.small, a.grouped, a.scoped), encoding="utf8")
