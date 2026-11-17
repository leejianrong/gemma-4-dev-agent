"""Pre-flight for pod runs: tasks known to be solvable must pass their tests with the gold patch.

A pod's Python is not Kaggle's image; without this check a run can spend hours in an environment
where no task can resolve (2026-11-12: pytest was missing).
Usage: python3 env_check.py DATA ID[,ID...]
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


def test_files(test_patch: str) -> list[str]:
    """Test files a diff touches (task patches have ---/+++ headers, no diff --git line)."""
    paths = re.findall(r"^\+\+\+ b/(\S+)$", test_patch, re.MULTILINE)
    return [p for p in paths if p.endswith(".py") and "test" in Path(p).name]


def _apply(ws: Path, tmp: Path, task: dict, name: str) -> str | None:
    """Apply one stored diff to the workspace; return an error text or None."""
    diff = tmp / f"{name}.diff"
    diff.write_text(task[name].rstrip("\n") + "\n")  # stored without one
    res = subprocess.run(["git", "apply", str(diff)], cwd=ws, capture_output=True, text=True)
    return f"git apply {name} failed: {res.stderr[-300:]}" if res.returncode else None


def _failed(output: str) -> set[str]:
    """Ids on the FAILED and ERROR lines of pytest's short summary."""
    return {
        line.split(None, 1)[1].split(" - ", 1)[0].strip()
        for line in output.splitlines()
        if line.startswith(("FAILED ", "ERROR "))
    }


def _run_tests(ws: Path, tmp: Path, files: list[str], timeout: int) -> tuple[set[str], str] | str:
    """Run the touched tests; return (failed ids, output tail) or a timeout message."""
    cmd = [sys.executable, "-m", "pytest", *files, "-q", "-p", "no:cacheprovider", "-rfE"]
    # src-layout repos import from ws/src; with only ws on the path the installed copy wins
    roots = [str(ws)] + ([str(ws / "src")] if (ws / "src").is_dir() else [])
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "PYTHONPATH": os.pathsep.join(roots),
        "HOME": str(tmp),
    }
    try:
        res = subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"tests timed out after {timeout}s"
    out = res.stdout + res.stderr
    return _failed(out), out[-400:]


def check(task: dict, snapshot: Path, timeout: int = 240) -> tuple[bool, str]:
    """The gold patch must fix the touched tests: no failure it adds, at least one it removes.

    Compared with the base state plus the test patch, so a test that fails for an unrelated
    reason (a missing optional package) does not fail the gate.
    """
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        ws = tmp / "ws"
        ws.mkdir()
        with tarfile.open(snapshot) as tf:
            tf.extractall(ws, filter="data")
        files = test_files(task["test_patch"])
        if err := _apply(ws, tmp, task, "test_patch"):
            return False, err
        before = _run_tests(ws, tmp, files, timeout)
        if isinstance(before, str):
            return False, before
        if err := _apply(ws, tmp, task, "patch"):
            return False, err
        after = _run_tests(ws, tmp, files, timeout)
        if isinstance(after, str):
            return False, after
        new, fixed = after[0] - before[0], before[0] - after[0]
        if new or not fixed:
            why = f"{len(new)} new failures" if new else "no test changed from failing to passing"
            return False, why + "\n" + after[1]
        return True, after[1]


def main(argv: list[str]) -> int:
    data, ids = Path(argv[1]), argv[2].split(",")
    tasks = {}
    for line in (data / "tasks.jsonl").open(encoding="utf-8"):
        t = json.loads(line)
        tasks[t["instance_id"]] = t
    bad = 0
    for tid in ids:
        ok, tail = check(tasks[tid], data / "snapshots" / f"{tid}.tgz")
        print(f"env-check {'ok' if ok else 'FAIL'} {tid}", flush=True)
        if not ok:
            print(tail, flush=True)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
