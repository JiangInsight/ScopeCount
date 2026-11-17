

import argparse
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

HERE = Path(__file__).resolve().parent
PAPER = HERE.parents[1]
DATA = HERE / "results"
SETS = [
    "full",
    "boundary",
    "typed",
    "degree",
    "bitmap",
    "typed-bitmap",
    "endpoint",
    "typed-endpoint",
]
NAMES = {
    "sql": "Native SQL",
    "merge": "Two-stream merge",
    "cert": "Footer field counts",
    "score": "Global default",
    "scorelocal": "Local defaults",
    "packed": "Packed row scores",
    "boundary_pos": "Positive exceptions",
    "boundary": "Word dispatch",
    "residual": "Footer residual",
    "dense": "Dense rank",
    "roaring": "CRoaring",
    "endpoint": "Selected prefixes",
    "endpoint_dense": "Dense prefixes",
}


def load(name):
    raw = pd.read_csv(DATA / name / "trials.tsv", sep="\t")
    keys = ["dataset", "rep", "method"]
    assert not raw.duplicated(keys).any()
    if name == "degree":
        assert len(raw) == 375
        return raw
    assert len(raw) == (150 if name.startswith("typed") else 650)
    assert (
        raw.groupby(["dataset", "method"]).slot.value_counts().unstack().nunique(axis=1)
        == 1
    ).all()
    raw = raw[raw.dataset != "fcc"]
    return raw


def med(raw):
    return raw.groupby(["dataset", "method"]).ns.median().unstack() / 1e6


def cluster_interval(m, target):
    by = m.assign(source=[i.rsplit("-", 1)[0] for i in m.index]).groupby("source").sum()
    ids = np.random.default_rng(319).integers(0, len(by), (5000, len(by)))
    return np.quantile(
        by.sql.values[ids].sum(axis=1) / by[target].values[ids].sum(axis=1),
        [0.025, 0.975],
    )


def table_block(raw, methods, target):
    times = med(raw)
    byrep = raw.pivot(index=["dataset", "rep"], columns="method", values="ns")
    rows = []
    for m in methods:
        ratio = times.sql / times[m]
        robust = (byrep[m] < byrep.sql).groupby(level="dataset").all().sum()
        wins = (ratio > 1).sum()
        comparison = "Reference" if m == target else f"{wins}/{robust}"
        rows.append(
            rf"{NAMES[m]} & {times[m].sum()/1000:.2f} & {ratio.median():.2f} & {comparison} \\"
        )
    return "\n".join(rows)


