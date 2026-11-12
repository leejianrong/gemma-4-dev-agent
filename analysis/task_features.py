"""GEM: relate each dev task's outcome over several runs to features of the task.

Outcome per task = times resolved over the runs (groups: stable >= 4 of 5, flaky 1 to 3, never 0)
plus the failure class of each failed run (`analysis/failure_classes.py`). Features come from the
gold patch mapping (A24), the issue text, the test patch, the BM25 localizer (A37) and the traces.
`build_rows` reads the local, gitignored data and writes nothing; `aggregate` and `render` reduce
the rows to group tables. Only aggregates leave this module (competition rules 4b): a cell with
fewer than 5 tasks is marked `~` (indicative only).

Usage: make task-features   (prints the tables; FIG_DIR=docs/img writes the figure too)
"""

from __future__ import annotations

import csv
import json
import os
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from analysis.dev_subset import MISSING_DEPS
from analysis.failure_classes import classify_run, gold_library_files
from analysis.trace_review import EDIT_TOOLS, calls

KAGGLE_RUNS = ("a0-r1", "a0-r2", "a2-r1", "a2-r2")
POD_LOG = "dev-a3-r1-pod/job.log"
TASK_LINE = re.compile(r"TASK \d+/\d+ (\S+) status=(\S+) calls=(\d+) t=([\d.]+)s")
MIN_CELL = 5


def group_of(n_resolved: int, n_runs: int = 5) -> str:
    if n_resolved == 0:
        return "never"
    return "stable" if n_resolved >= n_runs - 1 else "flaky"


def gold_features(hunks: list[dict], nodes: list[dict]) -> dict:
    """Shape of the gold patch of one task from its hunk and node rows."""
    lib = [h for h in hunks if h["status"] != "non_library"]
    status = {h["status"] for h in lib}
    return {
        "gold_files": len({h["path"] for h in lib}),
        "gold_hunks": len(lib),
        "gold_lines": sum(int(h["n_removed"] or 0) + int(h["n_added"] or 0) for h in lib),
        "gold_nodes": len(nodes),
        "module_level": "module_level" in status,
        "new_file": "new_file" in status,
        "async_hunk": "node_missing" in status,  # the graph has no node for an async def (A27)
        "docs_only": not lib,
    }


def issue_features(task: dict) -> dict:
    text = task["problem_statement"] or ""
    test_patch = task["test_patch"] or ""
    return {
        "issue_words": len(text.split()),
        "has_code": "```" in text or ">>>" in text,
        "has_traceback": "Traceback (most recent call last)" in text,
        "test_files": len(re.findall(r"^\+\+\+ b/", test_patch, re.MULTILINE)),
        "test_lines": sum(
            1 for ln in test_patch.splitlines() if ln.startswith("+") and not ln.startswith("+++")
        ),
        "missing_deps": bool(MISSING_DEPS.search(test_patch)),
        "year": (task.get("created_at") or "")[:4],
    }


def names_gold(text: str, node_ids: list[str], paths: set[str]) -> bool:
    """The issue names a gold symbol (last part of a node id) or a gold file's module name."""
    names = {n.rsplit(".", 1)[-1] for n in node_ids} | {Path(p).stem for p in paths}
    return any(len(n) >= 4 and re.search(rf"\b{re.escape(n)}\b", text) for n in names)


def bm25_hit(files: dict[str, str], text: str, node_ids: list[str], k: int = 10) -> bool | None:
    """Does the localizer skill's ranking put a gold node in its top k? None without a gold node."""
    if not node_ids:
        return None
    import skill_score as ss  # pod/skill_score.py; needs pod/ on sys.path

    ranked = [c["id"] for c, _ in ss.sk_rank(ss.sk_index(files), text)]
    return bool(set(node_ids) & set(ranked[:k]))


def trace_features(trace: dict, gold_files: set[str]) -> dict:
    """First edit in a gold file? Gold file read at all? (paths with or without /workspace/)."""

    def norm(p: str) -> str:
        return p.removeprefix("/workspace/").removeprefix("./")

    cs = calls(trace)
    edits = [norm(c["args"].get("filepath", "")) for c in cs if c["tool"] in EDIT_TOOLS]
    reads = {norm(c["args"].get("filepath", "")) for c in cs if c["tool"] == "read_file"}
    return {
        "edited": bool(edits),
        "first_edit_gold": bool(edits) and edits[0] in gold_files,
        "read_gold": bool(reads & gold_files),
    }


