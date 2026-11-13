"""Stage 2b of the synthetic task set: turn usable mutants into runnable tasks.

A task is one mutant whose fail-to-pass tests are known (stage 2a, run_tests.py). It has the shape
of a competition task, and the tests stay hidden until grading, as in the real set:

    snapshots/<id>.tgz   the repo at the mutated state as a one-commit git repo, WITHOUT the test
                         files that hold the fail-to-pass tests; `base_commit` is that commit
    patch                the gold patch, mutated -> original, with repo-relative paths
    test_patch           a new-file patch that puts the removed test files back (the grader
                         applies it)
    problem_statement    a TEMPLATED bug report built from the operator's symptom, the failing
                         test's name and its assertion message; no model is involved.
                         `--issues FILE` swaps in model-written texts by instance_id;
                         `issue_requests.jsonl` holds the writer's prompts (ISSUE_PROMPT).

Graphs and embeddings come from export.write_graph. Only the Docker runner of run_tests.py executes
repo code; `git` is the only other program run, and only to commit and apply patches.
Usage: python -m synthetic.tasks CACHE_DIR [NAME ...] --n 10 --seed 0 [--leak 0.2] [--issues FILE]
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import shutil
import statistics
import subprocess
import tarfile
import tempfile
import time
from collections import Counter
from pathlib import Path

from synthetic.export import CREATED_AT, names_the_node, pick, problem_statement, write_graph
from synthetic.fetch import load_manifest
from synthetic.graph import read_tree
from synthetic.mutate import OPERATORS, reverse_patch
from synthetic.run_tests import baseline, docker_runner, evaluate, sample_mutants

ISSUE_PROMPT = """Write a short bug report (30 to 100 words) as a user of a Python library would.
What goes wrong: {symptom}
One of the library's own checks fails with: {reason}
The check is called: {phrase}
Rules: plain prose, no traceback, no code block, do not name any function, class, module or file,
do not say how to fix it. Reply with the bug report only."""
CONTEXT = [
    "I ran into this while using the library in a small project, and it behaves differently "
    "from what I relied on before.",
    "The documentation describes the opposite, and the same call used to work for me with "
    "other inputs, so I suspect a recent regression.",
    "It is easy to miss because most inputs still work; only some combinations give the wrong "
    "answer, which makes it hard to track down from my side.",
]
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_DATE": CREATED_AT,
    "GIT_COMMITTER_DATE": CREATED_AT,
}
GIT = ["git", "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.invalid"]
GIT += ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false"]
GOLD_FIELDS = ["instance_id", "gold_node", "gold_kind", "fell_back", "operator", "file"]
GOLD_EXTRA = ["sites", "gold_nodes", "fail_to_pass"]
WORDS = (30, 100)


def humanize_test(test_id: str) -> str:
    """'tests/t.py::test_split_by_comma[a-1]' -> 'split by comma'."""
    name = test_id.rpartition("::")[2].split("[")[0]
    return re.sub(r"[_\s]+", " ", re.sub(r"^test_?", "", name)).strip()


def observed_expected(reason: str) -> tuple[str, str] | None:
    """(observed, expected) from a short pytest reason such as 'assert 3 == 4', else None."""
    m = re.search(r"assert (.+?) == (.+)", reason)
    if not m or "..." in reason:
        return None
    left, right = m.group(1).strip(), m.group(2).strip()
    return (left, right) if 0 < len(left) <= 40 and 0 < len(right) <= 40 else None


def _short_name(rec: dict) -> str:
    return rec["gold_node"].rpartition(".")[2].lower()


def _flat(s: str) -> str:
    return re.sub(r"[_\s]+", " ", s.lower()).strip()


def _names(text: str, word: str) -> bool:
    """Whether `text` names `word`, counting 'is_big' and 'is big' as the same name."""
    return bool(_flat(word)) and bool(
        re.search(rf"(?<![a-z0-9]){re.escape(_flat(word))}(?![a-z0-9])", _flat(text))
    )


def issue_text(rec: dict, reasons: dict, leak: float) -> tuple[str, list[str]]:
    """The templated bug report for a task and the problems found in it (empty when it is clean).

    The symptom comes from the operator; the extra sentences from the first failing test. An extra
    that names the node, the module or the file is dropped; a leak is allowed only by the planned
    `leak` share, which sits in the symptom text itself.
    """
    base = problem_statement(rec, leak)
    extras: list[str] = [pick(CONTEXT, "c:" + rec["id"])]
    test_id = sorted(reasons)[0] if reasons else ""
    phrase = humanize_test(test_id)
    avoid = [_short_name(rec), rec["module"].rpartition(".")[2].lower(), Path(rec["file"]).stem]
    if (
        1 <= len(phrase.split()) <= 8
        and len(phrase) >= 4
        and not any(_names(phrase, w) for w in avoid)
    ):
        extras.append(f"It affects the behaviour described as “{phrase}”.")
    why = reasons.get(test_id, "")
    pair = observed_expected(why)
    exc = re.match(r"(\w+(?:Error|Exception))\b", why.replace("AssertionError: ", ""))
    if pair:
        extras.append(f"For example, one case gives `{pair[0]}` where `{pair[1]}` is expected.")
    elif exc and exc.group(1) != "AssertionError":
        extras.append(f"One call now fails with `{exc.group(1)}`.")
    extras = [e for e in extras if not any(_names(e, w) for w in avoid)]
    text = " ".join([base, *extras])
    problems = issue_problems(text, rec)
    return (text, []) if not problems else (base, problems)


def issue_problems(text: str, rec: dict) -> list[str]:
    """Leaks and length problems of an issue text (the planned node name is not a problem)."""
    out = []
    for line in rec["gold_patch"].splitlines():
        body = line[1:].strip()
        if line[:1] in "+-" and not line.startswith(("+++", "---")) and len(body) >= 8:
            if body in text:
                out.append("patch line")
                break
    if any(op in text.lower() for op in OPERATORS):
        out.append("operator name")
    if not WORDS[0] <= len(text.split()) <= WORDS[1]:
        out.append("length")
    return out


def issue_request(rec: dict, reasons: dict) -> dict:
    """The prompt a model-written issue would be generated from (no diff, no node name)."""
    test_id = sorted(reasons)[0] if reasons else ""
    return {
        "instance_id": rec["instance_id"],
        "prompt": ISSUE_PROMPT.format(
            symptom=problem_statement({**rec, "id": rec["id"]}),
            reason=reasons.get(test_id, "an assertion"),
            phrase=humanize_test(test_id) or "unknown",
        ),
    }


def new_file_patch(path: str, text: str) -> str:
    """A git-style patch that creates `path` with `text`."""
    body = []
    for line in difflib.unified_diff([], text.splitlines(keepends=True), "/dev/null", f"b/{path}"):
        body.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return f"diff --git a/{path} b/{path}\nnew file mode 100644\n" + "".join(body)


def git_env() -> dict:
    """The environment for git: no inherited GIT_* variables (a git hook sets GIT_DIR, which would
    point `git init` and `git commit` at the caller's repository), plus our fixed dates."""
    return {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, **GIT_ENV}


def _git(tree: Path, *args: str, stdin: str | None = None) -> str:
    res = subprocess.run(
        [*GIT, *args],
        cwd=tree,
        env=git_env(),
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def write_snapshot(repo: Path, rel_file: str, mutated: str, drop: list[str], dest: Path) -> str:
    """Write the task snapshot to `dest` and return its base commit (a fresh one-commit repo)."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "tree"
        shutil.copytree(repo, tree, ignore=shutil.ignore_patterns(".git"), symlinks=True)
        (tree / rel_file).write_text(mutated, encoding="utf-8")
        for name in drop:
            (tree / name).unlink()
        _git(tree, "init", "-q")
        _git(tree, "add", "-A")
        _git(tree, "commit", "-q", "-m", "base")
        sha = _git(tree, "rev-parse", "HEAD")
        with tarfile.open(dest, "w:gz") as tf:
            tf.add(tree, arcname=".")
    return sha


def verify(task: dict, fail_to_pass: list[str], snapshot: Path, import_root: str, make_runner):
    """The grader's steps on the exported files: tests in, tests fail; gold patch in, tests pass."""
    files = sorted({i.split("::")[0] for i in fail_to_pass})
    ids = set(fail_to_pass)
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "tree"
        tree.mkdir()
        with tarfile.open(snapshot) as tf:
            tf.extractall(tree, filter="data")
        _git(tree, "apply", "-", stdin=task["test_patch"])
        before = make_runner(tree, import_root)(None, files)
        _git(tree, "apply", "-", stdin=task["patch"])
        after = make_runner(tree, import_root)(None, files)
    return {
        "fails_before": not before.timed_out and ids <= set(before.failed),
        "passes_after": not after.timed_out and after.passed > 0 and not ids & set(after.failed),
        "seconds": round(time.time() - t0, 1),
    }


def make_task(rec, row, repo, root, tests_dir, name, index, out, files, leak, make_runner):
    """Build one task (snapshot, graph, embeddings) from a usable mutant, or (None, why)."""
    f2p = row["fail_to_pass"]
    test_files = sorted({i.split("::")[0] for i in f2p})
    if not all(f.endswith(".py") and f.startswith(tests_dir + "/") for f in test_files):
        return None, "fail-to-pass test outside the tests dir"
    rel = (Path(root) / rec["file"]).as_posix()
    original = (repo / rel).read_text(encoding="utf-8", errors="replace")
    dropped = {f: (repo / f).read_text(encoding="utf-8", errors="replace") for f in test_files}
    iid = f"{name}_{index:05d}"
    snap = out / "snapshots" / f"{iid}.tgz"
    base = write_snapshot(repo, rel, rec["mutated_text"], test_files, snap)
    task_files = {**files, rec["file"]: rec["mutated_text"]}
    nodes, edges = write_graph(out, name, base, task_files)
    rec = {
        **rec,
        "instance_id": iid,
        "gold_patch": reverse_patch(original, rec["mutated_text"], rel),
    }
    text, problems = issue_text(rec, row.get("reasons", {}), leak)
    task = {
        "instance_id": iid,
        "repo": f"synthetic/{name}",
        "base_commit": base,
        "patch": rec["gold_patch"],
        "test_patch": "".join(new_file_patch(f, t) for f, t in dropped.items()),
        "problem_statement": text,
        "hints_text": "",
        "created_at": CREATED_AT,
    }
    check = verify(task, f2p, snap, root, make_runner) if make_runner else {}
    meta = {"rec": rec, "f2p": f2p, "reasons": row.get("reasons", {}), "problems": problems}
    meta |= {"nodes": nodes, "edges": edges, **check}
    return (task, meta), ""


def load_issues(path: Path | None) -> dict:
    """{instance_id: text} from a JSONL of model-written issue texts."""
    if not path:
        return {}
    rows = (json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines())
    return {r["instance_id"]: r["problem_statement"] for r in rows}


def run_repo(
    entry: dict, cache: Path, n: int, seed: int, out: Path, leak: float, check: bool, sites: int = 1
):
    repo = cache / entry["name"]
    root, recs = sample_mutants(repo, entry, n, seed, sites)
    tests = entry["tests_dir"]
    run = docker_runner(repo, root)
    base = baseline(run, tests)
    summary = {"repo": entry["name"], "mutants": len(recs), "suite_s": base["seconds"]}
    if base["timed_out"] or base["pass_rate"] < 0.9:
        return [], {**summary, "rejected": f"baseline pass rate {base['pass_rate']}"}
    fast = docker_runner(repo, root, timeout=min(120, max(20, int(8 * base["seconds"]))))
    files = read_tree(repo / root)
    t0 = time.time()
    statuses, skipped, built = Counter(), Counter(), []

    def make_runner(tree, import_root):
        return docker_runner(tree, import_root, timeout=min(240, max(60, int(8 * base["seconds"]))))

    for rec in recs:
        row = evaluate(rec, fast, root, tests, repo, base["bad"])
        statuses[row["status"]] += 1
        if row["status"] != "usable":
            continue
        made, why = make_task(
            rec,
            row,
            repo,
            root,
            tests,
            entry["name"],
            len(built),
            out,
            files,
            leak,
            make_runner if check else None,
        )
        if made:
            built.append(made)
        else:
            skipped[why] += 1
    summary.update(
        statuses=dict(statuses),
        skipped=dict(skipped),
        tasks=len(built),
        seconds=round(time.time() - t0, 1),
    )
    return built, summary


def quality(built: list, leak: float) -> dict:
    """Aggregates over the built tasks: leaks, duplicates, difficulty spread, per-repo counts."""
    tasks = [t for t, _ in built]
    metas = [m for _, m in built]
    texts = [t["problem_statement"] for t in tasks]
    changed = [
        sum(
            1
            for line in t["patch"].splitlines()
            if line[:1] in "+-" and line[:3] not in ("+++", "---")
        )
        for t in tasks
    ]
    named = sum(bool(_names(t, _short_name(m["rec"]))) for t, m in zip(texts, metas, strict=True))
    return {
        "tasks": len(tasks),
        "per_repo": dict(Counter(t["repo"] for t in tasks)),
        "unique_texts": len(set(texts)),
        "words_median": statistics.median(len(t.split()) for t in texts) if texts else 0,
        "text_fell_back_to_symptom": sum(bool(m["problems"]) for m in metas),
        "problems": dict(Counter(p for m in metas for p in m["problems"])),
        "names_the_node": named,
        "planned_to_name_the_node": sum(names_the_node(m["rec"], leak) for m in metas),
        "gold_lines_changed": {
            "min": min(changed, default=0),
            "median": statistics.median(changed) if changed else 0,
            "max": max(changed, default=0),
        },
        "gold_nodes_per_task": statistics.median(
            len(set(m["rec"].get("gold_nodes", [m["rec"]["gold_node"]]))) for m in metas
        )
        if metas
        else 0,
        "sites_per_task": statistics.median(m["rec"].get("sites", 1) for m in metas)
        if metas
        else 0,
        "fail_to_pass_median": statistics.median(len(m["f2p"]) for m in metas) if metas else 0,
        "verified": sum(bool(m.get("fails_before") and m.get("passes_after")) for m in metas),
        "verify_failed": sum(
            "fails_before" in m and not (m["fails_before"] and m["passes_after"]) for m in metas
        ),
        "mean_nodes": round(statistics.mean(m["nodes"] for m in metas), 1) if metas else 0,
    }


def write_bundle(built: list, out: Path, issues: dict) -> None:
    rows = []
    for task, _ in built:
        task["problem_statement"] = issues.get(task["instance_id"], task["problem_statement"])
        rows.append(task)
    (out / "tasks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with open(out / "gold_nodes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, [*GOLD_FIELDS, *GOLD_EXTRA])
        w.writeheader()
        for task, m in built:
            w.writerow(
                {
                    **{k: m["rec"][k] for k in GOLD_FIELDS if k != "instance_id"},
                    "instance_id": task["instance_id"],
                    "sites": m["rec"].get("sites", 1),
                    "gold_nodes": ";".join(m["rec"].get("gold_nodes", [m["rec"]["gold_node"]])),
                    "fail_to_pass": ";".join(m["f2p"]),
                }
            )
    reqs = (issue_request(m["rec"], m["reasons"]) for _, m in built)
    (out / "issue_requests.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in reqs), encoding="utf-8"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m synthetic.tasks", description=__doc__)
    ap.add_argument("cache", type=Path)
    ap.add_argument("names", nargs="*")
    ap.add_argument("--n", type=int, default=10, help="mutants per repo")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--sites", type=int, default=1, help="bugs per task, in different nodes of one file"
    )
    ap.add_argument("--leak", type=float, default=0.2, help="share of issues that name the node")
    ap.add_argument("--issues", type=Path, help="JSONL {instance_id, problem_statement}")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("data/synthetic/stage2b"))
    a = ap.parse_args(argv)
    for sub in ("graphs", "embeddings", "snapshots"):
        (a.out / sub).mkdir(parents=True, exist_ok=True)
    entries = [
        e
        for e in load_manifest()
        if (a.cache / e["name"]).is_dir() and (not a.names or e["name"] in a.names)
    ]
    built, summaries = [], []
    for e in entries:  # one repo, one container at a time
        got, summary = run_repo(
            e, a.cache.resolve(), a.n, a.seed, a.out, a.leak, not a.no_verify, a.sites
        )
        built += got
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    write_bundle(built, a.out, load_issues(a.issues))
    report = {"repos": summaries, "quality": quality(built, a.leak)}
    (a.out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report["quality"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
