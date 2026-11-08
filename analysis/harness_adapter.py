"""Turn the harness's ATIF-v1.7 traces into the run contract's trace (docs/RUN_CONTRACT.md).

Input per task: the ATIF trace (`raw/traces/trace_<id>.json`), the task's row from our
`task_results.csv` and the run's limits. Each ATIF agent step is one model call, optionally with a
tool call and its observation, so it becomes a `model` step then a `tool` step. Field names come
from the smoke run (A34); anything the harness does not give stays null or absent.

`counted` is our own count of tool calls that use budget (everything except `submit_patch`,
`get_status` and calls refused with BudgetExceeded). The harness reports its own `tool_calls` in
the task result and the two can differ (smoke run, fastapi_14964: 25 reported, 28 counted here), so
budget statistics should use the task_results.csv column, which is the harness's.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

FREE_TOOLS = frozenset({"submit_patch", "get_status"})
PATH_KEYS = ("filepath", "file_path", "path")
GRAPH_TOOLS = frozenset({"get_code_neighbors", "search_similar_code", "get_code_subgraph"})
PY_PATH = re.compile(r"[\w./-]+\.py\b")
CONTEXT_WINDOW = 32768


def _loads(text) -> dict:
    try:
        v = json.loads(text) if isinstance(text, str) else text
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def tool_paths(name: str, args: dict) -> list[str]:
    found = [args[k] for k in PATH_KEYS if isinstance(args.get(k), str)]
    if name == "run_command" and isinstance(args.get("command"), str):
        found += PY_PATH.findall(args["command"])
    return sorted(set(found))


def tool_nodes(name: str, args: dict) -> list[str]:
    if name not in GRAPH_TOOLS:
        return []
    out: list[str] = []
    for key in ("query", "node", "symbol", "nodes"):
        v = args.get(key)
        if isinstance(v, str):
            out += [x.strip() for x in v.strip("[]").replace('"', "").split(",") if x.strip()]
        elif isinstance(v, list):
            out += [str(x) for x in v]
    return out


def convert(trace: dict, row: dict, limits: dict) -> dict:
    """One contract trace. `row` is a task_results.csv row; `limits` has max_tool_calls etc."""
    steps: list[dict] = []
    last_t = 0.0

    def add(step: dict) -> None:
        nonlocal last_t
        step["t_s"] = round(max(step["t_s"], last_t), 3)
        last_t = step["t_s"]
        step["i"] = len(steps)
        steps.append(step)

    for s in trace.get("steps", []):
        if s.get("source") != "agent":
            continue
        m = s.get("metrics") or {}
        calls = s.get("tool_calls") or []
        issue_t = (calls[0].get("extra") or {}).get("elapsed_s") if calls else None
        msg = s.get("message") or ""
        model = {
            "kind": "model",
            "t_s": float(issue_t if issue_t is not None else last_t),
            "prompt_tokens": m.get("prompt_tokens"),
            "completion_tokens": m.get("completion_tokens"),
            "context_tokens": m.get("prompt_tokens"),
            "result_chars": len(msg),
            "ok": True,
        }
        add(model)
        obs = s.get("observation") or {}
        for call in calls:
            name = call.get("function_name", "")
            args = call.get("arguments") or {}
            content = _loads(obs.get("content"))
            err = content.get("error_message") or content.get("error_type")
            failed = content.get("status") == "error"
            done_t = (obs.get("extra") or {}).get("elapsed_s")
            issued = (call.get("extra") or {}).get("elapsed_s") or last_t
            tool = {
                "kind": "tool",
                "tool": name,
                "t_s": float(done_t if done_t is not None else issued),
                "duration_s": round(max(float(done_t or issued) - float(issued), 0.0), 3),
                "ok": not failed,
                "counted": name not in FREE_TOOLS and content.get("error_type") != "BudgetExceeded",
                "args_chars": len(json.dumps(args, sort_keys=True)),
                "result_chars": len(str(obs.get("content") or "")),
                "paths": tool_paths(name, args),
                "nodes": tool_nodes(name, args),
                "error": str(err) if failed and err else None,
            }
            add(tool)
    budget = int(limits["max_tool_calls"])
    used = 0
    for st in steps:  # the harness stops charging at the cap; later calls were not budgeted
        if st["kind"] == "tool" and st.get("counted"):
            used += 1
            st["counted"] = used <= budget
    patch_chars = int(row["patch_chars"] or 0)
    outcome = {
        "resolved": row["resolved"] in (1, "1", True),
        "status": row["status"],
        "test_exit_code": int(row["test_exit_code"]) if str(row["test_exit_code"]) != "" else None,
        "patch_chars": patch_chars,
        "duration_s": float(row["duration_s"]),
        "error": None,
    }
    return {
        "schema_version": "1",
        "run_id": row["run_id"],
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "outcome": outcome,
        "limits": {
            "max_tool_calls": int(limits["max_tool_calls"]),
            "max_time_s": float(limits["max_time_minutes"]) * 60,
            "max_turns": int(limits.get("max_turns") or 500),
            "context_window": CONTEXT_WINDOW,
        },
        "steps": steps,
    }


def convert_run(run_dir: Path, limits: dict, out: Path | None = None) -> list[Path]:
    """Convert every raw trace of a run directory into `<run_dir>/traces/`."""
    out = out or run_dir / "traces"
    out.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "task_results.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    written = []
    for row in rows:
        src = run_dir / "raw" / "traces" / f"trace_{row['instance_id']}.json"
        if not src.is_file():
            continue
        trace = convert(json.loads(src.read_text(encoding="utf-8")), row, limits)
        dest = out / f"trace_{row['run_id']}_{row['instance_id']}.json"
        dest.write_text(json.dumps(trace, indent=1) + "\n", encoding="utf-8")
        written.append(dest)
    return written
