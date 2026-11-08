"""EDA 5: from one edited node, which candidate set contains the other edited nodes?"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis import data, style

NAME = "eda_05_cochange"
METHODS = [
    ("hop1", "1-hop neighbours", style.PALETTE["blue"]),
    ("hop2", "2-hop neighbours", style.PALETTE["sky"]),
    ("same_class", "same class", style.PALETTE["pink"]),
    ("same_module", "same module", style.PALETTE["green"]),
    ("hop1_or_module", "1-hop or same module", style.PALETTE["orange"]),
    ("embedding10", "embedding top 10", style.PALETTE["vermillion"]),
]


def pooled(s: pd.DataFrame) -> pd.DataFrame:
    return s[s["repo"] == "all repos"].set_index("method")


def numbers(s: pd.DataFrame, t: pd.DataFrame) -> dict:
    p = pooled(s)
    out = {
        "tasks": int(p["tasks"].max()),
        "median_library_nodes_in_graph": float(t["n_pool"].median()),
    }
    for m, _, _ in METHODS:
        out[f"recall_{m}"] = float(p.loc[m, "recall"])
        out[f"precision_{m}"] = float(p.loc[m, "precision"])
        out[f"mean_set_size_{m}"] = float(p.loc[m, "mean_set_size"])
        out[f"median_lift_{m}"] = float(p.loc[m, "median_lift"])
    return out


def draw(s: pd.DataFrame, t: pd.DataFrame):
    p = pooled(s)
    fig, ax = plt.subplots(
        1, 2, figsize=(style.FIG_WIDTH, 3.6), gridspec_kw={"width_ratios": [3, 2]}
    )
    a = ax[0]
    pool = float(t["n_pool"].median())
    xs = np.logspace(0, np.log10(pool), 50)
    a.plot(xs, 100 * xs / pool, color=style.PALETTE["grey"], ls=":", lw=1.2, label="random set")
    for m, label, color in METHODS:
        x, y = p.loc[m, "mean_set_size"], 100 * p.loc[m, "recall"]
        a.scatter([x], [y], s=60, color=color, zorder=3)
        dy = {"embedding10": -11, "hop1": 5}.get(m, -3)
        a.annotate(label, (x, y), xytext=(6, dy), textcoords="offset points", fontsize=7)
    a.set(
        title="Recall against candidate-set size",
        xlabel="mean candidates returned (log)",
        ylabel="other gold nodes found (%)",
        xscale="log",
        ylim=(0, 100),
    )
    a.set_xlim(2, 400)
    a.legend(loc="lower right", fontsize=7)
    b = ax[1]
    names = [label for _, label, _ in METHODS]
    lifts = [p.loc[m, "median_lift"] for m, _, _ in METHODS]
    b.barh(names, lifts, color=[c for _, _, c in METHODS])
    b.invert_yaxis()
    b.set(title="Precision over chance", xlabel="median lift (x random, log)", xscale="log")
    b.set_xlim(1, 100)
    return fig


def build() -> list[Path]:
    s = data.load_in("cochange", "cochange_summary.csv")
    t = data.load_in("cochange", "cochange_tasks.csv")
    nums = numbers(s, t)
    caption = (
        f"Across {nums['tasks']} multi-node tasks, 1-hop graph neighbours "
        f"({nums['mean_set_size_hop1']:.0f} nodes) hold "
        f"{100 * nums['recall_hop1']:.0f}% of the other "
        f"edited nodes, the whole module {100 * nums['recall_same_module']:.0f}%; "
        f"embedding neighbours {100 * nums['recall_embedding10']:.0f}%."
    )
    return [
        style.save(draw(s, t), NAME, ["cochange_summary.csv", "cochange_tasks.csv"], nums, caption)
    ]
