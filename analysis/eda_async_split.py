"""EDA 7: localization recall split by target kind, with async edits counted as unreachable.

Targets per task are the mapped gold nodes (function-like or class-like) plus every library hunk
that fell in an async function (`node_missing`), which has no graph node and so can never be
returned by a graph-based or node-ranking method. Library pool only (sources: gold_nodes.csv,
gold_hunks.csv, localize_tasks.csv).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis import data, style

NAME = "eda_07_async_split"
KS = (1, 5, 10)
METHODS = [
    ("bm25", "BM25", style.PALETTE["blue"]),
    ("bm25_then_graph", "BM25, then graph", style.PALETTE["green"]),
    ("bm25_then_embedding", "BM25, then embedding", style.PALETTE["orange"]),
]
KINDS = [
    ("function_like", "sync\nfunctions"),
    ("class_like", "class\nnodes"),
    ("all", "all targets\n(async counted)"),
]


def prepare(nodes: pd.DataFrame, hunks: pd.DataFrame, loc: pd.DataFrame) -> pd.DataFrame:
    """One row per (task, method, k): found and total targets for each kind."""
    kind = nodes.set_index(["instance_id", "node_id"])["kind"].to_dict()
    async_n = hunks[hunks["status"] == "node_missing"].groupby("instance_id").size().to_dict()
    rows = []
    for r in loc[
        (loc["pool"] == "library") & loc["method"].isin([m for m, _, _ in METHODS])
    ].itertuples():
        gold = [g for g in str(r.gold).split("|") if g]
        top = [t for t in str(r.top).split("|") if t]
        for k in KS:
            hit = set(top[:k])
            row = {"instance_id": r.instance_id, "repo": r.repo, "method": r.method, "k": k}
            for name in ("function_like", "class_like"):
                mine = [g for g in gold if kind.get((r.instance_id, g)) == name]
                row[f"{name}_total"] = len(mine)
                row[f"{name}_found"] = sum(g in hit for g in mine)
            row["async_total"] = int(async_n.get(r.instance_id, 0))
            rows.append(row)
    return pd.DataFrame(rows)


def recall(df: pd.DataFrame, method: str, k: int, which: str) -> tuple[float, int]:
    """Mean per-task recall for a target kind, over tasks that have at least one such target."""
    d = df[(df["method"] == method) & (df["k"] == k)]
    if which == "all":
        tot = d["function_like_total"] + d["class_like_total"] + d["async_total"]
        found = d["function_like_found"] + d["class_like_found"]
    else:
        tot, found = d[f"{which}_total"], d[f"{which}_found"]
    keep = tot > 0
    return (float((found[keep] / tot[keep]).mean()) if keep.any() else float("nan")), int(
        keep.sum()
    )


def numbers(df: pd.DataFrame) -> dict:
    one = df[(df["method"] == "bm25") & (df["k"] == 10)]
    out = {
        "tasks": int(len(one)),
        "tasks_with_async_hunks": int((one["async_total"] > 0).sum()),
        "async_hunks": int(one["async_total"].sum()),
        "sync_function_nodes": int(one["function_like_total"].sum()),
        "class_nodes": int(one["class_like_total"].sum()),
    }
    for m, _, _ in METHODS:
        for which, _ in KINDS:
            val, n = recall(df, m, 10, which)
            out[f"recall@10_{m}_{which}"] = round(val, 3)
            out[f"tasks_{which}"] = n
    return out


def draw(df: pd.DataFrame):
    fig, ax = plt.subplots(
        1, 2, figsize=(style.FIG_WIDTH, 3.6), gridspec_kw={"width_ratios": [3, 2]}
    )
    a = ax[0]
    width = 0.8 / len(METHODS)
    for j, (m, label, color) in enumerate(METHODS):
        vals = [100 * recall(df, m, 10, w)[0] for w, _ in KINDS]
        a.bar(np.arange(len(KINDS)) + j * width, vals, width, color=color, label=label)
    labels = [f"{lab}\n(n={recall(df, 'bm25', 10, w)[1]})" for w, lab in KINDS]
    a.set_xticks(np.arange(len(KINDS)) + width * (len(METHODS) - 1) / 2, labels, fontsize=8)
    a.set(title="Recall@10 by target kind", ylabel="gold targets found (%)", ylim=(0, 60))
    a.legend(fontsize=7, loc="upper right")
    nums = numbers(df)
    b = ax[1]
    parts = [
        ("sync function nodes", nums["sync_function_nodes"], style.PALETTE["blue"]),
        ("class nodes", nums["class_nodes"], style.PALETTE["sky"]),
        ("async hunks (no node)", nums["async_hunks"], style.PALETTE["vermillion"]),
    ]
    b.barh([p[0] for p in parts], [p[1] for p in parts], color=[p[2] for p in parts])
    b.invert_yaxis()
    for i, p in enumerate(parts):
        b.text(p[1], i, f" {p[1]}", va="center", fontsize=8)
    b.set(
        title="Targets in the 116 scored tasks",
        xlabel="count",
        xlim=(0, max(p[1] for p in parts) * 1.2),
    )
    return fig


def build() -> list[Path]:
    nodes = data.load_in("map", "gold_nodes.csv")
    hunks = data.load_in("map", "gold_hunks.csv")
    loc = data.load_in("localize", "localize_tasks.csv")
    df = prepare(nodes, hunks, loc)
    nums = numbers(df)
    total = nums["sync_function_nodes"] + nums["class_nodes"] + nums["async_hunks"]
    caption = (
        f"Of {total} gold targets in {nums['tasks']} tasks, {nums['async_hunks']} hunks in "
        f"{nums['tasks_with_async_hunks']} tasks fall in async functions with no graph node and "
        "cannot be found by any node ranking; BM25 recall@10 is "
        f"{100 * nums['recall@10_bm25_function_like']:.0f}% on sync function nodes and "
        f"{100 * nums['recall@10_bm25_all']:.0f}% over all targets."
    )
    return [
        style.save(
            draw(df),
            NAME,
            ["gold_nodes.csv", "gold_hunks.csv", "localize_tasks.csv"],
            nums,
            caption,
        )
    ]
