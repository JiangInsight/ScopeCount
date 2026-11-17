

import hashlib, io, json, pathlib, re
import numpy as np
import pandas as pd
import requests
from trace_fetch import BASE, write_case

PROJECTS = {
    "press_insurance": (
        "the-markup/investigate-mi-insurance-territories",
        "cf515ea0efbfb9e38d504e036744efb775cfe29a",
        "02_allstate/01-analysis.ipynb",
    ),
    "press_facebook": (
        "BuzzFeedNews/2016-10-facebook-fact-check",
        "339d3e9980140c024d4791c32c231411a4b20660",
        "notebooks/facebook-fact-check.ipynb",
    ),
    "press_ftc": (
        "BuzzFeedNews/2018-09-ftc-analysis",
        "74cfd02c75621df06f1eaf003757103146d2d616",
        "notebooks/2018-09-ftc-analysis.ipynb",
    ),
    "press_icf": (
        "BuzzFeedNews/2022-04-icf-analysis",
        "bac49eb187c36d1f075e126f190ac23539d5980e",
        "notebooks/ownership/nc-ownership-final.ipynb",
    ),
    "agency_providers": (
        "cal-itp/notebooks",
        "8612636f5c64bf187f1f6a32ee7e77da19809fe3",
        "notebooks/stats.ipynb",
    ),
}


def build(key, root=BASE):
    repo, rev, nbpath = PROJECTS[key]
    raw = root / "notebook-sources" / key
    raw.mkdir(parents=True, exist_ok=True)
    evidence = []

    def fetch(path, source=repo, commit=rev):
        url = (
            "https://raw.githubusercontent.com/"
            + source
            + "/"
            + commit
            + "/"
            + requests.utils.quote(path, safe="/")
        )
        local = raw / path.split("/")[-1]
        if not local.exists():
            r = requests.get(url, timeout=90)
            r.raise_for_status()
            local.write_bytes(r.content)
        data = local.read_bytes()
        evidence.append({"url": url, "sha256": hashlib.sha256(data).hexdigest()})
        return data

    nb = json.loads(fetch(nbpath))
    qs = []

    def output(i):
        c = nb["cells"][i]
        assert c["execution_count"] is not None
        return "\n".join(
            "".join(o.get("data", {}).get("text/plain", o.get("text", [])))
            for o in c["outputs"]
        )

    def emit(i, cols, known, expression="missing count"):
        c = nb["cells"][i]
        assert c["cell_type"] == "code"
        vals = [int(df[col].isna().sum()) for col in cols]
        assert vals == known, (key, i, vals, known)
        qs.append(
            dict(
                id=f"cell_{c['execution_count']}",
                notebook_index=i,
                execution_count=c["execution_count"],
                rules=[([col], []) for col in cols],
                published_counts=known,
                expression=expression,
            )
        )

    if key == "press_insurance":
        features = json.loads(fetch("02_allstate/outputs/allstate_auto_clean.geojson"))[
            "features"
        ]
        df = pd.DataFrame.from_records(
            [dict(**f["properties"], geometry=f["geometry"]) for f in features]
        )
        match = re.fullmatch(r"Dropping (\d+) points", output(13).strip())
        emit(13, ["geo_id"], [int(match.group(1))])
    elif key == "press_facebook":
        df = pd.read_csv(io.BytesIO(fetch("data/facebook-fact-check.csv")))
        assert len(df) == int(output(5))
        cols = ["share_count", "reaction_count", "comment_count"]
        vals = [
            int(re.search(r"^" + s + r"\s+(\d+)", output(31), re.M).group(1))
            for s in cols
        ]
        emit(31, cols, vals)
    elif key == "press_icf":
        df = pd.read_excel(
            io.BytesIO(fetch("data/ownership/raw/2021-10-15-nc-icfmr.xlsx")),
            sheet_name="MHL_ExcelWebReport",
            skiprows=6,
        )
        assert len(df) == int(output(6))
        emit(8, ["CCN Number"], [int(output(8))])
    elif key == "press_ftc":
        srcs = ["2006_2015.xlsx", "2015_2017.xls", "2018.xlsx"]
        frames = []
        for i, end in enumerate(srcs):
            b = fetch("data/consumer_compls_redacted_" + end)
            fr = pd.read_excel(
                io.BytesIO(b), sheet_name="CIS Complaint" if i == 0 else 0
            )
            frames.append(fr.assign(source=end.split(".")[0].replace("_", "-")))
        assert [len(x) for x in frames] == [int(x) for x in output(4).split()]
        df = (
            pd.concat(frames, sort=False)
            .reset_index(drop=True)
            .rename(
                columns={
                    "  Created Date": "Created Date",
                    " Reference Number": "Reference Number",
                }
            )
        )
        df["date"] = pd.to_datetime(df["Created Date"], errors="coerce", format="mixed")
        df = df[
            [
                "source",
                "Reference Number",
                "Complaint Info Comments",
                "Created Date",
                "date",
            ]
        ]
        emit(7, ["date"], [int(output(7))])
    else:



        df = pd.read_csv(
            io.BytesIO(
                fetch(
                    "data/providers/providers.csv",
                    "cal-itp/mobility-marketplace",
                    "3fee068b3e3080115fdefc5695800e5de39d5bb5",
                )
            )
        )
        assert len(df) == int(output(4))
        for i, col, pct in [(3, "gtfs", True), (7, "upt_dr", True), (8, "gtfs", False)]:
            val = float(output(i))
            count = round(val * len(df) / 100) if pct else int(val)
            if pct:
                assert abs(count * 100 / len(df) - val) < 1e-10
            emit(
                i,
                [col],
                [count],
                "100 * missing count / table size" if pct else "missing count",
            )
    fields = list(df.columns)
    needed = {a for q in qs for p, n in q["rules"] for a in p + n}
    cols = fields[:63]
    if not needed <= set(cols):
        cols = [c for c in fields if c in needed] + [
            c for c in fields if c not in needed
        ][: 63 - len(needed)]
    masks = np.zeros(len(df), dtype="<u8")
    for i, col in enumerate(cols):
        masks |= df[col].isna().to_numpy(dtype="<u8") << i
    write_case(
        root / "matched" / key,
        cols,
        masks,
        qs,
        dict(
            source="published_executed_notebook",
            name=key,
            sources=evidence,
            nb_path=nbpath,
            repo=repo,
            revision=rev,
            clock="cell execution order; no request timestamp in output",
        ),
    )
    print(
        key,
        len(df),
        len(qs),
        [(q["execution_count"], q["published_counts"]) for q in qs],
        flush=True,
    )


if __name__ == "__main__":
    for key in PROJECTS:
        build(key)
