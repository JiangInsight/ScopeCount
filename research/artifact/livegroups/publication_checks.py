

import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from PIL import Image
from scipy import ndimage

from stops import DEFAULT, EDITION, WEEKLY

TABLE = "https://arxiv.org/html/2505.18281v1"
PLOT = (
    "https://raw.githubusercontent.com/saatvikkher/missing-traffic/"
    + EDITION
    + "/figures/F1_dcmr_time_OH.png"
)


def external_bytes(url):
    response = requests.get(url, timeout=90)
    response.raise_for_status()
    return response.content


def all_hourly_panels(cache):
    url = PLOT.replace("F1_dcmr_time_OH.png", "F7_dcmr_time.png")
    png = external_bytes(url)
    im = np.array(Image.open(io.BytesIO(png)).convert("L"))
    assert im.shape == (1500, 2100)
    components, _ = ndimage.label(im < 70)
    centers = []
    for y, x in ndimage.find_objects(components):
        if 10 < x.stop - x.start < 19 and 10 < y.stop - y.start < 19:
            centers.append(((x.start + x.stop - 1) / 2, (y.start + y.stop - 1) / 2))


    panels = [
        ("il_chicago", 1, [0.340, 0.335, 0.330, 0.325]),
        ("md_statewide", 1, [0.2075, 0.2050, 0.2025, 0.2000]),
        ("nj_statewide", 0, [0.38, 0.37, 0.36, 0.35, 0.34]),
        ("oh_statewide", 0, [0.215, 0.210, 0.205, 0.200, 0.195]),
        ("wa_statewide", 0, [0.25, 0.24, 0.23, 0.22]),
        ("wi_statewide", 0, [0.225, 0.220, 0.215, 0.210]),
    ]
    matched = []
    for i, (name, first, ticks) in enumerate(panels):
        yl, yh = [(126, 660), (838, 1372)][i // 3]
        xl, xh = [(196, 733), (878, 1414), (1540, 2078)][i % 3]
        dots = sorted((x, y) for x, y in centers if xl < x < xh and yl < y < yh)
        assert len(dots) == 24 and all(
            20 < d < 23 for d in np.diff([x for x, _ in dots])
        )
        grid = (
            np.where((im[yl:yh, xl + 8 : xh - 8] < 240).sum(1) > xh - xl - 60)[0] + yl
        )
        lines = [
            np.mean(g) for g in np.split(grid, np.flatnonzero(np.diff(grid) > 1) + 1)
        ]
        m, b = np.polyfit(ticks, lines[first::2], 1)
        o = pd.read_csv(cache / "panels" / name / "oracle-hour.csv")
        denom = len((cache / "panels" / name / "fields.txt").read_text().splitlines())
        assert list(o.key) == list(range(24))
        for (x, y), r in zip(dots, o.itertuples()):
            rate = r.missing / r.n / denom
            error = abs(m * rate + b - y)
            assert error < 1.5, (name, r.key, y, error)
            matched.append(
                dict(dataset=name, hour=r.key, rate=rate, x=x, y=y, pixel_error=error)
            )
    return {
        "plot": url,
        "sha256": hashlib.sha256(png).hexdigest(),
        "hourly_points": matched,
        "max_error_px": max(d["pixel_error"] for d in matched),
    }


def verify(cache, out):
    html = external_bytes(TABLE)
    tables = pd.read_html(io.BytesIO(html), flavor="lxml")
    table = next(t for t in tables if len(t) == 88 and "# Rows" in t)
    counts = {
        str(row["Dataset"])
        .replace(",", "")
        .lower()
        .replace(" ", "_"): int(row["# Rows"])
        for _, row in table.iterrows()
    }
    inputs = {}
    for name in WEEKLY:
        meta = json.loads((cache / "panels" / name / "case.json").read_text())
        assert counts[name] == meta["raw_rows"], (name, counts[name], meta["raw_rows"])
        inputs[name] = counts[name]


    png = external_bytes(PLOT)
    im = np.array(Image.open(io.BytesIO(png)).convert("L"))
    assert im.shape == (2400, 2400)
    labels, _ = ndimage.label(im < 70)
    centers = []
    for y, x in ndimage.find_objects(labels):
        if (
            x.start > 280
            and y.start > 150
            and 30 < x.stop - x.start < 60
            and 32 < y.stop - y.start < 60
        ):
            centers.append(((x.start + x.stop - 1) / 2, (y.start + y.stop - 1) / 2))
    centers.sort()
    assert len(centers) == 24 and all(
        82 <= d <= 85 for d in np.diff([x for x, _ in centers])
    )


    bright = np.where((im[:, 450:2300] < 240).sum(axis=1) > 1700)[0]
    lines = np.array(
        [np.mean(g) for g in np.split(bright, np.flatnonzero(np.diff(bright) > 1) + 1)]
    )
    assert len(lines) == 9
    m, b = np.polyfit([0.215, 0.210, 0.205, 0.200, 0.195], lines[::2], 1)
    oracle = pd.read_csv(cache / "panels/oh_statewide/oracle-hour.csv")
    width_plus_one = len(
        (cache / "panels/oh_statewide/fields.txt").read_text().splitlines()
    )
    assert list(oracle.key) == list(range(24))
    rates = oracle.missing / oracle.n / width_plus_one
    measured = np.array([y for _, y in centers])
    predicted = m * rates + b
    errors = np.abs(predicted - measured)
    assert max(errors) < 1.5, dict(
        max_px=max(errors), rates=rates.tolist(), pixel_centers=measured.tolist()
    )
    result = {
        "source_cardinality_table": TABLE,
        "table_raw_row_counts": inputs,
        "ohio_plot": PLOT,
        "plot_sha256": hashlib.sha256(png).hexdigest(),
        "ohio_max_error_px": float(max(errors)),
        "ohio_dcmr": [
            dict(
                hour=int(h),
                rate=float(rate),
                center_y_px=float(y),
                pixel_error=float(e),
            )
            for h, rate, y, e in zip(oracle.key, rates, measured, errors)
        ],
    }
    result["six_hourly_panels"] = all_hourly_panels(cache)
    print(
        "All 144 hourly markers max error",
        result["six_hourly_panels"]["max_error_px"],
        "px",
    )
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(
        len(inputs),
        "published cardinalities;",
        len(measured),
        "plot markers; max error",
        max(errors),
        "px",
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=DEFAULT)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    verify(args.cache, args.out)
