

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, LogLocator

R = Path(__file__).resolve().parents[3]


def plot():
    names = [
        "nhanes",
        "diabetes",
        "scania",
        "storm",
        "crash",
        "survey",
        "taxi",
        "maude",
    ]
    methods = [
        ("tree_direct", "Shared tree", "#156082", "-"),
        ("bitmap_direct", "Prepared bitmap", "#a84f14", "--"),
        ("online_direct", "Online cut", "#71469c", "-."),
        ("sql_opt", "Native SQL", "#48544d", ":"),
    ]
    plt.rcParams.update(
        {"font.family": "DejaVu Sans", "font.size": 8, "pdf.fonttype": 42}
    )
    fig, axs = plt.subplots(
        2, 4, figsize=(7.05, 3.12), sharex=True, layout="constrained"
    )
    for name, ax in zip(names, axs.flat):
        data = pd.read_csv(R / "runs" / "engine" / (name + ".tsv"), sep="\t")
        for method, label, color, style in methods:
            g = data[data.backend == method].sort_values(["rep", "ordinal"])
            q = g.request_ns.to_numpy().reshape(5, -1)
            y = (
                g.groupby("rep").index_build_ns.first().to_numpy()[:, None]
                + np.cumsum(q, axis=1)
            ) / 1e6
            h = np.arange(1, q.shape[1] + 1)
            ax.plot(
                h,
                np.median(y, axis=0),
                color=color,
                linestyle=style,
                linewidth=1.25,
                label=label,
            )
        ax.set_title(
            {"nhanes": "NHANES", "maude": "MAUDE"}.get(name, name.title()),
            pad=2,
            fontsize=8,
        )
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(LogLocator(base=10, numticks=4))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
        ax.set_xscale("log")
        ax.grid(alpha=0.18)
        ax.set_xticks([1, 16, 288], labels=["1", "16", "288"])
        ax.spines[["right", "top"]].set_visible(False)
    for ax in axs[:, 0]:
        ax.set_ylabel("Total time (ms)")
    fig.legend(
        *axs[0, 0].get_legend_handles_labels(),
        loc="outside upper center",
        ncol=4,
        frameon=False,
        columnspacing=1.2
    )
    fig.supxlabel("Number of slice requests on one snapshot", fontsize=8)
    fig.savefig(
        R / "research" / "figures" / "paid_prefix.pdf",
        bbox_inches="tight",
        pad_inches=0.02,
        metadata={"CreationDate": None, "ModDate": None},
    )


if __name__ == "__main__":
    plot()
