"""GEM-66: behaviour aggregates from raw harness traces (ATIF), with no per-task output.

A raw trace has `steps`; agent steps carry at most one tool call (`function_name`, `arguments`) and
an observation whose `content` is a JSON string with a `status`. `features` reduces one trace to
numbers; `summarize` reduces a list of them to medians and totals. Only aggregates are printed,
because the competition rules forbid publishing per-task data (terms 4b).
Usage: python -m analysis.trace_review RUN_DIR   (RUN_DIR holds raw/traces and task_results.csv)
"""

from __future__ import annotations

import collections
import csv
import json
import re
import statistics
import sys
from pathlib import Path

EDIT_TOOLS = ("edit_file", "write_file")
GRAPH_TOOLS = ("get_code_neighbors", "search_similar_code", "get_code_subgraph")
CATEGORIES = (
    ("test", r"pytest"),
    ("repro", r"<<|\bpython3?\b|\bpip\b"),
    ("search", r"\b(grep|rg|find|ls|tree|ag)\b"),
    ("read", r"\b(cat|head|tail|sed|wc|awk)\b"),
    ("git", r"\bgit\b"),
)
IN_TESTS = re.compile(r"(^|/)(tests?|testing)(/|_)|test_[a-z_]*\.py|_test\.py")


def command_category(cmd: str) -> str:
    """Rough class of a shell command: repro, test, search, read, git or other (first match)."""
    if re.search(r"\bsed\s+-i|\bpatch\b|\bgit apply\b", cmd):
        return "shell_edit"
    for name, pat in CATEGORIES:
        if re.search(pat, cmd):
            return name
    return "other"


def _status(step: dict) -> tuple[str, str]:
    """('ok' or 'error', error_type) from an observation's JSON content."""
    try:
        body = json.loads((step.get("observation") or {}).get("content") or "{}")
    except ValueError:
        return "ok", ""
    return body.get("status", "ok"), body.get("error_type", "")


def calls(trace: dict) -> list[dict]:
    """One record per tool call, in order, with its status, observation size and prompt size."""
    out, prev = [], 0.0
    for s in trace["steps"]:
        if s.get("source") != "agent":
            continue
        t = (s.get("extra") or {}).get("elapsed_s", prev)
        for tc in s.get("tool_calls") or []:
            status, etype = _status(s)
            out.append(
                {
                    "tool": tc["function_name"],
                    "args": tc.get("arguments") or {},
                    "status": status,
                    "error_type": etype,
                    "obs_chars": len((s.get("observation") or {}).get("content") or ""),
                    "prompt_tokens": (s.get("metrics") or {}).get("prompt_tokens", 0),
                    "step_s": t - prev,
                }
            )
        prev = t
    return out


def longest_run(flags: list[bool]) -> int:
    """Length of the longest run of consecutive True values."""
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def features(trace: dict, budget: int = 28) -> dict:
    cs = calls(trace)
    edit_idx = [i for i, c in enumerate(cs) if c["tool"] in EDIT_TOOLS]
    agent = [s for s in trace["steps"] if s.get("source") == "agent"]
    tools = collections.Counter(c["tool"] for c in cs)
    cats = collections.Counter(
        command_category(c["args"].get("command", "")) for c in cs if c["tool"] == "run_command"
    )
    edit_at = edit_idx[0] if edit_idx else None
    paths = [c["args"].get("filepath", "") for c in cs if c["tool"] == "read_file"]
    edits = [c for c in cs if c["tool"] == "edit_file"]
    return {
        "calls": len(cs),
        "agent_steps": len(agent),
        "text_only_turns": sum(1 for s in agent if not s.get("tool_calls")),
        "calls_before_first_edit": edit_at if edit_at is not None else len(cs),
        "edited": edit_at is not None,
        "repro_run": longest_run(
            [
                c["tool"] == "run_command"
                and command_category(c["args"].get("command", "")) == "repro"
                for c in cs
            ]
        ),
        "calls_over_budget": max(0, len(cs) - budget),
        "budget_errors": sum(1 for c in cs if c["error_type"] == "BudgetExceeded"),
        "long_steps": sum(1 for c in cs if c["step_s"] > 60),
        "verified_after_edit": bool(edit_idx)
        and any(
            c["tool"] == "run_command"
            and command_category(c["args"].get("command", "")) in ("test", "repro")
            for c in cs[edit_idx[-1] + 1 :]
        ),
        "tools": dict(tools),
        "commands": dict(cats),
        "graph_calls": sum(tools[g] for g in GRAPH_TOOLS),
        "read_errors": sum(1 for c in cs if c["tool"] == "read_file" and c["status"] == "error"),
        "edit_calls": len(edits),
        "edit_errors": sum(1 for c in edits if c["status"] == "error"),
        "submit_calls": tools["submit_patch"],
        "distinct_files_read": len(set(paths)),
        "repeat_reads": len(paths) - len(set(paths)),
        "reads_test_files": any(IN_TESTS.search(p) for p in paths)
        or any(
            IN_TESTS.search(c["args"].get("command", ""))
            for c in cs
            if c["tool"] == "run_command"
            and command_category(c["args"].get("command", "")) == "read"
        ),
        "ran_tests": cats["test"] > 0,
        "wrote_new_files": tools["write_file"],
        "max_prompt_tokens": max((c["prompt_tokens"] for c in cs), default=0),
        "obs_chars": sum(c["obs_chars"] for c in cs),
        "seconds_per_step": statistics.median([c["step_s"] for c in cs]) if cs else 0.0,
    }