def read_snapshot_py(tgz: Path) -> dict[str, str]:
    import skill_score as ss

    return ss.ss_read_py(tgz)


def pod_results(log: Path) -> dict[str, dict]:
    """Per-task result lines of a run that kept only its console log."""
    out = {}
    for tid, status, n_calls, secs in TASK_LINE.findall(log.read_text(errors="replace")):
        out[tid] = {"status": status, "calls": int(n_calls), "seconds": float(secs)}
    return out


def build_rows(data: Path) -> list[dict]:
    """One row per dev task: features plus outcomes over the Kaggle runs and the pod run."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pod"))
    ids = json.loads((data / "dev_subset.json").read_text())["ids"]
    tasks = {}
    for line in open(data / "competition/tasks.jsonl", encoding="utf-8"):
        t = json.loads(line)
        tasks[t["instance_id"]] = t
    hunks_csv, nodes_csv = data / "map/gold_hunks.csv", data / "map/gold_nodes.csv"
    hunks, nodes = {}, {}
    for r in csv.DictReader(open(hunks_csv, newline="", encoding="utf-8")):
        hunks.setdefault(r["instance_id"], []).append(r)
    for r in csv.DictReader(open(nodes_csv, newline="", encoding="utf-8")):
        nodes.setdefault(r["instance_id"], []).append(r)
    gold = gold_library_files(hunks_csv)
    runs = {}
    for name in KAGGLE_RUNS:
        d = data / "runs" / f"dev-{name}"
        results = {r["instance_id"]: r for r in classify_run(d, hunks_csv)}
        stats = {r["instance_id"]: r for r in csv.DictReader(open(d / "task_results.csv"))}
        runs[name] = (d, results, stats)
    pod = pod_results(data / "runs" / POD_LOG)
    rows = []
    for tid in ids:
        t = tasks[tid]
        node_ids = [n["node_id"] for n in nodes.get(tid, [])]
        row = {"id": tid, "repo": t["repo"].split("/")[-1]}
        row |= gold_features(hunks.get(tid, []), nodes.get(tid, []))
        row |= issue_features(t)
        row["names_gold"] = names_gold(t["problem_statement"], node_ids, gold.get(tid, set()))
        files = read_snapshot_py(data / "competition/snapshots" / f"{tid}.tgz")
        row["bm25_hit"] = bm25_hit(files, t["problem_statement"], node_ids)
        outcomes = []
        for d, results, stats in runs.values():
            tr = d / "raw/traces" / f"trace_{tid}.json"
            tf = (
                trace_features(json.loads(tr.read_text()), gold.get(tid, set()))
                if tr.is_file()
                else {}
            )
            outcomes.append(
                {
                    "class": results[tid]["class"],
                    "calls": int(stats[tid]["tool_calls"]),
                    "seconds": float(stats[tid]["duration_s"]),
                    **tf,
                }
            )
        row["runs"] = outcomes
        row["pod"] = pod.get(tid)
        row["n_resolved"] = sum(o["class"] == "resolved" for o in outcomes) + int(
            bool(pod.get(tid)) and pod[tid]["status"] == "resolved"
        )
        row["n_runs"] = len(outcomes) + int(bool(pod.get(tid)))
        row["group"] = group_of(row["n_resolved"], row["n_runs"])
        rows.append(row)
    return rows


def _med(values: list) -> str:
    return f"{round(statistics.median(values), 1):g}" if values else "-"


def _share(flags: list) -> str:
    flags = [f for f in flags if f is not None]
    return f"{sum(flags)}/{len(flags)}" if flags else "-"


def _cell(n: int, text: str) -> str:
    return text + ("~" if n < MIN_CELL else "")


BINS = (
    ("gold files", lambda r: "1" if r["gold_files"] <= 1 else "2+"),
    ("gold lines", lambda r: "<=10" if r["gold_lines"] <= 10 else ">10"),
    ("module-level hunk", lambda r: "yes" if r["module_level"] else "no"),
    ("async hunk", lambda r: "yes" if r["async_hunk"] else "no"),
    (
        "localizer top-10 hit",
        lambda r: {None: "no gold node", True: "yes", False: "no"}[r["bm25_hit"]],
    ),
    ("issue names gold symbol", lambda r: "yes" if r["names_gold"] else "no"),
    ("issue has code block", lambda r: "yes" if r["has_code"] else "no"),
    ("issue words", lambda r: "<150" if r["issue_words"] < 150 else ">=150"),
    ("test lines", lambda r: "<=40" if r["test_lines"] <= 40 else ">40"),
    ("missing test deps", lambda r: "yes" if r["missing_deps"] else "no"),
    ("repo", lambda r: r["repo"]),
)


def aggregate(rows: list[dict]) -> dict:
    """Group sizes, feature summaries by group, and pooled failure classes by feature bin."""
    groups = {g: [r for r in rows if r["group"] == g] for g in ("stable", "flaky", "never")}
    out = {"n": len(rows), "groups": {g: len(v) for g, v in groups.items()}, "by_group": {}}
    for g, rs in groups.items():
        out["by_group"][g] = {
            "n": len(rs),
            "gold_files": _med([r["gold_files"] for r in rs]),
            "gold_lines": _med([r["gold_lines"] for r in rs]),
            "gold_nodes": _med([r["gold_nodes"] for r in rs]),
            "issue_words": _med([r["issue_words"] for r in rs]),
            "test_lines": _med([r["test_lines"] for r in rs]),
            "module_level": _share([r["module_level"] for r in rs]),
            "async_hunk": _share([r["async_hunk"] for r in rs]),
            "bm25_hit": _share([r["bm25_hit"] for r in rs]),
            "names_gold": _share([r["names_gold"] for r in rs]),
            "missing_deps": _share([r["missing_deps"] for r in rs]),
            "mean_calls": _med([statistics.mean(o["calls"] for o in r["runs"]) for r in rs]),
            "mean_minutes": _med(
                [round(statistics.mean(o["seconds"] for o in r["runs"]) / 60, 1) for r in rs]
            ),
            "first_edit_gold": _share(
                [o.get("first_edit_gold") for r in rs for o in r["runs"] if o.get("edited")]
            ),
        }
    classes = (
        "resolved",
        "timeout",
        "budget_no_patch",
        "wrong_file",
        "broke_code",
        "inconclusive",
        "wrong_fix",
    )
    out["bins"] = {}
    for name, fn in BINS:
        table = {}
        for r in rows:
            b = fn(r)
            c = table.setdefault(b, {"tasks": 0, "runs": Counter()})
            c["tasks"] += 1
            c["runs"].update(o["class"] for o in r["runs"])
        out["bins"][name] = {
            b: {"tasks": v["tasks"], **{k: v["runs"].get(k, 0) for k in classes}}
            for b, v in sorted(table.items())
        }
    out["classes"] = classes
    return out


def unscoreable(rows: list[dict]) -> dict:
    """Never-solved tasks that probably cannot be judged here versus genuine failures."""
    never = [r for r in rows if r["group"] == "never"]
    deps = [r for r in never if r["missing_deps"]]
    inconc = [
        r
        for r in never
        if r not in deps and sum(o["class"] == "inconclusive" for o in r["runs"]) >= 3
    ]
    docs = [r for r in never if r not in deps + inconc and r["docs_only"]]
    return {
        "never": len(never),
        "missing_test_deps": len(deps),
        "inconclusive_in_3_plus_runs": len(inconc),
        "docs_only_gold": len(docs),
        "genuine": len(never) - len(deps) - len(inconc) - len(docs),
    }


def levers(rows: list[dict]) -> dict:
    """Where agent behaviour could matter: flaky tasks, budget stops that had read a gold file."""
    flaky = [r for r in rows if r["group"] == "flaky"]
    budget = [o for r in rows for o in r["runs"] if o["class"] == "budget_no_patch"]
    timeouts = [o for r in rows for o in r["runs"] if o["class"] == "timeout"]
    failed = [o for r in rows for o in r["runs"] if o["class"] != "resolved" and o.get("edited")]
    return {
        "flaky_tasks": len(flaky),
        "flaky_failed_classes": dict(
            Counter(o["class"] for r in flaky for o in r["runs"] if o["class"] != "resolved")
        ),
        "budget_stops": len(budget),
        "budget_stops_read_gold_file": sum(bool(o.get("read_gold")) for o in budget),
        "timeouts": len(timeouts),
        "failed_with_edit": len(failed),
        "failed_first_edit_gold": sum(bool(o.get("first_edit_gold")) for o in failed),
    }


def render(agg: dict, unsc: dict, lev: dict) -> str:
    """Markdown tables of aggregates (no per-task rows)."""
    lines = [
        f"Tasks: {agg['n']}. Groups: " + ", ".join(f"{g} {n}" for g, n in agg["groups"].items()),
        "",
    ]
    keys = list(next(iter(agg["by_group"].values())))
    lines += ["| Group | " + " | ".join(keys) + " |", "|" + "---|" * (len(keys) + 1)]
    for g, v in agg["by_group"].items():
        lines.append(
            f"| {g} | "
            + " | ".join(_cell(v["n"], str(v[k])) if k != "n" else str(v["n"]) for k in keys)
            + " |"
        )
    lines += ["", "Failure classes pooled over the Kaggle runs (task-runs) by feature bin:", ""]
    cls = agg["classes"]
    lines += ["| Feature | Bin | Tasks | " + " | ".join(cls) + " |", "|" + "---|" * (len(cls) + 3)]
    for name, bins in agg["bins"].items():
        for b, v in bins.items():
            lines.append(
                f"| {name} | {b} | {_cell(v['tasks'], str(v['tasks']))} | "
                + " | ".join(str(v[c]) for c in cls)
                + " |"
            )
    lines += ["", f"Never-solved tasks: {unsc}", "", f"Levers: {lev}"]
    return "\n".join(lines)


def figure(agg: dict):
    """Resolved share of task-runs by feature bin (left) and what the failed runs were (right)."""
    from analysis import style

    picks = [
        ("gold lines", "<=10"),
        ("gold lines", ">10"),
        ("gold files", "1"),
        ("gold files", "2+"),
        ("module-level hunk", "no"),
        ("module-level hunk", "yes"),
        ("localizer top-10 hit", "yes"),
        ("localizer top-10 hit", "no"),
    ]
    cls = [c for c in agg["classes"] if c != "resolved"]
    fig, (a, b) = style.plt.subplots(1, 2, figsize=(style.FIG_WIDTH, 3.4))
    labels, shares = [], []
    for feat, bin_ in picks:
        v = agg["bins"][feat][bin_]
        runs = sum(v[c] for c in agg["classes"])
        labels.append(f"{feat}: {bin_} (n={v['tasks']})")
        shares.append(100 * v["resolved"] / runs)
    a.barh(labels[::-1], shares[::-1], color=style.PALETTE["blue"])
    a.set_xlabel("Task-runs resolved (%)")
    a.set_title("Resolved share by feature")
    for i, bin_ in enumerate(("<=10", ">10")):
        v = agg["bins"]["gold lines"][bin_]
        failed = sum(v[c] for c in cls)
        left = 0.0
        for j, c in enumerate(cls):
            w = 100 * v[c] / failed
            b.barh(
                i, w, left=left, color=list(style.PALETTE.values())[j], label=c if i == 0 else None
            )
            left += w
    b.set_yticks([0, 1], ["gold <=10 lines", "gold >10 lines"])
    b.set_xlabel("Failed task-runs (%)")
    b.set_title("How the failed runs failed")
    b.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3)
    return fig


def main(argv: list[str]) -> int:
    rows = build_rows(Path(argv[0]))
    agg = aggregate(rows)
    print(render(agg, unscoreable(rows), levers(rows)))
    if os.environ.get("FIG_DIR"):
        from analysis import style

        style.save(figure(agg), "failure-features", ["dev runs", "gold map"], {"tasks": agg["n"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
