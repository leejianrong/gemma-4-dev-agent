"""Writeup card and thumbnail: one panel, big type, readable at small size.

Numbers are the hit@10 rows of A28 (116 tasks, library nodes): BM25 55%, BM25 then graph 54%,
BM25 then embedding 50%, random 0%. Output: figures/writeup/thumbnail.png (16:9, 1280x720).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from analysis import style

OUT = Path("figures/writeup/thumbnail.png")
BARS = [
    ("BM25\n(plain text)", 55, style.PALETTE["blue"]),
    ("BM25 then\ncall graph", 54, style.PALETTE["green"]),
    ("BM25 then\nembeddings", 50, style.PALETTE["orange"]),
    ("Random", 0, style.PALETTE["grey"]),
]


def draw():
    fig, ax = plt.subplots(figsize=(12.8, 7.2), dpi=100, layout=None)
    ax.grid(False)
    ax.bar([b[0] for b in BARS], [b[1] for b in BARS], color=[b[2] for b in BARS], width=0.62)
    for i, b in enumerate(BARS):
        ax.text(i, b[1] + 2.5, f"{b[1]}%", ha="center", fontsize=34, fontweight="bold")
    ax.set_ylim(0, 75)
    ax.set_yticks([])
    ax.tick_params(axis="x", labelsize=22, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    fig.text(0.04, 0.91, "Where does a code graph help a bug-fixing agent?", fontsize=30, ha="left")
    fig.text(
        0.04,
        0.835,
        "Plain text search finds the edit site as well as any graph tool.",
        fontsize=20,
        ha="left",
        color=style.PALETTE["grey"],
    )
    fig.text(
        0.04,
        0.785,
        "Share of tasks with a gold node in the top 10 (116 tasks, 4 Python libraries)",
        fontsize=17,
        ha="left",
        color=style.PALETTE["grey"],
    )
    fig.set_layout_engine("none")
    ax.set_position([0.04, 0.14, 0.93, 0.56])
    return fig


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    draw().savefig(OUT, dpi=100)
    print(OUT)
