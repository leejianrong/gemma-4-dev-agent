"""EDA 2: anatomy of the gold patches (sources: tasks.csv, hunks.csv).

"Library" means a .py file outside docs_src/, docs/, scripts/, tests/, test/ and examples/.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis import data, style

NAME = "eda_02_patch_anatomy"
KINDS = ["library only", "library + other python", "no library code"]
KIND_COLORS = [style.PALETTE["blue"], style.PALETTE["sky"], style.PALETTE["vermillion"]]
BUCKETS = ["1", "2", "3", "4-5", "6+"]


def prepare(tasks: pd.DataFrame, hunks: pd.DataFrame) -> pd.DataFrame:
    lib = (
        hunks[hunks["is_library"] == 1]
        .groupby("instance_id")
        .agg(
            lib_added=("n_added", "sum"),
            lib_removed=("n_removed", "sum"),
            lib_hunks=("n_added", "size"),
        )
    )
    other = hunks[hunks["is_library"] == 0].groupby("instance_id").size().rename("other_hunks")
    t = tasks.join(lib, on="instance_id").join(other, on="instance_id")
    for col in ("lib_added", "lib_removed", "lib_hunks", "other_hunks"):
        t[col] = t[col].fillna(0).astype(int)
    t["lib_lines"] = t["lib_added"] + t["lib_removed"]
    t["kind"] = np.select(
        [t["lib_hunks"] == 0, t["other_hunks"] > 0], [KINDS[2], KINDS[1]], default=KINDS[0]
    )
    t["files_bucket"] = pd.cut(
        t["patch_files"], bins=[0, 1, 2, 3, 5, 10**9], labels=BUCKETS
    ).astype(str)
    return t


def numbers(t: pd.DataFrame, hunks: pd.DataFrame) -> dict:
    lib = t[t["lib_lines"] > 0]
    return {
        "tasks": len(t),
        "tasks_with_library_changes": len(lib),
        "tasks_without_library_code": int((t["kind"] == KINDS[2]).sum()),
        "tasks_library_plus_other": int((t["kind"] == KINDS[1]).sum()),
        "median_library_lines_changed": float(lib["lib_lines"].median()),
        "p90_library_lines_changed": float(lib["lib_lines"].quantile(0.9)),
        "max_library_lines_changed": int(lib["lib_lines"].max()),
        "median_library_lines_per_repo": {
            style.short(r): float(g["lib_lines"].median()) for r, g in lib.groupby("repo")
        },
        "single_file_patches": int((t["patch_files"] == 1).sum()),
        "pure_addition_tasks": int(((t["lib_lines"] > 0) & (t["lib_removed"] == 0)).sum()),
        "tasks_with_a_new_file": int((t["patch_new_files"] > 0).sum()),
        "non_python_hunks": int((hunks["is_python"] == 0).sum()),
        "hunks": len(hunks),
    }


def draw(t: pd.DataFrame):
    repos = [r for r in style.REPO_ORDER if r in set(t["repo"])]
    lib = t[t["lib_lines"] > 0]
    fig, ax = plt.subplots(2, 2, figsize=(style.FIG_WIDTH, 5.8))

    a = ax[0, 0]  # library lines changed, ECDF
    for r in repos:
        v = np.sort(lib.loc[lib["repo"] == r, "lib_lines"].to_numpy())
        if len(v) > 1:
            med = np.median(v)
            a.step(
                v,
                np.arange(1, len(v) + 1) / len(v),
                where="post",
                color=style.REPO_COLORS[r],
                label=f"{style.short(r)} (median {med:.0f})",
            )
    a.axvline(lib["lib_lines"].median(), color=style.PALETTE["grey"], ls=":", lw=1)
    a.set(
        title="Library lines changed per patch",
        xlabel="added + removed lines (log)",
        ylabel="share of tasks",
        xscale="log",
    )
    a.legend(loc="lower right", fontsize=8)

    b = ax[0, 1]  # files touched
    width = 0.8 / len(repos)
    for j, r in enumerate(repos):
        sub = t[t["repo"] == r]
        share = [100 * (sub["files_bucket"] == k).mean() for k in BUCKETS]
        b.bar(
            np.arange(len(BUCKETS)) + j * width,
            share,
            width,
            color=style.REPO_COLORS[r],
            label=f"{style.short(r)} (n={len(sub)})",
        )
    b.set_xticks(np.arange(len(BUCKETS)) + width * (len(repos) - 1) / 2, BUCKETS)
    b.set(title="Files touched per patch", xlabel="files", ylabel="% of tasks")
    b.set_ylim(0, 135)  # headroom for the legend; the single httpx task is a 100% bar
    b.set_yticks(range(0, 101, 20))
    b.legend(fontsize=7, loc="upper center", ncol=2)

    c = ax[1, 0]  # where the edits land
    left = np.zeros(len(repos))
    for kind, color in zip(KINDS, KIND_COLORS, strict=True):
        share = np.array([100 * (t.loc[t["repo"] == r, "kind"] == kind).mean() for r in repos])
        c.barh([style.short(r) for r in repos], share, left=left, color=color, label=kind)
        left += share
    c.invert_yaxis()
    c.set(title="Where the edits land", xlabel="% of tasks")
    c.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3)
    c.set_xlim(0, 100)

    d = ax[1, 1]  # added vs removed
    for r in repos:
        s = lib[lib["repo"] == r]
        d.scatter(
            s["lib_removed"],
            s["lib_added"],
            s=14,
            alpha=0.7,
            color=style.REPO_COLORS[r],
            linewidths=0,
        )
    top = max(lib["lib_added"].max(), lib["lib_removed"].max(), 10)
    d.plot([0, top], [0, top], color=style.PALETTE["grey"], ls=":", lw=1)
    d.set(
        title="Added vs removed library lines",
        xlabel="removed lines",
        ylabel="added lines",
        xscale="symlog",
        yscale="symlog",
    )
    pure = int((lib["lib_removed"] == 0).sum())
    d.text(
        0.04,
        0.95,
        f"{pure} pure additions\n(on the left edge)",
        transform=d.transAxes,
        va="top",
        fontsize=8,
        color=style.PALETTE["grey"],
    )
    return fig


def build() -> list[Path]:
    tasks, hunks = data.load("tasks.csv"), data.load("hunks.csv")
    t = prepare(tasks, hunks)
    nums = numbers(t, hunks)
    caption = (
        "Gold patches are small: the median patch changes "
        f"{nums['median_library_lines_changed']:.0f} library lines and "
        f"{nums['single_file_patches']} of {nums['tasks']} touch one file. "
        f"{nums['tasks_without_library_code']} tasks change no library code; "
        f"{nums['pure_addition_tasks']} only add lines; all {nums['hunks']} hunks are Python."
    )
    return [style.save(draw(t), NAME, ["tasks.csv", "hunks.csv"], nums, caption)]
