"""T1 (docs/research/trace-analyses.md): aggregates that answer four questions from raw traces.

Q1 message length by call index (does commentary shrink after the first tool call?), Q2 what the
agent does after a refused edit, Q3 call index and seconds at the first edit, first test and submit,
Q4 the resolved and unresolved groups side by side. Only aggregates are printed (rules 4b).
Usage: python -m analysis.trace_questions RUN_DIR [RUN_DIR ...]
(each RUN_DIR holds raw/traces and task_results.csv)
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

from analysis.trace_review import calls, command_category

MAX_CALL_INDEX = 28


def message_lengths(trace: dict) -> list[int]:
    """Visible text length of each agent step, in order; a missing message counts as 0."""
    return [len(s.get("message") or "") for s in trace["steps"] if s.get("source") == "agent"]


def edit_followups(trace: dict) -> dict:
    """For each refused edit_file, the next call: same-path edit, same-path read, other, or none.

    Edits refused only because the call budget ran out are not edit failures and are skipped.
    """
    cs = calls(trace)
    out = {"refused": 0, "retry_edit": 0, "reread": 0, "other": 0, "last": 0}
    for i, c in enumerate(cs):
        if c["tool"] != "edit_file" or c["status"] != "error":
            continue
        if c["error_type"] == "BudgetExceeded":
            continue
        out["refused"] += 1
        if i + 1 == len(cs):
            out["last"] += 1
            continue
        nxt = cs[i + 1]
        same = nxt["args"].get("filepath") == c["args"].get("filepath")
        if nxt["tool"] == "edit_file" and same:
            out["retry_edit"] += 1
        elif nxt["tool"] == "read_file" and same:
            out["reread"] += 1
        else:
            out["other"] += 1
    return out


def _clock(trace: dict) -> list[float]:
    """Elapsed seconds after each tool call, parallel to `calls(trace)`."""
    out, prev = [], 0.0
    for s in trace["steps"]:
        if s.get("source") != "agent":
            continue
        t = (s.get("extra") or {}).get("elapsed_s", prev)
        out.extend([t] * len(s.get("tool_calls") or []))
        prev = t
    return out


def milestones(trace: dict) -> dict:
    """(0-based call index, seconds) at the first edit, first test and submit; None if never."""
    cs, clock = calls(trace), _clock(trace)

    def first(pred):
        for i, c in enumerate(cs):
            if pred(c):
                return (i, clock[i])
        return None

    def is_test(c):
        cmd = c["args"].get("command", "")
        return c["tool"] == "run_command" and command_category(cmd) == "test"

    return {
        "first_edit": first(lambda c: c["tool"] in ("edit_file", "write_file")),
        "first_test": first(is_test),
        "submit": first(lambda c: c["tool"] == "submit_patch"),
        "calls": len(cs),
    }


def _med(vals: list[float]):
    return statistics.median(vals) if vals else None


def _group(rows: list[dict]) -> dict:
    def at(key, pos):
        return [r["m"][key][pos] for r in rows if r["m"][key] is not None]

    longest = max((len(r["msg"]) for r in rows), default=0)
    by_call = []
    for i in range(min(longest, MAX_CALL_INDEX)):
        col = [r["msg"][i] for r in rows if len(r["msg"]) > i]
        by_call.append(_med(col))
    empty = [x == 0 for r in rows for x in r["msg"][1:]]
    return {
        "n": len(rows),
        "median_calls": _med([r["m"]["calls"] for r in rows]),
        "median_first_edit_call": _med(at("first_edit", 0)),
        "median_first_edit_s": _med(at("first_edit", 1)),
        "median_first_test_call": _med(at("first_test", 0)),
        "median_submit_call": _med(at("submit", 0)),
        "no_submit": sum(r["m"]["submit"] is None for r in rows),
        "msg_median_by_call": by_call,
        "share_empty_after_first": round(sum(empty) / len(empty), 2) if empty else None,
    }


def summarize_runs(rows: list[dict]) -> dict:
    """Group rows (`resolved`, `m` milestones, `msg` lengths) into all, resolved and unresolved."""
    return {
        "all": _group(rows),
        "resolved": _group([r for r in rows if r["resolved"]]),
        "unresolved": _group([r for r in rows if not r["resolved"]]),
    }


def load_rows(run: Path) -> tuple[list[dict], dict]:
    """Per-task rows (kept in memory only) and the summed edit follow-ups for one run directory."""
    resolved = {}
    with open(run / "task_results.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            resolved[r["instance_id"]] = r["resolved"] == "1"
    rows, follow = [], {"refused": 0, "retry_edit": 0, "reread": 0, "other": 0, "last": 0}
    for f in sorted((run / "raw" / "traces").glob("trace_*.json")):
        tid = f.stem.removeprefix("trace_")
        if tid not in resolved:
            continue
        t = json.loads(f.read_text(encoding="utf-8"))
        rows.append({"resolved": resolved[tid], "m": milestones(t), "msg": message_lengths(t)})
        for k, v in edit_followups(t).items():
            follow[k] += v
    return rows, follow


def main(argv: list[str]) -> int:
    for arg in argv[1:]:
        rows, follow = load_rows(Path(arg))
        print(Path(arg).name, json.dumps({"edit_followups": follow, **summarize_runs(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
