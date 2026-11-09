"""Gold-patch grading check: does the air-gapped sandbox resolve a task with its own gold patch?

Runs swegemma's `verify_task` (competition code) with the task's gold patch as the agent patch,
in the Docker image `swebench-sandbox:latest` built from the public Dockerfile with `--network
none`, and keeps only aggregates. Repo tests run inside the container, never on the host.
Run it with the Python that has swegemma installed:

    python analysis/gold_check.py TASKS_JSONL SNAPSHOTS_DIR OUT_JSON WHEELS_DIR ID [ID ...]

The harness reads the sandbox setup script from $KAGGLE_SANDBOX_DIR.

OUT_JSON holds per-task rows and stays under data/ (competition rules 4b); the printed summary
has counts only.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ERRORS = (
    ("missing_module", re.compile(r"ModuleNotFoundError")),
    ("fixture_error", re.compile(r"recursive dependency involving fixture|fixture '.*' not found")),
    ("timeout", re.compile(r"[Tt]imed? ?out")),
    ("assertion", re.compile(r"\b[1-9]\d* failed\b")),
    ("collection_error", re.compile(r"\b[1-9]\d* errors?\b")),
)


def error_class(text: str) -> str:
    """First matching reason a test run did not pass, or `other`."""
    return next((name for name, rx in ERRORS if rx.search(text)), "other")


def row(res) -> dict:
    """Keep the verdict and one error class from a swegemma TaskResult."""
    return {
        "repo": res.repo,
        "resolved": bool(res.resolved),
        "error": None if res.resolved else error_class((res.test_output or "") + (res.error or "")),
    }


def summarize(rows: list[dict]) -> dict:
    by_error = collections.Counter(r["error"] for r in rows if r["error"])
    return {
        "tasks": len(rows),
        "resolved": sum(r["resolved"] for r in rows),
        "errors": dict(by_error),
    }


def main(argv: list[str]) -> int:
    import asyncio

    from adk_submission import ModelRegistry
    from swegemma.config import EvalConfig
    from swegemma.harness.verification import verify_task
    from swegemma.models import load_tasks
    from swegemma.sandbox import ContainerConfig, ContainerManager

    tasks_path, snaps, out, wheels, *ids = argv[1:]
    cfg = EvalConfig(
        tasks_path=Path(tasks_path),
        snapshots_dir=Path(snaps),
        results_dir=Path(out).parent / "results",
        submission_dir=Path(out).parent / "sub",
        models=ModelRegistry(),
        wheels_dir=Path(wheels),
    )
    box = ContainerManager(ContainerConfig(image="swebench-sandbox:latest", network_mode="none"))
    tasks = [t for t in load_tasks(Path(tasks_path)) if t.instance_id in set(ids)]
    rows = []
    for t in tasks:  # the gold patch is the "agent" patch
        res = asyncio.run(
            verify_task(box, cfg, t, Path(snaps) / f"{t.instance_id}.tgz", agent_patch=t.patch)
        )
        rows.append({"instance_id": t.instance_id, **row(res)})
        print(f"{len(rows)}/{len(tasks)} done", flush=True)
    Path(out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(json.dumps(summarize(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
