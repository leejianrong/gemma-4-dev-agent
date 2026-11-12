"""Aggregate failure modes from a pod run's console log (job.log), for the small-model runs.

The log has one block per task: event lines (`  [ 12.3s] 🔧 run_command ...`, thoughts, tool
results) and then a marker `TASK n/36 id status=.. calls=.. t=..s`. We read it as text only. Output
is counts and shares, never ids or text (competition rules 4b). Usage:
  python3 -I -m analysis.small_model_log NAME=job.log [NAME=job.log ...] [--gold gold_hunks.csv]
"""

from __future__ import annotations

import csv
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

MARK = re.compile(
    r"TASK (\d+)/\d+ (\S+) status=(\S+) calls=(\d+) t=([\d.]+)"
)  # glued to a box edge
EVENT = re.compile(r"^  \[\s*[\d.]+s\]\s+(\S+)\s?(.*)$")
ERROR_CLASSES = [
    ("edit: old_string not found", r"old_string not found"),
    ("edit: identical old and new string", r"No changes to apply"),
    ("edit: several matches", r"Target string occurs"),
    ("tool call missing arguments", r"mandatory input parameters are not present"),
    ("path does not exist", r"Source path .* (?:not|does)"),
    ("bad line range", r"start_line .* cannot be greater"),
]
TOOLS = {
    "📖": "read_file",
    "✏️": "edit_file",
    "🔧": "run_command",
    "📝": "write_file",
    "🤖": "submit_patch",
}


def error_class(text: str) -> str:
    for name, pat in ERROR_CLASSES:
        if re.search(pat, text):
            return name
    return "other"


def path_kind(path: str) -> str:
    if path.startswith(("docs_src/", "docs/")):
        return "docs"
    if path.startswith("tests/") or "/test_" in path:
        return "tests"
    return "library"


def parse(text: str) -> list[dict]:
    """One dict per task: status, calls, seconds, tool calls, errors, thoughts, edits, tests."""
    tasks, start = [], 0
    for m in MARK.finditer(text):
        block = text[start : m.start()]
        start = m.end()
        lines = block.splitlines()
        t = {
            "id": m.group(2),
            "status": m.group(3),
            "calls": int(m.group(4)),
            "secs": float(m.group(5)),
            "tools": Counter(),
            "errors": Counter(),
            "thoughts": [],
            "edits": [],
            "tests": [],
            "no_submit": "without explicit submit_patch" in block,
        }
        for i, line in enumerate(lines):
            ev = EVENT.match(line)
            if not ev:
                continue
            icon, rest = ev.groups()
            if icon in TOOLS:
                t["tools"][TOOLS[icon]] += 1
                tail = " ".join(lines[i + 1 : i + 8])
                if icon == "✏️":
                    p = re.match(r"edit_file \((.*?)\)", rest)
                    t["edits"].append(p.group(1) if p else "")
                if icon == "🔧" and "pytest" in rest + tail[:200]:
                    res = " ".join(lines[i + 1 : i + 12])
                    bad = re.search(r"\bfailed\b|\berror", res, re.I)
                    ok = re.search(r"\bpassed\b", res)
                    t["tests"].append("fail" if bad else "pass" if ok else "unknown")
            elif icon == "💭":
                n = re.match(r"\((\d+) chars\)", rest)
                if n:
                    t["thoughts"].append(int(n.group(1)))
            elif icon == "❌":
                t["errors"][error_class(rest + " " + " ".join(lines[i + 1 : i + 4]))] += 1
        tasks.append(t)
    return tasks


def kind(t: dict) -> str:
    if t["status"] == "resolved":
        return "resolved"
    if t["status"] == "error" and t["secs"] >= 470:
        return "timeout"
    return t["status"] if t["status"] != "error" else "error (other)"


def share(n: int, d: int) -> str:
    return f"{n} of {d} ({100 * n / d:.0f}%)" if d else "0"


def summarize(tasks: list[dict], gold: dict[str, set[str]] | None = None) -> dict[str, object]:
    n = len(tasks)
    out: dict[str, object] = {"tasks": n, "status": dict(Counter(kind(t) for t in tasks))}
    calls = Counter()
    errs = Counter()
    for t in tasks:
        calls.update(t["tools"])
        errs.update(t["errors"])
    out["calls_by_tool"] = dict(calls)
    out["errors_by_class"] = dict(errs)
    out["error_rate"] = f"{sum(errs.values())} of {sum(calls.values())} calls"
    out["tasks_with_errors"] = share(sum(1 for t in tasks if t["errors"]), n)
    out["median_calls"] = st.median(t["calls"] for t in tasks)
    out["no_submit_call"] = share(sum(1 for t in tasks if not t["tools"]["submit_patch"]), n)
    th = [x for t in tasks for x in t["thoughts"]]
    if th:
        q = st.quantiles(th, n=10)
        out["thought_chars"] = {
            "mean": round(st.mean(th)),
            "median": st.median(th),
            "p90": round(q[-1]),
        }
    per = defaultdict(list)
    for t in tasks:
        per[kind(t)].append(sum(t["thoughts"]))
    out["thought_chars_per_task_by_status"] = {k: round(st.mean(v)) for k, v in per.items()}
    ran = [t for t in tasks if t["tests"]]
    out["ran_a_test"] = share(len(ran), n)
    out["resolved_with_test"] = share(sum(t["status"] == "resolved" for t in ran), len(ran))
    rest = [t for t in tasks if not t["tests"]]
    out["resolved_without_test"] = share(sum(t["status"] == "resolved" for t in rest), len(rest))
    out["last_test_result_unresolved"] = dict(
        Counter(t["tests"][-1] for t in ran if t["status"] != "resolved")
    )
    kinds = Counter(path_kind(p) for t in tasks for p in set(t["edits"]))
    out["files_edited_by_kind"] = dict(kinds)
    out["tasks_editing_docs_only"] = share(
        sum(1 for t in tasks if t["edits"] and all(path_kind(p) != "library" for p in t["edits"])),
        n,
    )
    out["edits_per_task_median"] = st.median(len(t["edits"]) for t in tasks)
    if gold:
        hit = [t for t in tasks if set(t["edits"]) & gold.get(t["id"], set())]
        out["edited_a_gold_file"] = share(len(hit), n)
        bad = [t for t in tasks if t["status"] != "resolved"]
        out["unresolved_edited_a_gold_file"] = share(
            sum(1 for t in bad if set(t["edits"]) & gold.get(t["id"], set())), len(bad)
        )
    return out


def load_gold(path: Path) -> dict[str, set[str]]:
    gold: dict[str, set[str]] = defaultdict(set)
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            gold[r["instance_id"]].add(r["path"])
    return gold


def main(argv: list[str]) -> int:
    gold_path = None
    runs = []
    it = iter(argv[1:])
    for a in it:
        if a == "--gold":
            gold_path = Path(next(it))
        else:
            name, _, p = a.partition("=")
            runs.append((name, Path(p)))
    gold = load_gold(gold_path) if gold_path else None
    for name, p in runs:
        print(f"== {name}")
        for k, v in summarize(parse(p.read_text(encoding="utf-8", errors="replace")), gold).items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
