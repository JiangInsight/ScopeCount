

from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read_trials(paths, method, duration):
    result = {}
    for path in sorted(paths):
        frame = pd.read_csv(path, sep="\t")
        matrix = frame.pivot(index="rep", columns=method, values=duration) / 1e6
        assert not matrix.isna().any().any()
        result[path.stem] = matrix
    return result


def summary(cases, target):
    records = []
    for case, matrix in cases.items():
        for op in matrix.columns:
            times = matrix[op]
            ratio = times / matrix[target]
            records.append(
                dict(
                    case=case,
                    method=op,
                    repeats=len(times),
                    median_ms=times.median(),
                    p25_ms=times.quantile(0.25),
                    p75_ms=times.quantile(0.75),
                    p95_ms=times.quantile(0.95),
                    paired_ratio=ratio.median(),
                    target_faster=int((ratio > 1).sum()),
                )
            )
    return records


def report():
    data = HERE / "evidence"
    fcc = read_trials(
        [data / "original.tsv", data / "shuffled.tsv"], "method", "request_ns"
    )
    controls = read_trials((data / "controls").glob("*.tsv"), "op", "time_ns")
    records = summary(fcc, "runs") + summary(controls, "weight")
    pd.DataFrame(records).to_csv(
        data / "summary.tsv", sep="\t", index=False, float_format="%.4f"
    )
    original, shuffled = (fcc[name].median() for name in ("original", "shuffled"))
    text = rf"""\paragraph{{A recorded audit in native order.}}
The FCC notebook reports email presence by bulk uploader. Its input has 10,087,929 rows, 597 uploaders and 872 contiguous key runs. We retained the source order, minimum group size, rounding and output ordering on the encoded uploader and email-validity projection. Each method returned the same eleven reported groups in all {len(fcc["original"])} executions. DuckDB group-by, fused row scatter, scalar run aggregation and the word-run operator took {original.sql:.2f}, {original.rows:.2f}, {original.stream:.2f} and {original.runs:.2f}\,ms, respectively (medians, one thread). The word operator gained {original.stream / original.runs:.2f}$\times$ over scalar run aggregation and {original.sql / original.runs:.2f}$\times$ over SQL. A fixed hash permutation of the same rows gave {shuffled.sql:.2f}, {shuffled.rows:.2f}, {shuffled.stream:.2f} and {shuffled.runs:.2f}\,ms. On that layout the word operator and direct scatter differed by {abs(shuffled.runs - shuffled.rows):.2f}\,ms. Each method started from the same resident table and built its counters within the timed query.
"""
    if controls:
        assert len(controls) == 6
        c = {k: v.median() for k, v in controls.items()}
        t = c["interleaved-few_scores"]
        u = c["interleaved-independent"]
        text += rf"""
\paragraph{{Isolating the score representation.}}
Six controls cross long equal-key runs, six interleaved keys and a random 4,096-key domain with two 16-field distributions on 524,288 rows. One assigns each row one, two or four present cells at random positions. The other samples each field independently. On the interleaved three-score input, literal intersections, holding out the last group, and also allowing binary planes and score atoms took {t.wliteral:.2f}, {t.wmargin:.2f} and {t.weight:.2f}\,ms. With independent fields the corresponding medians were {u.wliteral:.2f}, {u.wmargin:.2f} and {u.weight:.2f}\,ms. For the same two inputs, native grouped counts took {t.sql_counts:.2f} and {u.sql_counts:.2f}\,ms, and a fused row loop took {t.wrows:.2f} and {u.wrows:.2f}\,ms. Every invocation returned all group sizes and score sums, which the driver checked against an independent evaluation of the generated group and score arrays.
"""
    (ROOT / "fused_results.tex").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    report()
