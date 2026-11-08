"""EDA 6: the code graph has no async functions, and what that does to mapping gold edits."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from analysis import data, style

NAME = "eda_06_async_graph"
STATUS = [
    ("mapped", "mapped to a node", style.PALETTE["blue"]),
    ("module_level", "module level (imports, constants)", style.PALETTE["sky"]),
    ("new_file", "new file", style.PALETTE["grey"]),
    ("node_missing", "no node (async function)", style.PALETTE["vermillion"]),
    ("no_changed_code", "no changed code", style.PALETTE["yellow"]),
]


def numbers(rep: dict) -> dict:
    d = rep["defs_in_patched_files"]
    return {
        "async_defs": d["async_defs"],
        "async_with_node": d["async_with_node"],
        "sync_defs": d["sync_defs"],
        "sync_with_node": d["sync_with_node"],
        "hunks_by_status": rep["library_hunk_status"],
        "tasks": rep["tasks"],
        "tasks_with_a_mapped_node": rep["tasks_with_a_mapped_node"],
    }


def draw(rep: dict):
    d = rep["defs_in_patched_files"]
    fig, ax = plt.subplots(
        1, 2, figsize=(style.FIG_WIDTH, 3.4), gridspec_kw={"width_ratios": [2, 3]}
    )
    a = ax[0]
    kinds = ["sync def", "async def"]
    have = [d["sync_with_node"], d["async_with_node"]]
    total = [d["sync_defs"], d["async_defs"]]
    a.bar(kinds, total, color=style.PALETTE["vermillion"], label="no graph node")
    a.bar(kinds, have, color=style.PALETTE["blue"], label="has a graph node")
    for i, (h, t) in enumerate(zip(have, total, strict=True)):
        a.text(i, t, f"{h:,} of {t:,}\n({100 * h / t:.0f}%)", ha="center", va="bottom", fontsize=8)
    a.set(title="Functions in patched files", ylabel="functions", ylim=(0, max(total) * 1.25))
    a.set_xlim(-0.8, 1.8)
    a.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    b = ax[1]
    status = rep["library_hunk_status"]
    rows = [(label, status.get(k, 0), c) for k, label, c in STATUS if status.get(k, 0)]
    b.barh([r[0] for r in rows], [r[1] for r in rows], color=[r[2] for r in rows])
    b.invert_yaxis()
    for i, r in enumerate(rows):
        b.text(r[1], i, f" {r[1]}", va="center", fontsize=8)
    b.set(title="Where gold hunks land", xlabel="hunks", xlim=(0, max(r[1] for r in rows) * 1.15))
    return fig


def build() -> list[Path]:
    rep = data.report_in("map")
    nums = numbers(rep)
    caption = (
        f"None of the {nums['async_defs']} async functions in patched files has a graph node, "
        f"against all {nums['sync_defs']:,} sync ones; "
        f"{nums['hunks_by_status'].get('node_missing', 0)} gold hunks fall in async code."
    )
    return [style.save(draw(rep), NAME, ["map/report.json"], nums, caption)]
