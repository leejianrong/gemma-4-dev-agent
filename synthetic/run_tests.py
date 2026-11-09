"""Stage 2a: run a repo's tests unmutated and mutated inside Docker, and classify each mutant.

Repo code never runs on the host. Every pytest run is one `docker run` with no network, a read-only
root, the repo mounted read-only and copied to a tmpfs scratch dir (where the mutated file is
dropped in), no capabilities, a non-root user, and memory, CPU, pids and wall-clock limits. The
image (docker/synthetic) needs network only when it is built.

A mutant is usable when 1 to 5 tests that pass unmutated fail on it; those tests are its
fail-to-pass set. Other outcomes (no test fails, too many fail, a rerun disagrees, timeout) are
dropped. Usage: python -m synthetic.run_tests CACHE_DIR [--n 40] [--seed 0] [--workers 3] [NAME ...]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

from synthetic.fetch import load_manifest
from synthetic.mutate import generate

IMAGE = "gemma-synthetic-tests"
MAX_KILLERS = 5
SCRIPT = (
    "set -e; mkdir -p /scratch/repo;"
    " tar --exclude=.git -C /repo -cf - . | tar -C /scratch/repo -xf -;"
    ' if [ -n "$MUT_REL" ]; then cp /mut/m.py "/scratch/repo/$MUT_REL"; fi; cd /scratch/repo;'
    ' export PYTHONPATH="/scratch/repo/$IMPORT_ROOT";'
    ' exec timeout "$T" python -m pytest -p no:cacheprovider -q --tb=no -rfE "$@"'
)
COUNT = re.compile(r"(\d+) (passed|failed|error|errors)")


class Run(NamedTuple):
    passed: int
    failed: frozenset  # ids of failed tests and collection errors
    seconds: float
    timed_out: bool


def parse_pytest(out: str) -> tuple[int, frozenset]:
    """Passed count and the ids named on FAILED/ERROR lines of the short summary."""
    ids = {
        line.split(None, 1)[1].split(" - ", 1)[0].strip()
        for line in out.splitlines()
        if line.startswith(("FAILED ", "ERROR "))
    }
    passed = sum(
        int(n) for n, w in COUNT.findall(out.splitlines()[-1] if out else "") if w == "passed"
    )
    return passed, frozenset(ids)


def docker_runner(repo: Path, import_root: str, timeout: int = 240):
    """A runner(mut, args): one isolated pytest run. mut is (repo-relative path, text) or None."""

    def run(mut: tuple[str, str] | None, args: list[str]) -> Run:
        with tempfile.TemporaryDirectory() as tmp:
            if mut:
                (Path(tmp) / "m.py").write_text(mut[1], encoding="utf-8")
            cmd = [
                *("docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL"),
                *("--security-opt", "no-new-privileges", "--pids-limit", "256", "--memory", "1g"),
                *(
                    "--cpus",
                    "2",
                    "--user",
                    "1000:1000",
                    "--tmpfs",
                    "/scratch:rw,exec,mode=1777,size=512m",
                ),
                *(
                    "--tmpfs",
                    "/tmp:rw,mode=1777,size=256m",
                    "-e",
                    "HOME=/tmp",
                    "-e",
                    "PYTHONDONTWRITEBYTECODE=1",
                ),
                *("-e", f"MUT_REL={mut[0] if mut else ''}", "-e", f"IMPORT_ROOT={import_root}"),
                *("-e", f"T={timeout}", "-v", f"{repo}:/repo:ro", "-v", f"{tmp}:/mut:ro"),
                *(IMAGE, "bash", "-c", SCRIPT, "bash", *args),
            ]
            t0 = time.time()
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
            except subprocess.TimeoutExpired:
                return Run(0, frozenset(), time.time() - t0, True)
        passed, ids = parse_pytest(res.stdout)
        return Run(passed, ids, time.time() - t0, res.returncode == 124)

    return run


def classify(base_bad: set, mut: Run, confirm: Run | None) -> tuple[str, list[str]]:
    """Status and fail-to-pass ids of a mutant. base_bad = tests failing in any unmutated run."""
    if mut.timed_out:
        return "timeout", []
    killers = sorted(set(mut.failed) - base_bad)
    if not killers:
        return "equivalent", []
    if len(killers) > MAX_KILLERS:
        return "too_broad", killers
    if confirm is None or sorted(set(confirm.failed) - base_bad) != killers:
        return "flaky", killers
    return "usable", killers


def files_naming_module(repo: Path, tests_dir: str, module: str) -> list[str]:
    """Test files (repo-relative) that name the mutated module."""
    parent, _, leaf = module.rpartition(".")
    pat = re.compile(
        rf"\b{re.escape(module)}\b"
        + (rf"|from\s+{re.escape(parent)}\s+import[^\n]*\b{leaf}\b" if parent else "")
    )
    return sorted(
        p.relative_to(repo).as_posix()
        for p in (repo / tests_dir).rglob("test_*.py")
        if pat.search(p.read_text(encoding="utf-8", errors="replace"))
    )


def evaluate(
    record: dict, run, import_root: str, tests_dir: str, repo: Path, base_bad: set
) -> dict:
    """Run one mutant: targeted tests first (stop if too many fail), then the full suite."""
    mut = ((Path(import_root) / record["file"]).as_posix(), record["mutated_text"])
    t0 = time.time()
    targets = files_naming_module(repo, tests_dir, record["module"])
    first = run(mut, targets) if targets else None
    if first and not first.timed_out and len(set(first.failed) - base_bad) > MAX_KILLERS:
        status, ids = "too_broad", sorted(set(first.failed) - base_bad)
    else:
        full = run(mut, [tests_dir])
        confirm = None
        if not full.timed_out and 0 < len(set(full.failed) - base_bad) <= MAX_KILLERS:
            confirm = run(mut, sorted(set(full.failed) - base_bad))
        status, ids = classify(base_bad, full, confirm)
    return {
        "id": record["id"],
        "status": status,
        "fail_to_pass": ids,
        "seconds": round(time.time() - t0, 1),
    }


def baseline(run, tests_dir: str, reps: int = 3) -> dict:
    runs = [run(None, [tests_dir]) for _ in range(reps)]
    bad = set().union(*(r.failed for r in runs))
    flaky = bad - set.intersection(*(set(r.failed) for r in runs))
    first = runs[0]
    total = first.passed + len(first.failed)
    return {
        "bad": bad,
        "flaky": len(flaky),
        "pass_rate": round(first.passed / total, 3) if total else 0.0,
        "tests": total,
        "seconds": round(statistics.median(r.seconds for r in runs), 1),
        "timed_out": any(r.timed_out for r in runs),
    }


def sample_mutants(repo: Path, entry: dict, n: int, seed: int) -> tuple[str, list[dict]]:
    pkg = Path(entry["package_dir"])
    root = str(pkg.parent)
    recs = generate(repo / root, n=0, seed=seed, repo=entry["name"])
    return root, [r for r in recs if r["file"].startswith(pkg.name + "/")][:n]


def run_repo(entry: dict, cache: Path, n: int, seed: int, out: Path) -> dict:
    repo = cache / entry["name"]
    root, recs = sample_mutants(repo, entry, n, seed)
    run = docker_runner(repo, root)
    tests = entry["tests_dir"]
    base = baseline(run, tests)
    summary = {"repo": entry["name"], **{k: v for k, v in base.items() if k != "bad"}, "mutants": 0}
    if base["timed_out"] or base["pass_rate"] < 0.9:
        return {
            **summary,
            "rejected": f"baseline pass rate {base['pass_rate']}, timed_out={base['timed_out']}",
        }
    t0 = time.time()
    fast = docker_runner(
        repo, root, timeout=min(120, max(20, int(8 * base["seconds"])))
    )  # loops die early
    rows = [evaluate(r, fast, root, tests, repo, base["bad"]) for r in recs]
    (out / f"{entry['name']}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    c = Counter(r["status"] for r in rows)
    m = max(len(rows), 1)
    return {
        **summary,
        "mutants": len(rows),
        "statuses": dict(c),
        "kill_rate": round(1 - (c["equivalent"] + c["timeout"]) / m, 3),
        "usable_share": round(c["usable"] / m, 3),
        "seconds_per_mutant": round((time.time() - t0) / m, 1),
        "usable_per_500": round(500 * c["usable"] / m),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m synthetic.run_tests", description=__doc__)
    ap.add_argument("cache", type=Path)
    ap.add_argument("names", nargs="*")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("data/synthetic/stage2a"))
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    entries = [
        e
        for e in load_manifest()
        if (a.cache / e["name"]).is_dir() and (not a.names or e["name"] in a.names)
    ]
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(lambda e: run_repo(e, a.cache.resolve(), a.n, a.seed, a.out), entries))
    (a.out / "summary.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    for r in rows:
        print(json.dumps(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
