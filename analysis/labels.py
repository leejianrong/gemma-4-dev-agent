"""Per-task difficulty and leakage labels for all public tasks (GEM-21).

`python -m analysis.labels` writes data/labels/task_labels.csv and docs/TASK_LABELS.md. The
definitions table below is the single source for both the doc and the column check in the tests, so
a label cannot exist without its one-line definition. Inputs: tasks.csv (EDA kernel), gold_hunks.csv
and gold_nodes.csv (mapping kernel, exact), localize_tasks.csv (localization kernel).
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import data

DEFINITIONS: list[tuple[str, str]] = [
    ("instance_id", "Task id."),
    ("repo", "Repository the task comes from."),
    ("lib_files", "Library Python files in the gold patch (not docs, tests, scripts or examples)."),
    ("lib_hunks", "Library hunks in the gold patch."),
    ("lib_lines", "Library lines added plus removed by the gold patch."),
    ("new_file_hunks", "Library hunks that create a new file."),
    (
        "module_level_hunks",
        "Library hunks outside any function or class (imports, constants).",
    ),
    ("async_hunks", "Library hunks inside an async function, which has no graph node."),
    ("gold_nodes", "Graph nodes edited by the gold patch (exact line-number mapping)."),
    ("gold_class_nodes", "Edited nodes that are classes rather than functions."),
    (
        "size_tier",
        "lib_lines bucket: none 0, tiny to 5, small to 15, medium to 50, else large.",
    ),
    (
        "difficulty",
        "easy: at most 1 gold node and 15 lib lines; hard: 4+ gold nodes or over 50 lib lines; "
        "medium otherwise; no_library_code when the patch edits no library file.",
    ),
    ("issue_words", "Words in the issue text."),
    ("has_traceback", "1 when the issue contains a Python traceback."),
    ("code_blocks", "Fenced code blocks in the issue."),
    (
        "names_symbol",
        "1 when the issue names a function or class the gold patch edits (leakage).",
    ),
    (
        "names_module",
        "1 when the issue names a module the gold patch edits (leakage).",
    ),
    ("graph_nodes", "Nodes in the task's code graph (blank when the task has no gold node)."),
    ("gold_max_degree", "Highest in plus out degree among the gold nodes in the call graph."),
    ("gold_median_degree", "Median in plus out degree of the gold nodes."),
    (
        "bm25_best_rank",
        "Rank of the first gold node when BM25 ranks library nodes (blank: no gold node).",
    ),
    ("test_funcs_added", "Test functions added by the hidden test patch."),
    ("test_lines_added", "Lines added by the hidden test patch."),
]
COLUMNS = [c for c, _ in DEFINITIONS]
TIERS = [(0, "none"), (5, "tiny"), (15, "small"), (50, "medium")]


def size_tier(lines: int) -> str:
    for cap, name in TIERS:
        if lines <= cap:
            return name
    return "large"


def difficulty(lib_lines: int, nodes: int, lib_hunks: int) -> str:
    if lib_hunks == 0:
        return "no_library_code"
    if nodes >= 4 or lib_lines > 50:
        return "hard"
    if nodes <= 1 and lib_lines <= 15:
        return "easy"
    return "medium"


def build(
    tasks: pd.DataFrame, hunks: pd.DataFrame, nodes: pd.DataFrame, loc: pd.DataFrame
) -> pd.DataFrame:
    lib = hunks[hunks["status"] != "non_library"]
    h = lib.groupby("instance_id").agg(
        lib_hunks=("status", "size"),
        lib_lines=("n_added", lambda s: 0),  # filled below
    )
    h["lib_lines"] = (
        lib.assign(t=lib["n_added"] + lib["n_removed"]).groupby("instance_id")["t"].sum()
    )
    for col, status in (
        ("new_file_hunks", "new_file"),
        ("module_level_hunks", "module_level"),
        ("async_hunks", "node_missing"),
    ):
        h[col] = lib[lib["status"] == status].groupby("instance_id").size()
    n = (
        nodes.assign(deg=nodes["in_degree"] + nodes["out_degree"])
        if "in_degree" in nodes
        else nodes.assign(deg=np.nan)
    )
    g = n.groupby("instance_id").agg(
        gold_nodes=("node_id", "size"),
        gold_max_degree=("deg", "max"),
        gold_median_degree=("deg", "median"),
    )
    g["gold_class_nodes"] = n[n["kind"] == "class_like"].groupby("instance_id").size()
    ranks = (
        loc[(loc["pool"] == "library") & (loc["method"] == "bm25")]
        .set_index("instance_id")["best_rank"]
        .rename("bm25_best_rank")
    )
    t = tasks.set_index("instance_id")
    out = (
        t[
            [
                "repo",
                "patch_lib_files",
                "problem_words",
                "has_traceback",
                "code_blocks",
                "issue_mentions_hunk_symbol",
                "issue_mentions_patch_module",
                "test_funcs_added",
                "test_lines_added",
            ]
        ]
        .rename(
            columns={
                "patch_lib_files": "lib_files",
                "problem_words": "issue_words",
                "issue_mentions_hunk_symbol": "names_symbol",
                "issue_mentions_patch_module": "names_module",
            }
        )
        .join(h)
        .join(g)
        .join(ranks)
    )
    if "graph_nodes" in nodes:
        out = out.join(nodes.groupby("instance_id")["graph_nodes"].first())
    else:
        out["graph_nodes"] = np.nan
    for col in (
        "lib_hunks",
        "lib_lines",
        "new_file_hunks",
        "module_level_hunks",
        "async_hunks",
        "gold_nodes",
        "gold_class_nodes",
    ):
        out[col] = out[col].fillna(0).astype(int)
    out["size_tier"] = out["lib_lines"].map(size_tier)
    out["difficulty"] = [
        difficulty(a, b, c)
        for a, b, c in zip(out["lib_lines"], out["gold_nodes"], out["lib_hunks"], strict=True)
    ]
    out = out.reset_index()
    return out[COLUMNS]


def definitions_markdown() -> str:
    lines = [
        "# Task labels",
        "",
        "One row per public task in `task_labels.csv`. Generated by "
        "`python -m analysis.labels`; do not edit by hand.",
        "",
        "| Label | Definition |",
        "|---|---|",
    ]
    lines += [f"| `{c}` | {d} |" for c, d in DEFINITIONS]
    return "\n".join(lines) + "\n"


def main() -> int:
    tasks = data.load("tasks.csv")
    hunks = data.load_in("map", "gold_hunks.csv")
    nodes = data.load_in("map", "gold_nodes.csv")
    loc = data.load_in("localize", "localize_tasks.csv")
    df = build(tasks, hunks, nodes, loc)
    out = Path(os.environ.get("LABELS_DIR", "data/labels"))
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "task_labels.csv", index=False)
    Path("docs/TASK_LABELS.md").write_text(definitions_markdown(), encoding="utf-8")
    print(f"wrote {out / 'task_labels.csv'} ({len(df)} tasks) and docs/TASK_LABELS.md")
    print(df["difficulty"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
