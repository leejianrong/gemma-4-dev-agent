"""EDA 1: task inventory, repo mix and the issue-text profile (source: tasks.csv)."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis import data, style

NAME = "eda_01_inventory"


def numbers(t: pd.DataFrame) -> dict:
    n = len(t)
    by = t.groupby("repo")
    return {
        "tasks": n,
        "tasks_per_repo": {style.short(r): int(c) for r, c in by.size().items()},
        "median_issue_words": float(t["problem_words"].median()),
        "median_issue_words_per_repo": {
            style.short(r): float(g["problem_words"].median()) for r, g in by
        },
        "issues_with_code_block": int((t["code_blocks"] > 0).sum()),
        "issues_with_url": int((t["urls"] > 0).sum()),
        "issues_with_traceback": int(t["has_traceback"].sum()),
        "tasks_with_hints": int((t["hints_chars"] > 0).sum()),
        "first_created": t["created"].min().strftime("%Y-%m-%d"),
        "last_created": t["created"].max().strftime("%Y-%m-%d"),
        "created_since_2025": int((t["created"] >= pd.Timestamp("2025-01-01", tz="UTC")).sum()),
    }


def draw(t: pd.DataFrame):
    repos = [r for r in style.REPO_ORDER if r in set(t["repo"])]
    fig, ax = plt.subplots(2, 2, figsize=(style.FIG_WIDTH, 5.8))

    a = ax[0, 0]  # tasks per repo
    counts = [int((t["repo"] == r).sum()) for r in repos]
    bars = a.bar(
        [style.short(r) for r in repos], counts, color=[style.REPO_COLORS[r] for r in repos]
    )
    a.bar_label(bars, padding=2)
    a.set(title="Tasks per repository", ylabel="tasks")
    a.set_ylim(0, max(counts) * 1.15)

    b = ax[0, 1]  # timeline
    for i, r in enumerate(repos):
        d = t.loc[t["repo"] == r, "created"]
        b.scatter(d, np.full(len(d), i), s=14, alpha=0.65, color=style.REPO_COLORS[r], linewidths=0)
    b.set_yticks(range(len(repos)), [style.short(r) for r in repos])
    b.set(title="When each issue was opened")
    b.grid(axis="y", visible=False)
    b.tick_params(axis="x", rotation=30)

    c = ax[1, 0]  # issue length ECDF
    for r in repos:
        w = np.sort(t.loc[t["repo"] == r, "problem_words"].to_numpy())
        if len(w) > 1:
            c.step(
                w,
                np.arange(1, len(w) + 1) / len(w),
                where="post",
                color=style.REPO_COLORS[r],
                label=f"{style.short(r)} (n={len(w)})",
            )
    c.axvline(t["problem_words"].median(), color=style.PALETTE["grey"], ls=":", lw=1)
    c.text(
        t["problem_words"].median() * 1.05,
        0.05,
        f"median {t['problem_words'].median():.0f}",
        color=style.PALETTE["grey"],
        fontsize=8,
    )
    c.set(
        title="Issue length",
        xlabel="words in the problem statement",
        ylabel="share of tasks",
        xscale="log",
    )
    c.legend(loc="upper left", fontsize=8)

    d_ = ax[1, 1]  # what issues contain
    feats = [
        ("code block", t["code_blocks"] > 0),
        ("URL", t["urls"] > 0),
        ("traceback", t["has_traceback"] > 0),
        ("hints", t["hints_chars"] > 0),
    ]
    width = 0.8 / len(repos)
    for j, r in enumerate(repos):
        m = t["repo"] == r
        share = [100 * s[m].mean() for _, s in feats]
        d_.bar(
            np.arange(len(feats)) + j * width,
            share,
            width,
            color=style.REPO_COLORS[r],
            label=f"{style.short(r)} (n={int(m.sum())})",
        )
    centres = np.arange(len(feats)) + width * (len(repos) - 1) / 2
    for x, (_, s) in zip(centres, feats, strict=True):
        if not s.any():  # a true zero must not look like missing data
            d_.text(
                x, 3, f"none\n(0 of {len(t)})", ha="center", fontsize=8, color=style.PALETTE["grey"]
            )
    d_.set_xticks(centres, [f for f, _ in feats])
    d_.set(title="What an issue contains", ylabel="% of tasks")
    d_.legend(fontsize=7, loc="upper right")
    return fig


def build() -> list[Path]:
    t = data.load("tasks.csv")
    t["created"] = pd.to_datetime(t["created_at"], utc=True)
    nums = numbers(t)
    caption = (
        f"{nums['tasks']} public tasks from {len(nums['tasks_per_repo'])} repositories, opened "
        f"{nums['first_created']} to {nums['last_created']}. Median issue is "
        f"{nums['median_issue_words']:.0f} words; {nums['issues_with_code_block']} contain a code "
        f"block, {nums['issues_with_traceback']} a traceback, and "
        f"{nums['tasks_with_hints']} have hints."
    )
    return [style.save(draw(t), NAME, ["tasks.csv"], nums, caption)]
