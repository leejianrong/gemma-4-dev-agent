"""The run contract the eval runner writes and the dashboards read (docs/RUN_CONTRACT.md).

Three artefacts: a trace per task (schemas/trace.schema.json), `task_results.csv` (one row per
task per run) and `runs.csv` (one row per run). `validate_*` return a list of problems, empty when
the artefact is valid, so callers can show every problem at once. The checks go beyond the schema:
a trace must agree with itself and the CSVs must agree with each other.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "trace.schema.json"
STATUSES = (
    "resolved",
    "unresolved",
    "empty_patch",
    "time_limit",
    "tool_budget",
    "turn_budget",
    "model_timeout",
    "error",
)
RUNS_COLUMNS = (
    "run_id variant parent_variant git_sha model temperature seed subset max_tool_calls max_time_s "
    "n_tasks n_resolved resolution_rate n_empty_patch n_time_limit n_tool_budget n_error "
    "wall_s kernel notes"
).split()
TASK_COLUMNS = (
    "run_id instance_id repo resolved status test_exit_code patch_chars tool_calls turns "
    "duration_s prompt_tokens completion_tokens max_context_tokens"
).split()
_STATUS_COUNTS = {
    "n_empty_patch": "empty_patch",
    "n_time_limit": "time_limit",
    "n_tool_budget": "tool_budget",
    "n_error": "error",
}


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_trace(trace: dict) -> list[str]:
    """Schema errors first; the semantic checks run only when the shape is right."""
    validator = jsonschema.Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(trace), key=lambda e: list(e.absolute_path))
    problems = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors]
    if problems:
        return problems
    out, steps = trace["outcome"], trace["steps"]
    if out["resolved"] != (out["status"] == "resolved"):
        problems.append(f"outcome: resolved={out['resolved']} but status={out['status']!r}")
    if out["status"] == "empty_patch" and out["patch_chars"] != 0:
        problems.append("outcome: status empty_patch but patch_chars > 0")
    if out["resolved"] and out["patch_chars"] == 0:
        problems.append("outcome: resolved with an empty patch")
    last_t = -1.0
    for n, s in enumerate(steps):
        if s["i"] != n:
            problems.append(f"steps/{n}: i={s['i']}, expected {n}")
        if s["t_s"] < last_t:
            problems.append(f"steps/{n}: t_s {s['t_s']} goes back in time (after {last_t})")
        last_t = max(last_t, s["t_s"])
        if s["kind"] == "tool" and not s.get("tool"):
            problems.append(f"steps/{n}: a tool step needs a tool name")
    if steps and out["duration_s"] < steps[-1]["t_s"]:
        problems.append("outcome: duration_s is shorter than the last step")
    counted = sum(1 for s in steps if s["kind"] == "tool" and s.get("counted", True))
    if counted > trace["limits"]["max_tool_calls"]:
        problems.append(f"steps: {counted} counted tool calls exceed the limit")
    if out["status"] == "tool_budget" and counted < trace["limits"]["max_tool_calls"]:
        problems.append("outcome: status tool_budget but the budget was not used up")
    return problems


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _columns(got: list[str], want: list[str], name: str) -> list[str]:
    missing = [c for c in want if c not in got]
    return [f"{name}: missing columns {missing}"] if missing else []


def _num(row: dict, col: str, name: str, n: int, problems: list[str], kind=float) -> None:
    try:
        v = kind(row[col])
    except (TypeError, ValueError):
        problems.append(f"{name} row {n}: {col}={row[col]!r} is not a number")
        return
    if v < 0:
        problems.append(f"{name} row {n}: {col} is negative")


def validate_task_results(path: Path) -> list[str]:
    cols, rows = read_csv(path)
    problems = _columns(cols, TASK_COLUMNS, "task_results.csv")
    if problems:
        return problems
    seen = set()
    for n, r in enumerate(rows, 2):
        key = (r["run_id"], r["instance_id"])
        if key in seen:
            problems.append(f"task_results.csv row {n}: duplicate {key}")
        seen.add(key)
        if r["status"] not in STATUSES:
            problems.append(f"task_results.csv row {n}: unknown status {r['status']!r}")
        if r["resolved"] not in ("0", "1"):
            problems.append(f"task_results.csv row {n}: resolved must be 0 or 1")
        elif (r["resolved"] == "1") != (r["status"] == "resolved"):
            problems.append(f"task_results.csv row {n}: resolved and status disagree")
        for col in ("patch_chars", "tool_calls", "turns"):
            _num(r, col, "task_results.csv", n, problems, int)
        _num(r, "duration_s", "task_results.csv", n, problems)
    return problems


def validate_runs(path: Path, task_results: Path | None = None) -> list[str]:
    cols, rows = read_csv(path)
    problems = _columns(cols, RUNS_COLUMNS, "runs.csv")
    if problems:
        return problems
    ids = [r["run_id"] for r in rows]
    problems += [
        f"runs.csv: duplicate run_id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})
    ]
    for n, r in enumerate(rows, 2):
        for col in ("n_tasks", "n_resolved", "seed"):
            _num(r, col, "runs.csv", n, problems, int)
    if task_results is None or problems:
        return problems
    _, trs = read_csv(task_results)
    for r in rows:
        mine = [t for t in trs if t["run_id"] == r["run_id"]]
        if not mine:
            problems.append(f"runs.csv: run {r['run_id']} has no task_results rows")
            continue
        checks = {"n_tasks": len(mine), "n_resolved": sum(t["resolved"] == "1" for t in mine)}
        for col, status in _STATUS_COUNTS.items():
            checks[col] = sum(t["status"] == status for t in mine)
        for col, want in checks.items():
            if int(r[col]) != want:
                problems.append(
                    f"runs.csv: run {r['run_id']} {col}={r[col]} but task_results has {want}"
                )
        rate = checks["n_resolved"] / len(mine)
        if abs(float(r["resolution_rate"]) - rate) > 1e-3:
            problems.append(
                f"runs.csv: run {r['run_id']} resolution_rate disagrees with task_results"
            )
    return problems


def validate_dir(root: Path) -> list[str]:
    """Validate a runs directory: runs.csv, task_results.csv and traces/*.json agree."""
    problems: list[str] = []
    tr, rn = root / "task_results.csv", root / "runs.csv"
    for f in (tr, rn):
        if not f.is_file():
            problems.append(f"{f} not found")
    if problems:
        return problems
    problems += validate_task_results(tr) + validate_runs(rn, tr)
    _, trows = read_csv(tr)
    by_key = {(t["run_id"], t["instance_id"]): t for t in trows}
    for f in sorted((root / "traces").glob("*.json")):
        try:
            trace = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            problems.append(f"{f.name}: not JSON ({e})")
            continue
        problems += [f"{f.name}: {p}" for p in validate_trace(trace)]
        row = by_key.get((trace.get("run_id"), trace.get("instance_id")))
        if row is None:
            problems.append(f"{f.name}: no matching row in task_results.csv")
        elif row["status"] != trace.get("outcome", {}).get("status"):
            problems.append(f"{f.name}: status differs from task_results.csv")
    return problems
