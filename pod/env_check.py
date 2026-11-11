"""Pre-flight for pod runs: tasks known to be solvable must pass their tests with the gold patch.

A pod's Python is not Kaggle's image; without this check a run can spend hours in an environment
where no task can resolve (2026-11-12: pytest was missing).
Usage: python3 env_check.py DATA ID[,ID...]
"""

from __future__ import annotations

import json
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


def check(task: dict, snapshot: Path, timeout: int = 240) -> tuple[bool, str]:
    """Unpack the snapshot, apply the gold and test patches, run the touched tests."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        with tarfile.open(snapshot) as tf:
            tf.extractall(ws, filter="data")
        for name in ("patch", "test_patch"):
            (Path(tmp) / f"{name}.diff").write_text(
                task[name].rstrip("\n") + "\n"
            )  # stored without one
            res = subprocess.run(
                ["git", "apply", str(Path(tmp) / f"{name}.diff")],
                cwd=ws,
                capture_output=True,
                text=True,
            )
            if res.returncode:
                return False, f"git apply {name} failed: {res.stderr[-300:]}"
        cmd = [sys.executable, "-m", "pytest", *test_files(task["test_patch"]), "-q", "-x"]
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "PYTHONPATH": str(ws), "HOME": tmp}
        try:
            res = subprocess.run(
                cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return False, f"tests timed out after {timeout}s"
        return res.returncode == 0, (res.stdout + res.stderr)[-400:]


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
