"""Localization benchmark page (GEM-64): recall@k per method, and a per-task ranked list."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path

import indah

from dashboards.data import RunData, table

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "localize"
KS = (1, 5, 10)
METHOD_COLUMNS = [
    "method",
    "tasks",
    "recall@1",
    "recall@5",
    "recall@10",
    "hit@10 %",
    "median best rank",
]
RANK_COLUMNS = ["rank", "node", "gold"]
LABELS = {
    "random": "random",
    "bm25": "BM25",
    "bm25_then_graph": "BM25, then graph neighbours",
    "bm25_then_embedding": "BM25, then embedding neighbours",
    "bm25_graph": "BM25 boosted by graph",
    "bm25_embedding": "BM25 boosted by embedding",
}


@dataclass
class Localization:
    summary: list[dict]
    tasks: list[dict]
    is_fixture: bool


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load(root: Path | None = None) -> Localization:
    root = Path(os.environ.get("LOCALIZE_DIR", "data/localize")) if root is None else root
    ok = (root / "localize_summary.csv").is_file() and (root / "localize_tasks.csv").is_file()
    base = root if ok else FIXTURES
    tasks = _read(base / "localize_tasks.csv")
    if tasks and "top" not in tasks[0]:  # an older kernel output without ranked lists
        for t in tasks:
            t["top"], t["gold"] = "", ""
    return Localization(_read(base / "localize_summary.csv"), tasks, not ok)


def repos(loc: Localization) -> list[str]:
    return sorted({r["repo"] for r in loc.summary}, key=lambda r: (r != "all repos", r))


def method_rows(loc: Localization, repo: str, pool: str) -> list[dict]:
    """One row per method for the repo and pool, in the table's column order."""
    out = []
    for r in loc.summary:
        if r["repo"] == repo and r["pool"] == pool:
            row = {"method": LABELS.get(r["method"], r["method"]), "tasks": int(r["tasks"])}
            for k in KS:
                row[f"recall@{k}"] = round(100 * float(r[f"recall@{k}"]), 1)
            row["hit@10 %"] = round(100 * float(r["hit@10"]), 1)
            row["median best rank"] = r["median_best_rank"]
            out.append((list(LABELS).index(r["method"]) if r["method"] in LABELS else 99, row))
    return [row for _, row in sorted(out, key=lambda p: p[0])]


def chart_rows(loc: Localization, repo: str, pool: str) -> list[list[float]]:
    """[[k, recall of method 1, recall of method 2, ...], ...] for the line chart."""
    rows = method_rows(loc, repo, pool)
    return [[k, *[r[f"recall@{k}"] for r in rows]] for k in KS]


def task_ids(loc: Localization, repo: str, pool: str) -> list[str]:
    ids = {
        t["instance_id"]
        for t in loc.tasks
        if t["pool"] == pool and (repo == "all repos" or t["repo"] == repo)
    }
    return sorted(ids)


def ranked_rows(loc: Localization, instance: str, pool: str, method: str) -> list[dict]:
    """The method's top-ranked nodes for one task; gold nodes are marked."""
    for t in loc.tasks:
        if t["instance_id"] == instance and t["pool"] == pool and t["method"] == method:
            gold = set(filter(None, t["gold"].split("|")))
            top = [n for n in t["top"].split("|") if n]
            rows = [
                {"rank": i, "node": n, "gold": "GOLD" if n in gold else ""}
                for i, n in enumerate(top, 1)
            ]
            seen = {r["node"] for r in rows}
            rows += [
                {"rank": ">20", "node": g, "gold": "GOLD (not in top 20)"}
                for g in sorted(gold - seen)
            ]
            return rows
    return []


def page(_data: RunData):
    loc = load()
    pool = indah.Signal("library")
    repo = indah.Signal("all repos")
    method = indah.Signal("bm25")
    first = task_ids(loc, "all repos", "library")
    task = indah.Signal(first[0] if first else "")

    def current_task() -> str:
        ids = task_ids(loc, repo.value, pool.value)
        return task.value if task.value in ids else (ids[0] if ids else "")

    banner = (
        "Showing synthetic fixture data. Run `make pull-localize` for the real results."
        if loc.is_fixture
        else "Real results from the gemma-4-localize kernel."
    )
    best = lambda: max(  # noqa: E731
        (r["hit@10 %"] for r in method_rows(loc, repo.value, pool.value)), default=0.0
    )
    methods = sorted(
        {t["method"] for t in loc.tasks}, key=lambda m: list(LABELS).index(m) if m in LABELS else 99
    )
    return indah.Column(
        children=[
            indah.Text(f"# Localization benchmark\n\n{banner}", markdown=True),
            indah.Row(
                children=[
                    indah.Segmented(pool, options=["library", "all"]),
                    indah.Select(repo, options=repos(loc), label="Repo"),
                ]
            ),
            indah.Stat(
                lambda: f"{best():.0f}%", label="best method, tasks with a gold node in the top 10"
            ),
            indah.Chart(
                lambda: chart_rows(loc, repo.value, pool.value),
                series=[
                    LABELS.get(r["method"], r["method"])
                    for r in method_rows(loc, "all repos", "library")
                ],
                title="Recall of gold nodes at k (%)",
                x_label="nodes returned (k)",
            ),
            indah.DataFrame(
                lambda: table(method_rows(loc, repo.value, pool.value), METHOD_COLUMNS),
                label="Methods",
            ),
            indah.Text("## One task", markdown=True),
            indah.Row(
                children=[
                    indah.Select(
                        task,
                        options=lambda: task_ids(loc, repo.value, pool.value),
                        label="Task",
                    ),
                    indah.Select(method, options=methods, label="Method"),
                ]
            ),
            indah.DataFrame(
                lambda: table(
                    ranked_rows(loc, current_task(), pool.value, method.value), RANK_COLUMNS
                ),
                label="Ranked nodes (top 20), gold marked",
            ),
        ]
    )
