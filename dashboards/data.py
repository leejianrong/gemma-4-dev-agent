"""Find and load run tables: real runs under data/runs/, else the synthetic fixtures."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "runs"


@dataclass
class RunData:
    runs: list[dict]
    tasks: list[dict]
    sources: list[Path]
    is_fixture: bool
    trace_dirs: list[Path] = field(default_factory=list)


def runs_root() -> Path:
    return Path(os.environ.get("RUNS_DIR", "data/runs"))


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def run_dirs(root: Path) -> list[Path]:
    """The root itself and each direct subfolder that holds a runs.csv."""
    found = [root] if (root / "runs.csv").is_file() else []
    if root.is_dir():
        found += sorted(p for p in root.iterdir() if p.is_dir() and (p / "runs.csv").is_file())
    return found


def load(root: Path | None = None) -> RunData:
    dirs = run_dirs(runs_root() if root is None else root)
    fixture = not dirs
    if fixture:
        dirs = [FIXTURES]
    runs: list[dict] = []
    tasks: list[dict] = []
    for d in dirs:
        runs += _read(d / "runs.csv")
        if (d / "task_results.csv").is_file():
            tasks += _read(d / "task_results.csv")
    return RunData(runs, tasks, dirs, fixture, [d / "traces" for d in dirs])