def _stats(vals: list[float]) -> dict:
    return {"median": statistics.median(vals), "mean": round(statistics.fmean(vals), 2)}


def summarize(rows: list[dict]) -> dict:
    """Aggregate per-trace features: medians for counts, shares for flags, totals for tools."""
    n = len(rows)
    out: dict = {"traces": n}
    for k in (
        "calls",
        "calls_before_first_edit",
        "text_only_turns",
        "edit_errors",
        "read_errors",
        "distinct_files_read",
        "repeat_reads",
        "max_prompt_tokens",
        "seconds_per_step",
    ):
        out[k] = _stats([r[k] for r in rows])
    for k in ("edited", "reads_test_files", "ran_tests", "verified_after_edit"):
        out[f"share_{k}"] = round(sum(r[k] for r in rows) / n, 2)
    out["tasks_with_repro_run_4plus"] = sum(r["repro_run"] >= 4 for r in rows)
    for k in ("tools", "commands"):
        total: collections.Counter = collections.Counter()
        for r in rows:
            total.update(r[k])
        out[f"total_{k}"] = dict(total)
    for k in (
        "graph_calls",
        "submit_calls",
        "edit_calls",
        "wrote_new_files",
        "calls_over_budget",
        "budget_errors",
        "long_steps",
    ):
        out[f"total_{k}"] = sum(r[k] for r in rows)
    return out


def load_run(run: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """Features keyed by instance id, and each instance's status, from a run directory."""
    status = {}
    with open(run / "task_results.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            status[r["instance_id"]] = r["status"]
    feats = {}
    for f in sorted((run / "raw" / "traces").glob("trace_*.json")):
        tid = f.stem.removeprefix("trace_")
        if tid in status:
            feats[tid] = features(json.loads(f.read_text(encoding="utf-8")))
    return feats, status


def main(argv: list[str]) -> int:
    feats, status = load_run(Path(argv[1]))
    if len(argv) > 2:  # a gold_hunks.csv path: also split by failure class
        from analysis.failure_classes import classify_run

        status = {r["instance_id"]: r["class"] for r in classify_run(Path(argv[1]), Path(argv[2]))}
        for name in sorted(set(status.values())):
            ids = [t for t in feats if status[t] == name]
            print(f"class:{name}", json.dumps(summarize([feats[t] for t in ids])))
        return 0
    groups = {
        "all": list(feats),
        "resolved": [t for t in feats if status[t] == "resolved"],
        "unresolved_with_patch": [t for t in feats if status[t] == "unresolved"],
        "timeout": [t for t in feats if status[t] == "error"],
        "no_patch": [t for t in feats if status[t] in ("tool_budget", "empty_patch")],
    }
    for name, ids in groups.items():
        if ids:
            print(name, json.dumps(summarize([feats[t] for t in ids])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
