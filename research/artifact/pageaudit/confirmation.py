

import argparse
from pathlib import Path
import shutil
import pandas as pd
from report import DATA, PAPER, cluster_interval, med

CAMPAIGNS = {"confirm": 1300, "typed-states": 200, "cuts": 650, "segments": 650}


def report():
    raw = {}
    for name, n in CAMPAIGNS.items():
        t = pd.read_csv(DATA / name / "trials.tsv", sep="\t")
        assert len(t) == n and not t.duplicated(["dataset", "method", "rep"]).any()
        slots = t.groupby(["dataset", "method", "slot"]).size().unstack()
        assert slots.notna().all().all() and (slots.nunique(axis=1) == 1).all()
        raw[name] = t[t.dataset != "fcc"]
    c = med(raw["confirm"])
    m = med(raw["segments"])
    t = med(raw["typed-states"])
    k = med(raw["cuts"])
    trial = raw["confirm"].pivot(
        index=["dataset", "rep"], columns="method", values="ns"
    )
    dut = trial.endpoint
    labels = {
        "sql": "native SQL",
        "dense": "dense rank",
        "roaring": "CRoaring",
        "packed": "packed row scores",
    }
    best = {p: int((c.endpoint < c[p]).sum()) for p in labels}
    allwins = {
        p: int((dut < trial[p]).groupby(level="dataset").all().sum()) for p in labels
    }
    reference = c[list(labels)].min(axis=1)
    typed_reference = t[list(labels)].min(axis=1)
    reference_ci = cluster_interval(c.assign(sql=reference), "endpoint")
    winners = c[list(labels)].idxmin(axis=1).value_counts()
    ca = c.loc["ca_statewide-week"]
    bakersfield = c.loc["ca_bakersfield-week"]
    ci = cluster_interval(c, "endpoint")
    work = pd.read_csv(DATA / "segment_work.csv")
    assert len(work) == 25
    w = work.sum(numeric_only=True)
    s = rf"""\paragraph{{Confirmation against direct bitmap execution.}}
A further ten position-balanced rounds place the prefix operator, both bitmap plans, packed row scores and native SQL in the same experiment. Summing the 25 per-query medians gives {c.endpoint.sum()/1000:.2f} seconds for prefixes, {c.packed.sum()/1000:.2f} for packed row scores, {c.dense.sum()/1000:.2f} for dense rank, {c.roaring.sum()/1000:.2f} for CRoaring and {c.sql.sum()/1000:.2f} for SQL. The corresponding SQL-to-prefix ratio is {c.sql.sum()/c.endpoint.sum():.2f} (source-cluster bootstrap interval {ci[0]:.2f}--{ci[1]:.2f}). Prefixes lead dense rank on {best['dense']} queries by median and on {allwins['dense']} in every round. Against CRoaring those counts are {best['roaring']} and {allwins['roaring']}; against SQL they are {best['sql']} and {allwins['sql']}. The median within-query ratio of prefix p95 to median is {(dut.groupby(level=0).quantile(.95)/dut.groupby(level=0).median()).median():.2f}. Several individual dense-rank timings overlap those of the prefix operator even though the medians favor prefixes throughout this confirmation run.

For a stricter comparison, we select the fastest median of the four reference plans separately for each query, with no charge for choosing it. Across the normalized files the resulting total is {reference.sum()/1000:.2f} seconds. Prefixes finish sooner on {int((c.endpoint<reference).sum())} of 25 queries. On the original-value files the corresponding totals are {typed_reference.sum()/1000:.2f} seconds for this reference and {t.endpoint.sum()/1000:.2f} for prefixes, which lead on {int((t.endpoint<typed_reference).sum())} of four. Washington's two queries contribute {((c.dense-c.endpoint)[c.index.str.startswith('wa_statewide')].sum())/1000:.2f} of the {(c.dense-c.endpoint).sum()/1000:.2f} seconds saved against dense rank. The four alternatives are chosen after observing the timings. The fastest reference is dense rank on {winners['dense']} normalized queries, packed scores on {winners['packed']} and SQL on {winners['sql']}. Resampling the 19 source tables together with all their queries gives a 95\% interval of {reference_ci[0]:.2f}--{reference_ci[1]:.2f} for the ratio of the reference total to the prefix total.

Bakersfield's weekly audit is the exception. Native SQL finishes in {bakersfield.sql:.2f} milliseconds and the prefix operator in {bakersfield.endpoint:.2f}. For California statewide, the SQL time is {ca.sql:,.2f} milliseconds, while dense rank and prefixes take {ca.dense:.2f} and {ca.endpoint:.2f}. That query contributes {(ca.sql-ca.endpoint)/1000:.2f} seconds to the gain against SQL but less than one millisecond against dense rank. Which reference wins on a source matters as much as its row count.

\paragraph{{Testing when additional anchors pay.}}
Of {int(w.words):,} input words across the published requests, {int(w.eligible):,} have both a mixed field and two to twelve key runs. On these words one residual group requires {int(w.one):,} probes. Optimal segmentation requires {int(w.segmented):,}, a strict reduction on {int(w.improved):,} words in {int((work.improved>0).sum())} queries. Weighting each probe by the number of active mixed field masks changes the counts from {int(w.literal_one):,} to {int(w.literal_segmented):,}. The complete queries using one-segment and mixed schedules take {m.segment_one.sum()/1000:.2f} and {m.segment.sum()/1000:.2f} seconds over the 25 queries; the accompanying prefix-only control costs {m.endpoint.sum()/1000:.2f}. Plan lookup, reconstruction and arithmetic all count toward these times. Segmentation beats the one-residual schedule on {int((m.segment<m.segment_one).sum())} of 25 query medians, even though its total time is higher. Only {100*w.improved/w.words:.2f}\% of all source words realize it under this cutoff. A separate run forces sparse prefix probes, dense prefix construction, or a switch at four or eight interior cuts. Their totals are {k.endpoint_sparse.sum()/1000:.2f}, {k.endpoint_dense.sum()/1000:.2f}, {k.endpoint.sum()/1000:.2f} and {k.endpoint8.sum()/1000:.2f} seconds to answer all 25 study queries in the common cutoff comparison.

\paragraph{{Original values at state scale.}}
The Ohio and Washington original-value files contain {7225577+11333425:,} of the vehicular records in the normalized study and support four of the same weekly and hourly queries. The files occupy 189.0 and 117.2 MB. Across these four queries, prefixes take {t.endpoint.sum()/1000:.2f} seconds, dense rank {t.dense.sum()/1000:.2f}, CRoaring {t.roaring.sum()/1000:.2f}, packed scores {t.packed.sum()/1000:.2f} and SQL {t.sql.sum()/1000:.2f}. The prefix operator leads SQL on {int((t.endpoint<t.sql).sum())} of four queries and dense rank on {int((t.endpoint<t.dense).sum())}. For Washington by hour the SQL-to-prefix ratio is {t.loc['wa_statewide-hour','sql']/t.loc['wa_statewide-hour','endpoint']:.2f}, compared with {t.loc['oh_statewide-hour','sql']/t.loc['oh_statewide-hour','endpoint']:.2f} for Ohio by hour. The timing starts from each existing file. Preparing those original-value projections took 41 and 63 seconds locally and was common to all file methods.
"""
    controls = pd.read_csv(DATA / "segment_controls.tsv", sep="\t")
    assert len(controls) == 100
    cm = controls.groupby(["layout", "method"]).ns.median().unstack() / 1e6
    known = cm.loc["two_epochs"]
    alternating = cm.loc["interleaved"]
    s += rf"""
A controlled input repeats the theorem's ten-run grouping over 1,048,576 rows and 24 varying fields. Reordering its key fragments preserves their frequencies, lengths and the entire validity matrix. With the two residual groups in separate regions, single-residual and segmented execution take {known.segment_one:.2f} and {known.segment:.2f}\,ms. After interleaving the same key fragments the times are {alternating.segment_one:.2f} and {alternating.segment:.2f}\,ms. These small differences in ten-round medians accompany exact changes in the number of prefix and direct-run measurements used to recover the separate group totals within each arrangement of keys.
"""
    (PAPER / "confirmation.tex").write_text(s, encoding="utf8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path)
    args = parser.parse_args()
    if args.freeze:
        for name in CAMPAIGNS:
            folder = DATA / name
            folder.mkdir(exist_ok=True)
            for path in (args.freeze / ("page-" + name)).glob("*.tsv"):
                shutil.copyfile(path, folder / path.name)
    report()
