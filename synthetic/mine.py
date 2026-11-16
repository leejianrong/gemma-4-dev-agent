"""S1 of benchmark v2: tasks from real commits (docs/BENCHMARK_V2.md).

A commit that changes library code and test code in one go, where the new tests fail on the parent
and pass on the commit, is a task: base = the parent, `patch` = the library part, `test_patch` =
the test part, issue text = the commit message with links and trailers removed (never the diff).
Git only reads history; the tests run in the same no-network container as the other stages
(synthetic/run_tests.py). Output is a tasks.jsonl in the competition's layout plus snapshots.
Usage: python -m synthetic.mine HISTORY_DIR NAME [NAME ...] [--max-commits N] [--out DIR]
       python -m synthetic.mine graphs DIR     add graphs/ and embeddings/ to a mined DIR
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

from synthetic.export import CREATED_AT, write_graph
from synthetic.fetch import load_manifest
from synthetic.graph import read_tree
from synthetic.realism import summarize
from synthetic.run_tests import Run, docker_runner
from synthetic.tasks import GIT, commit_tree, git_env

MAX_LIB_LINES = 300  # larger commits are refactors, not tasks an agent could solve in 28 calls
TRAILER = re.compile(
    r"^(Co-authored-by|Signed-off-by|Reviewed-by|Fixes|Closes|Resolves|Refs?)\b.*$", re.I
)
URL = re.compile(r"https?://\S+")
PR_SUFFIX = re.compile(r"\s*\(#\d+\)\s*$")
RECORD, FIELD = "\x01", "\x02"


def classify_files(
    paths: list[str], package_dir: str, tests_dir: str
) -> tuple[list[str], list[str]] | None:
    """(library .py files, test .py files) of a commit, or None unless it has both.

    Files outside the package and the tests dir (docs, changelog, packaging) are left out.
    """
    tests = [p for p in paths if p.startswith(tests_dir + "/") and p.endswith(".py")]
    lib = [
        p for p in paths if p.startswith(package_dir + "/") and p.endswith(".py") and p not in tests
    ]
    return (lib, tests) if lib and tests else None


def clean_message(subject: str, body: str) -> str:
    """The commit message as an issue text: no PR number, links, issue references or trailers."""
    lines = []
    for ln in body.splitlines():
        if TRAILER.match(ln.strip()):
            continue
        bare = URL.sub("", ln)
        if bare != ln and len(bare.split()) <= 2:  # "See <link>": nothing left worth keeping
            continue
        lines.append(bare)
    text = "\n".join(lines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    head = PR_SUFFIX.sub("", subject).strip()
    return f"{head}\n\n{text}" if text else head


def size_of(patch: str) -> int:
    """Changed lines of a unified diff."""
    return sum(
        1 for ln in patch.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))
    )


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(
        [*GIT, *args], cwd=repo, env=git_env(), capture_output=True, text=True, check=True
    )
    return res.stdout


def list_candidates(repo: Path, head: str, package_dir: str, tests_dir: str) -> list[dict]:
    """Single-parent commits from `head` back that change library and test files, newest first."""
    fmt = f"{RECORD}%H{FIELD}%P{FIELD}%s{FIELD}%b{FIELD}"
    out = _git(repo, "log", "--no-merges", "--name-only", f"--format={fmt}", head)
    found = []
    for rec in out.split(RECORD)[1:]:
        sha, parents, subject, body, files = rec.split(FIELD)
        if len(parents.split()) != 1:
            continue
        split = classify_files([f for f in files.splitlines() if f], package_dir, tests_dir)
        if split:
            found.append(
                {
                    "sha": sha,
                    "parent": parents.strip(),
                    "subject": subject.strip(),
                    "body": body.strip(),
                    "lib_files": split[0],
                    "test_files": split[1],
                }
            )
    return found


def judge(before: Run, after: Run, before2: Run, after2: Run) -> tuple[str, list[str]]:
    """Status and fail-to-pass ids of a commit from two runs of the test files in each state.

    `before` = parent with the new tests, `after` = the commit. A test that fails in both states
    (a failure the sandbox's package versions cause) is not fail-to-pass.
    """
    if any(r.timed_out for r in (before, after, before2, after2)):
        return "timeout", []
    f2p = sorted(set(before.failed) - set(after.failed))
    if not f2p:
        return "no_fail_to_pass", []
    if after.passed == 0 or after2.passed == 0:
        return "nothing_passes_after", f2p
    if sorted(set(before2.failed) - set(after2.failed)) != f2p:
        return "flaky", f2p
    return "usable", f2p


def diff_of(repo: Path, parent: str, sha: str, files: list[str]) -> str:
    return _git(repo, "diff", "--no-ext-diff", "--no-color", parent, sha, "--", *files)


def materialise(repo: Path, rev: str, dest: Path) -> None:
    """Extract the tree of `rev` into `dest` (git archive; no repo code runs)."""
    arch = subprocess.run(
        ["git", "archive", rev], cwd=repo, env=git_env(), capture_output=True, check=True
    )
    with tarfile.open(fileobj=io.BytesIO(arch.stdout)) as tf:
        tf.extractall(dest, filter="data")


def apply_patch(tree: Path, patch: str) -> None:
    subprocess.run(
        [*GIT, "apply", "-"], cwd=tree, env=git_env(), input=patch, text=True, check=True
    )


def mine_candidate(repo: Path, c: dict, name: str, root: str, make_runner, out: Path) -> tuple:
    """(status, task or None) for one commit: build the task and verify it in the container."""
    patch = diff_of(repo, c["parent"], c["sha"], c["lib_files"])
    test_patch = diff_of(repo, c["parent"], c["sha"], c["test_files"])
    size = size_of(patch)
    if not 0 < size <= MAX_LIB_LINES or not test_patch:
        return "size_out_of_range", None
    iid = f"{name}__{c['sha'][:10]}"
    snap = out / "snapshots" / f"{iid}.tgz"
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "tree"
        tree.mkdir()
        try:
            materialise(repo, c["parent"], tree)
            base = commit_tree(tree, snap)
            apply_patch(tree, test_patch)
        except (subprocess.CalledProcessError, tarfile.TarError):
            snap.unlink(missing_ok=True)
            return "patch_does_not_apply", None
        files = [f for f in c["test_files"] if (tree / f).is_file()]
        if not files:
            snap.unlink(missing_ok=True)
            return "tests_deleted", None
        run = make_runner(tree, root)
        before, before2 = run(None, files), run(None, files)
        try:
            apply_patch(tree, patch)
        except subprocess.CalledProcessError:
            snap.unlink(missing_ok=True)
            return "patch_does_not_apply", None
        after, after2 = run(None, files), run(None, files)
    status, f2p = judge(before, after, before2, after2)
    if status != "usable":
        snap.unlink(missing_ok=True)
        return status, None
    task = {
        "instance_id": iid,
        "repo": f"synthetic/{name}",
        "base_commit": base,
        "patch": patch,
        "test_patch": test_patch,
        "problem_statement": clean_message(c["subject"], c["body"]),
        "hints_text": "",
        "created_at": CREATED_AT,
        "fail_to_pass": f2p,
    }
    return "usable", task


def ensure_full_clone(entry: dict, dest: Path) -> Path:
    """A full-history clone of the repo, with the pinned commit reachable."""
    if not dest.exists():
        subprocess.run(
            ["git", "clone", "--quiet", entry["url"], str(dest)],
            env=git_env(),
            check=True,
            timeout=1800,
        )
    _git(dest, "cat-file", "-e", entry["sha"] + "^{commit}")
    return dest


def mine_repo(entry: dict, clone: Path, limit: int, out: Path, timeout: int = 120):
    root = str(Path(entry["package_dir"]).parent)
    cands = list_candidates(clone, entry["sha"], entry["package_dir"], entry["tests_dir"])
    seen, built = Counter(), []
    for c in cands[:limit]:
        status, task = mine_candidate(
            clone, c, entry["name"], root, lambda tree, r: docker_runner(tree, r, timeout), out
        )
        seen[status] += 1
        if task:
            built.append(task)
    return built, {
        "repo": entry["name"],
        "candidates": len(cands),
        "tried": sum(seen.values()),
        "statuses": dict(seen),
        "tasks": len(built),
    }


def export_graphs(out: Path, tasks: list[dict], entries: dict[str, dict]) -> int:
    """Write graphs/ and embeddings/ for each task from its snapshot (the competition layout)."""
    for sub in ("graphs", "embeddings"):
        (out / sub).mkdir(exist_ok=True)
    for t in tasks:
        name = t["repo"].split("/", 1)[1]
        root = str(Path(entries[name]["package_dir"]).parent)
        with tempfile.TemporaryDirectory() as tmp:
            with tarfile.open(out / "snapshots" / f"{t['instance_id']}.tgz") as tf:
                tf.extractall(tmp, filter="data")
            files = read_tree(Path(tmp) / root)
        write_graph(out, name, t["base_commit"], files)
    return len(tasks)


def main(argv: list[str]) -> int:
    if argv[:1] == [
        "graphs"
    ]:  # python -m synthetic.mine graphs DIR: DIR has tasks.jsonl, snapshots/
        out = Path(argv[1])
        rows = [json.loads(ln) for ln in (out / "tasks.jsonl").read_text().splitlines() if ln]
        entries = {e["name"]: e for e in load_manifest()}
        print(f"graphs and embeddings for {export_graphs(out, rows, entries)} tasks")
        return 0
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("history", type=Path, help="folder for full-history clones")
    ap.add_argument("names", nargs="+")
    ap.add_argument("--max-commits", type=int, default=40, help="candidates tried per repo")
    ap.add_argument("--out", type=Path, default=Path("data/synthetic/s1"))
    a = ap.parse_args(argv)
    (a.out / "snapshots").mkdir(parents=True, exist_ok=True)
    a.history.mkdir(parents=True, exist_ok=True)
    tasks, summaries = [], []
    for e in (e for e in load_manifest() if e["name"] in a.names):
        clone = ensure_full_clone(e, a.history / e["name"])
        got, summary = mine_repo(e, clone, a.max_commits, a.out)
        tasks += got
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
        (a.out / "tasks.jsonl").write_text(  # after every repo: a crash keeps the finished ones
            "".join(json.dumps(t) + "\n" for t in tasks), encoding="utf-8"
        )
    report = {"repos": summaries, "shape": summarize(tasks) if tasks else {}}
    (a.out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report["shape"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
