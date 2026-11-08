"""EDA 4: can the issue text, graph and embeddings find the gold node? (localize_summary.csv)"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis import data, style

NAME = "eda_04_localization"
METHODS = [
    ("bm25", "BM25", style.PALETTE["blue"]),
    ("bm25_then_graph", "BM25 then graph neighbours", style.PALETTE["green"]),
    ("bm25_then_embedding", "BM25 then embedding neighbours", style.PALETTE["orange"]),
    ("bm25_graph", "BM25 boosted by graph", style.PALETTE["sky"]),
    ("bm25_embedding", "BM25 boosted by embedding", style.PALETTE["vermillion"]),
]
KS = [1, 5, 10]


def cell(s: pd.DataFrame, repo: str, pool: str, method: str, col: str) -> float:
    row = s[(s["repo"] == repo) & (s["pool"] == pool) & (s["method"] == method)]
    return float(row[col].iloc[0]) if len(row) else float("nan")


def numbers(s: pd.DataFrame) -> dict:
    out = {"tasks": int(s[(s["repo"] == "all repos") & (s["method"] == "bm25")]["tasks"].max())}
    for pool in ("library", "all"):
        for m, _, _ in METHODS:
            out[f"hit@10_{pool}_{m}"] = round(cell(s, "all repos", pool, m, "hit@10"), 3)
        out[f"random_hit@10_{pool}"] = round(cell(s, "all repos", pool, "random", "hit@10"), 3)
    return out


def draw(s: pd.DataFrame):
    fig, ax = plt.subplot_mosaic("AB;CC", figsize=(style.FIG_WIDTH, 6.4))
    width = 0.8 / len(METHODS)
    for key, pool, title in (
        ("A", "library", "Library nodes only"),
        ("B", "all", "All graph nodes"),
    ):
        a = ax[key]
        for j, (m, label, color) in enumerate(METHODS):
            vals = [100 * cell(s, "all repos", pool, m, f"recall@{k}") for k in KS]
            a.bar(np.arange(len(KS)) + j * width, vals, width, color=color, label=label)
        a.set_xticks(np.arange(len(KS)) + width * (len(METHODS) - 1) / 2, [f"@{k}" for k in KS])
        a.set(title=title, ylabel="recall of gold nodes (%)", xlabel="nodes returned")
        a.set_ylim(0, 50)
    handles, labels = ax["A"].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=7, loc="outside lower center", ncol=3)
    c = ax["C"]
    repos = [r for r in style.REPO_ORDER if r in set(s["repo"]) and r != "encode/httpx"]
    width = 0.8 / len(METHODS)
    for j, (m, _label, color) in enumerate(METHODS):
        vals = [100 * cell(s, r, "library", m, "hit@10") for r in repos]
        c.bar(np.arange(len(repos)) + j * width, vals, width, color=color)
    n = [
        int(
            s[(s["repo"] == r) & (s["method"] == "bm25") & (s["pool"] == "library")]["tasks"].iloc[
                0
            ]
        )
        for r in repos
    ]
    c.set_xticks(
        np.arange(len(repos)) + width * (len(METHODS) - 1) / 2,
        [f"{style.short(r)} (n={k})" for r, k in zip(repos, n, strict=True)],
    )
    c.set(
        title="Tasks with a gold node in the top 10 (library nodes; httpx has 1 task, omitted)",
        ylabel="% of tasks",
        ylim=(0, 100),
    )
    return fig


def build() -> list[Path]:
    s = data.load_in("localize", "localize_summary.csv")
    nums = numbers(s)
    caption = (
        f"BM25 on the issue text puts a gold node in the top 10 for "
        f"{100 * nums['hit@10_library_bm25']:.0f}% "
        f"of {nums['tasks']} tasks (library nodes). Adding graph neighbours "
        f"({100 * nums['hit@10_library_bm25_then_graph']:.0f}%) or embedding neighbours "
        f"({100 * nums['hit@10_library_bm25_then_embedding']:.0f}%) does not help; "
        "random finds none."
    )
    return [style.save(draw(s), NAME, ["localize_summary.csv"], nums, caption)]
