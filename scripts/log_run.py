"""Append one row per run to experiments/runs.csv, computed from the run's task_results.csv.

    uv run python scripts/log_run.py RUN_DIR --run-id ID --variant NAME --model M --subset S \
        --zip dist/submission.zip [--seed 0] [--temperature 0.2] [--parent NAME] [--kernel SLUG]

The zip's SHA-256 identifies exactly what ran; a run without one is refused, as is a repeated
run_id. Columns are always written in the contract's order (analysis/runs.py: RUNS_COLUMNS).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis import runs  # noqa: E402

LOG = Path("experiments/runs.csv")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build_row(run_dir: Path, a: argparse.Namespace) -> dict:
    _, tasks = runs.read_csv(run_dir / "task_results.csv")
    mine = [t for t in tasks if t["run_id"] == a.run_id]
    if not mine:
        raise ValueError(f"no rows for run_id {a.run_id!r} in {run_dir / 'task_results.csv'}")
    sha = a.zip_sha256 or (sha256_of(Path(a.zip)) if a.zip else "")
    if not runs.SHA256.fullmatch(sha):
        raise ValueError("a run needs the submission zip: pass --zip PATH or --zip-sha256 HEX")
    n = len(mine)
    resolved = sum(t["resolved"] == "1" for t in mine)
    wall = round(sum(float(t["duration_s"]) for t in mine), 1)
    count = lambda s: sum(t["status"] == s for t in mine)  # noqa: E731
    return {
        "run_id": a.run_id,
        "variant": a.variant,
        "parent_variant": a.parent,
        "git_sha": a.git_sha or git_sha(),
        "zip_sha256": sha,
        "model": a.model,
        "temperature": a.temperature,
        "seed": a.seed,
        "subset": a.subset,
        "max_tool_calls": a.max_tool_calls,
        "max_time_s": a.max_time_s,
        "n_tasks": n,
        "n_resolved": resolved,
        "resolution_rate": round(resolved / n, 4),
        "n_empty_patch": count("empty_patch"),
        "n_time_limit": count("time_limit"),
        "n_tool_budget": count("tool_budget"),
        "n_error": count("error"),
        "wall_s": wall,
        "minutes_per_task": round(wall / 60 / n, 2),
        "kernel": a.kernel,
        "notes": a.notes,
    }


def append(log: Path, row: dict) -> None:
    if log.is_file():
        header, existing = runs.read_csv(log)
        if header != runs.RUNS_COLUMNS:
            raise ValueError(f"{log} has columns {header}, expected the contract order")
        if any(r["run_id"] == row["run_id"] for r in existing):
            raise ValueError(f"run_id {row['run_id']!r} is already in {log}")
    else:
        log.parent.mkdir(parents=True, exist_ok=True)
    new = not log.is_file()
    with open(log, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=runs.RUNS_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({c: row[c] for c in runs.RUNS_COLUMNS})


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--subset", required=True)
    ap.add_argument("--zip")
    ap.add_argument("--zip-sha256")
    ap.add_argument("--parent", default="")
    ap.add_argument("--git-sha", default="")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--max-tool-calls", type=int, default=100)
    ap.add_argument("--max-time-s", type=int, default=3600)
    ap.add_argument("--kernel", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument("--log", type=Path, default=LOG)
    a = ap.parse_args(argv[1:])
    try:
        row = build_row(a.run_dir, a)
        append(a.log, row)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"logged {row['run_id']}: {row['n_resolved']}/{row['n_tasks']} resolved -> {a.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