def plot(raw):
    d = med(raw)
    resident = pd.read_csv(PAPER / "artifact/livegroups/results/panels.csv")
    resident.index = resident.dataset + "-" + resident.dim
    d = d.join((resident.sql_count_ms / resident.scope_weight_ms).rename("resident"))
    d = d.sort_values("resident")
    x = np.arange(len(d))
    fig, ax = plt.subplots(figsize=(7, 2.46), layout="constrained")
    ax.axhline(1, ls="--", lw=0.8, c=".35")
    ax.vlines(
        x,
        np.minimum(d.resident, d.sql / d.endpoint),
        np.maximum(d.resident, d.sql / d.endpoint),
        color="#b4babf",
        lw=1,
    )
    ax.scatter(
        x,
        d.resident,
        marker="o",
        facecolors="white",
        edgecolors="#29465d",
        s=21,
        label="Resident word cover",
    )
    ax.scatter(
        x,
        d.sql / d.endpoint,
        marker="^",
        color="#b63e30",
        s=23,
        label="File prefix operator",
    )
    tick_names = [
        n.replace("_statewide", "")
        .replace("ca_los_angeles", "Los Angeles")
        .replace("ca_bakersfield", "Bakersfield")
        .replace("mn_saint_paul", "Saint Paul")
        .split("-")
        for n in d.index
    ]
    ax.set_xticks(
        x,
        [
            (n[0].upper() if len(n[0]) == 2 else " ".join(part.upper() if len(part) == 2 else part.title() for part in n[0].split("_")))
            + (" h" if n[1] == "hour" else " w")
            for n in tick_names
        ],
        rotation=52,
        ha="right",
        fontsize=8,
    )
    ax.set_yscale("log", base=2)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    ax.set_ylabel("SQL time / operator time", fontsize=9)
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(axis="y", alpha=0.18)
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="lower center", bbox_to_anchor=(0.5, 1.0), borderaxespad=0.1)
    fig.savefig(
        PAPER / "figures" / "grouped_speed.pdf",
        metadata={"CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def report():
    raw = {s: load(s) for s in SETS}
    tables = {s: med(f) for s, f in raw.items() if s != "degree"}
    f, b, idx, e = (tables[k] for k in ("full", "boundary", "bitmap", "endpoint"))
    tex = r"""\subsection{Reading the encoded input}
Table~\ref{tab:file} compares complete file-to-answer queries on the 25 traffic-stop workloads. Each block is a separate balanced experiment. For each query we divide the median SQL time by the median plan time in that block. The last column gives the counts of queries with a lower median than SQL and with a win in every round. We retain the block boundaries because the same SQL can run at different speeds in different sessions.
\begin{table}[t]\centering\small
\caption{File-to-answer cost on 25 published audits.}\label{tab:file}
\begin{tabular}{lrrr}\toprule
Plan & Total (s) & Median ratio & Wins/all five\\\midrule
"""
    for title, series, methods in [
        ("Encoded runs", "full", ["sql", "cert", "merge", "score", "scorelocal"]),
        (
            "Packed validity",
            "boundary",
            ["sql", "merge", "packed", "boundary_pos", "boundary"],
        ),
        (
            "Bitmaps and margins",
            "bitmap",
            ["sql", "dense", "roaring", "boundary", "residual"],
        ),
        (
            "Score prefixes",
            "endpoint",
            ["sql", "dense", "boundary", "endpoint_dense", "endpoint"],
        ),
    ]:
        tex += (
            r"\multicolumn{4}{l}{\emph{"
            + title
            + r"}}\\"
            + "\n"
            + table_block(raw[series], methods, "sql")
            + "\n"
            + r"\midrule"
            + "\n"
        )
    tex = (
        tex.rstrip().removesuffix(r"\midrule") + r"""\bottomrule\end{tabular}\end{table}
"""
    )
    ci = cluster_interval(e, "endpoint")
    ep = e.sql / e.endpoint
    tex += rf"""
The conventional run merge takes {f['merge'].sum()/1000:.2f} seconds. Choosing a score default for every group and recovering one residual takes {f.scorelocal.sum()/1000:.2f} seconds in the same experiment. The run-fragment objective saves accumulator updates, but pricing and locating them costs time. Keeping level literals packed changes the scale of the comparison. Word dispatch takes {b.boundary.sum()/1000:.2f} seconds against {b.sql.sum()/1000:.2f} seconds for SQL and {b['merge'].sum()/1000:.2f} seconds for the merge. Always forming packed byte scores takes {b.packed.sum()/1000:.2f} seconds. Enabling negative exceptions changes the total by {abs(b.boundary.sum()-b.boundary_pos.sum())/1000:.2f} seconds. The ablations therefore attribute the main reduction to retaining packed level words and evaluating several fields within the same physical traversal of the grouping keys.

The bitmap control uses dense rank at the ends of key runs. CRoaring~\cite{{roaringimpl}} builds run-optimized key sets and the smaller polarity of each predicate, then uses intersection cardinality. Both use the packed level reader, footer simplification and the same result interface. Temporary indexes live for one Parquet row group and are charged on each call. Over all queries their totals are {idx.dense.sum()/1000:.2f} and {idx.roaring.sum()/1000:.2f} seconds. The word and residual alternatives take {idx.boundary.sum()/1000:.2f} and {idx.residual.sum()/1000:.2f} seconds. When adjacent positions alternate between groups, even the largest group can have very few words exclusively to itself.

Figure~\ref{{fig:workloads}} compares the two input boundaries for weekly (w) and hourly (h) audits. The file prefix operator takes {e.endpoint.sum()/1000:.2f} seconds against {e.sql.sum()/1000:.2f} for SQL, a ratio of {e.sql.sum()/e.endpoint.sum():.2f} for the sum of medians. Resampling the 19 source jurisdictions with both queries kept together gives a 95\% bootstrap interval of {ci[0]:.2f}--{ci[1]:.2f} for this ratio. This interval describes sensitivity to the observed mixture of sources. The operator leads SQL on {int((ep>1).sum())} of 25 queries and dense rank on {int((e.dense>e.endpoint).sum())}. Always forming local prefixes takes {e.endpoint_dense.sum()/1000:.2f} seconds against {e.endpoint.sum()/1000:.2f} for evaluation at the selected cuts. The most expensive queries and the query count both matter when assessing these plans.
\begin{{figure*}}[t]\centering\includegraphics[width=\textwidth]{{figures/grouped_speed}}
\caption{{SQL-to-operator time by audit period.}}\label{{fig:workloads}}\end{{figure*}}
"""
    typed = tables["typed-endpoint"]
    deg = raw["degree"].copy()
    deg["paid"] = deg.query_ns + deg.build_ns
    dh = (
        deg.groupby(["table", "method", "rep"])
        .paid.sum()
        .groupby(level=[0, 1])
        .median()
        .unstack()
        / 1e9
    )
    tex += r"""
\paragraph{Retaining original field types.}
Three weekly queries use source values and field types in place of Boolean validity proxies. Both input representations preserve row order, key equality and all missingness decisions. Table~\ref{tab:typed} includes native SQL, dense rank and the prefix operator from their common ten-round comparison. The physical input changes the amount of data read and decompressed, even though the output is fixed. File sizes range from 2.34 to 3.20 MB, compared with 0.12 to 0.58 MB when the same records contain only their two time keys and nullable Boolean fields.
\begin{table}[t]\centering\small
\caption{Original-type file queries in milliseconds.}\label{tab:typed}
\begin{tabular}{lrrrr}\toprule
Source & SQL & Dense rank & Word & Prefix\\\midrule
"""
    for name, label in [
        ("ca_bakersfield-week", "Bakersfield"),
        ("co_aurora-week", "Aurora"),
        ("mn_saint_paul-week", "Saint Paul"),
    ]:
        t = typed.loc[name]
        tex += (
            rf"{label} & {t.sql:.2f} & {t.dense:.2f} & {t.boundary:.2f} & {t.endpoint:.2f} \\"
            + "\n"
        )
    tex += r"\bottomrule\end{tabular}\end{table}" + "\n"
    tex += rf"""
\paragraph{{Charging a score synopsis from file.}}
A separate five-round replay starts from the same normalized files and materializes the reusable degree by SQL. Each source pays for reading its input, writing the degree and two time keys once, then answering its one or two published queries. Summing the medians of these {len(dh)} complete source workloads gives {dh.degree.sum():.2f} seconds. Direct per-field counts take {dh.counts.sum():.2f} seconds and a per-row SQL expression takes {dh.inline.sum():.2f}. We measure the degree as an alternative that an engine could use when more queries arrive. Its construction and subsequent SQL are both part of the reported cost at the published horizon.
"""
    (PAPER / "file_results.tex").write_text(tex, encoding="utf8")
    plot(raw["endpoint"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--freeze", type=Path, help="Directory containing completed page-* campaigns"
    )
    a = p.parse_args()
    if a.freeze:
        for name in SETS:
            dst = DATA / name
            dst.mkdir(parents=True, exist_ok=True)
            for f in (a.freeze / ("page-" + name)).glob("*.tsv"):
                shutil.copyfile(f, dst / f.name)
    report()
