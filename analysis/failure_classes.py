"""GEM-16: put every task of a run into one failure class, from its status, patch and test log.

Rules run in order and the first match wins:
  resolved       tests pass
  timeout        status error (the 8-minute session limit); a patch may exist but was not graded
  budget_no_patch  status tool_budget, no patch left behind
  no_patch       agent finished with an empty patch
  wrong_file     patch touches none of the library files the gold patch edits
  broke_code     patch makes the library fail to import or parse (SyntaxError, ImportError, ...)
  inconclusive   tests errored before any assertion ran (missing test module, broken fixture)
  wrong_fix      right file, tests ran, an assertion still fails
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

CLASSES = (
    "resolved",
    "timeout",
    "budget_no_patch",
    "no_patch",
    "wrong_file",
    "broke_code",
    "inconclusive",
    "wrong_fix",
)
BROKE = re.compile(r"SyntaxError|IndentationError|cannot import name|has no attribute|NameError")
ERRORED = re.compile(r"ModuleNotFoundError|recursive dependency involving fixture")
FAILED = re.compile(r"\b[1-9]\d* failed\b")


def patch_files(patch: str) -> set[str]:
    return set(re.findall(r"^diff --git a/(\S+) b/", patch, re.MULTILINE))


def classify(row: dict, patch: str, log: str, gold_files: set[str]) -> str:
    status = row["status"]
    if status == "resolved":
        return "resolved"
    if status == "error":
        return "timeout"
    if status == "tool_budget":
        return "budget_no_patch"
    if status == "empty_patch" or not patch.strip():
        return "no_patch"
    if gold_files and not (patch_files(patch) & gold_files):
        return "wrong_file"
    if BROKE.search(log):
        return "broke_code"
    if ERRORED.search(log) and not FAILED.search(log):
        return "inconclusive"
    return "wrong_fix"


def gold_library_files(hunks_csv: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    with open(hunks_csv, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["status"] != "non_library":
                out.setdefault(r["instance_id"], set()).add(r["path"])
    return out


def classify_run(run_dir: Path, hunks_csv: Path) -> list[dict]:
    gold = gold_library_files(hunks_csv)
    with open(run_dir / "task_results.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        tid = r["instance_id"]
        pf, lf = run_dir / "patches" / f"{tid}.patch", run_dir / "test_outputs" / f"{tid}.log"
        patch = pf.read_text(encoding="utf-8") if pf.is_file() else ""
        log = lf.read_text(encoding="utf-8", errors="replace") if lf.is_file() else ""
        cls = classify(r, patch, log, gold.get(tid, set()))
        out.append({"instance_id": tid, "repo": r["repo"], "status": r["status"], "class": cls})
    return out


if __name__ == "__main__":
    import collections
    import sys

    res = classify_run(Path(sys.argv[1]), Path(sys.argv[2]))
    count = collections.Counter(r["class"] for r in res)
    for c in CLASSES:
        print(f"{c:16s}{count.get(c, 0):3d}  {[r['instance_id'] for r in res if r['class'] == c]}")
