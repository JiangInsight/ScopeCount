

from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle
from itertools import groupby

root = Path(__file__).resolve().parents[2]
keys = "AAABBAACCCBB"
scores = np.array([1, 1, 2, 0, 1, 2, 1, 0, 2, 2, 0, 1])
colors = {"A": "#d2e4eb", "B": "#f4debf", "C": "#cfe4d9"}
prefix = np.r_[0, scores.cumsum()]
fig, ax = plt.subplots(figsize=(3.55, 1.42), layout="constrained")
ax.set_xlim(-2.25, 12.5)
ax.set_ylim(-0.9, 2.9)
ax.axis("off")
for y, title in [(2.1, "Key"), (1.12, "Score"), (0.0, "Prefix")]:
    ax.text(-0.52, y, title, ha="right", va="center", fontsize=8)
start = 0
for key, group in groupby(keys):
    n = len(list(group))
    end = start + n
    ax.add_patch(
        Rectangle((start, 1.74), n, 0.72, fc=colors[key], ec="#4a5358", lw=0.65)
    )
    ax.text(start + n / 2, 2.09, key, ha="center", va="center", fontsize=8)
    ax.plot([start, start], [0.25, 1.7], c="#68757b", lw=0.6, ls=":")
    ax.text(start, 0, int(prefix[start]), ha="center", va="center", fontsize=8)
    start = end
ax.plot([start, start], [0.25, 1.7], c="#68757b", lw=0.6, ls=":")
ax.text(start, 0, int(prefix[start]), ha="center", va="center", fontsize=8)
for i, v in enumerate(scores):
    ax.text(i + 0.5, 1.13, str(v), ha="center", va="center", fontsize=8)
ax.text(6, -0.67, "Group totals     A = 7     B = 2     C = 4", ha="center", fontsize=8)
assert {k: int(scores[np.array(list(keys)) == k].sum()) for k in "ABC"} == {
    "A": 7,
    "B": 2,
    "C": 4,
}
fig.savefig(
    root / "figures" / "score_example.pdf",
    bbox_inches="tight",
    pad_inches=0.01,
    metadata={"CreationDate": None, "ModDate": None},
)
