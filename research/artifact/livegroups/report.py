

from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def report():
    src = HERE / "results"
    raw = pd.read_csv(src / "trials.csv.gz")
    med = raw.groupby(["dataset", "dim", "method"]).ns.median().unstack() / 1e6
    horizon = pd.read_csv(src / "observed_horizons.csv")
    pairs = med.sql_count / med.scope_weight
    q = pairs.quantile([0.1, 0.5, 0.9]).values
    rep = horizon.degree_repeats_vs_weight.dropna()
    wins = (horizon.unindexed_weight_ms < horizon.charged_degree_ms).sum()
    rows = []
    names = {
        "sql_count": "SQL field counts",
        "sql_row": "SQL row expression",
        "scope_rows": "Fused scatter",
        "scope_stream": "Scalar runs",
        "scope_runs": "Word runs",
        "scope_wrows": "Scalar score",
        "scope_wliteral": "Signed literals",
        "scope_wmargin": "Literal + residual",
        "scope_weight": "Full score cover",
        "row_degree": "Stored degree",
    }
    for key, label in names.items():
        p95 = raw[raw.method == key].groupby(["dataset", "dim"]).ns.quantile(0.95) / 1e6
        rows.append(
            rf"{label} & {med[key].sum()/1000:.3f} & {med[key].median():.2f} & {(p95/med[key]).median():.2f} \\"
        )
    s = (
        r"""\begin{table}[t]\centering\small
\caption{Resident execution of 25 temporal audits.}\label{tab:resident}
\begin{tabular}{lrrr}\toprule
Plan & Total (s) & Median (ms) & Tail ratio\\\midrule
"""
        + "\n".join(rows)
        + r"""
\bottomrule\end{tabular}\end{table}
"""
    )
    s += rf"""
Table~\ref{{tab:resident}} gives the sum of the 25 query medians, their median, and the median across queries of the within-query p95-to-median ratio. The full word cover leads native field-count SQL on {int((pairs>1).sum())} of 25 queries. The 10th, 50th and 90th percentiles of SQL time divided by cover time are {q[0]:.2f}, {q[1]:.2f} and {q[2]:.2f}. These ratios compare the same complete answers and capture considerable variation across jurisdictions. Holding out a group reduces the sum from {med.scope_wliteral.sum()/1000:.3f} to {med.scope_wmargin.sum()/1000:.3f} seconds. Constructing additional score representations raises it to {med.scope_weight.sum()/1000:.3f}. The largest part of the observed SQL advantage is already available to the fused word-run operator.

Across the 19 jurisdictions the stored degree needs {horizon.build_ms.sum()/1000:.3f} seconds to construct and {horizon.degree_query_ms.sum()/1000:.3f} seconds to answer the published requests once. Including the build brings its cost to {horizon.charged_degree_ms.sum()/1000:.3f} seconds, compared with {med.scope_weight.sum()/1000:.3f} seconds for the cover. The cover costs less on {wins} of 19 sources over their published one- or two-query workloads. Once built, the degree is the fastest plan in aggregate. On {len(rep)} sources the measured degree query cost per complete workload is below the cover's. Holding both costs fixed, the degree would recover its build after {int(rep.min())}--{int(rep.max())} complete executions on these sources, with median {rep.median():.1f}. The published code supplies no evidence that these extra executions occurred. The other {19-len(rep)} would take longer per execution even with their degree already available.
"""
    (HERE.parents[1] / "resident_table.tex").write_text(s, encoding="utf8")


if __name__ == "__main__":
    report()
