

from pathlib import Path
import pandas as pd

here = Path(__file__).resolve()
p = here.parents[3]
root = here.parents[2]
names = ["diabetes", "nhanes", "scania", "storm", "crash", "survey", "taxi", "maude"]


def make():
    rows = []
    for name in names:
        d = pd.read_csv(p / "revision" / "online" / (name + ".out.tsv"), sep="\t")
        assert len(d) == 504 and (d.online_units <= 2 * d.offline_units).all()
        end = d.iloc[-1]
        vals = [
            end[k] / end.offline_units
            for k in [
                "tree_units",
                "eager_units",
                "scalar_threshold_units",
                "online_units",
            ]
        ]
        vals.append((d.online_units / d.offline_units).max())
        rows.append(
            (
                "NHANES"
                if name == "nhanes"
                else ("MAUDE" if name == "maude" else name.title())
            )
            + " & "
            + " & ".join(f"{x:,.2f}" for x in vals)
            + r" \\"
        )
    (root / "revision_control_rows.tex").write_text(
        "\n".join(rows) + r"\bottomrule" + "\n"
    )


if __name__ == "__main__":
    make()
