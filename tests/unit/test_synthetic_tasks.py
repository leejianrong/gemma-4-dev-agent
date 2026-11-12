"""Stage 2b: runnable synthetic tasks, on a toy repo with a fake runner (no Docker, no network)."""

import csv
import json
import subprocess
import tarfile

from synthetic import mutate
from synthetic.run_tests import Run, evaluate, failure_reasons
from synthetic.tasks import (
    humanize_test,
    issue_problems,
    issue_request,
    issue_text,
    load_issues,
    make_task,
    new_file_patch,
    observed_expected,
    quality,
    verify,
    write_bundle,
    write_snapshot,
)

CORE = "def is_big(x):\n    if x > 10:\n        return True\n    return False\n"
TEST = "from pkg.core import is_big\n\n\ndef test_is_big_limit():\n    assert is_big(11)\n"
F2P = "tests/test_core.py::test_is_big_limit"


def toy_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pkg" / "__init__.py").write_text("")
    (repo / "pkg" / "core.py").write_text(CORE)
    (repo / "tests" / "test_core.py").write_text(TEST)
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return repo


def a_record(repo):
    return mutate.generate(repo, n=1, seed=0, repo="toy", commit="abc")[0]


def fake_factory(original):
    """A runner that fails the test while core.py differs from the original and the test exists."""

    def make_runner(tree, import_root):
        def run(mut, args):
            present = (tree / "tests" / "test_core.py").is_file()
            broken = (tree / "pkg" / "core.py").read_text() != original
            failed = frozenset({F2P}) if present and broken else frozenset()
            return Run(0 if failed else 1, failed, 0.1, False)

        return run

    return make_runner


def test_failure_reasons_pairs_each_id_with_its_short_reason():
    out = "FAILED tests/a.py::test_x - assert 3 == 4\nERROR tests/b.py - ImportError\n1 failed\n"
    assert failure_reasons(out) == {
        "tests/a.py::test_x": "assert 3 == 4",
        "tests/b.py": "ImportError",
    }


def test_evaluate_rows_carry_the_reasons_of_the_failing_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    runs = iter(
        [
            Run(9, frozenset({"t::a"}), 0.1, False, (("t::a", "assert 1 == 2"),)),
            Run(9, frozenset({"t::a"}), 0.1, False),
        ]
    )
    rec = {"id": "m", "file": "p.py", "module": "p", "mutated_text": "x = 1\n"}
    row = evaluate(rec, lambda mut, args: next(runs), "src", "tests", tmp_path, set())
    assert row["status"] == "usable" and row["reasons"] == {"t::a": "assert 1 == 2"}


def test_humanize_and_observed_expected():
    assert humanize_test("tests/t.py::test_split_by_comma[a-1]") == "split by comma"
    assert observed_expected("AssertionError: assert 3 == 4") == ("3", "4")
    assert observed_expected("assert 'a' == 'b'") == ("'a'", "'b'")
    assert observed_expected("assert " + "x" * 60 + " == 1") is None
    assert observed_expected("ValueError: boom") is None


def record(**over):
    rec = {
        "id": "toy__core__10__cmp_swap",
        "operator": "cmp_swap",
        "gold_node": "pkg.core.is_big",
        "module": "pkg.core",
        "file": "pkg/core.py",
        "gold_patch": "diff --git a/pkg/core.py b/pkg/core.py\n-    if x >= 10:\n+    if x > 10:\n",
    }
    return {**rec, **over}


def test_issue_text_uses_the_failing_test_and_never_leaks_by_accident():
    reasons = {"tests/t.py::test_inputs_over_the_limit": "assert False == True"}
    text, problems = issue_text(record(), reasons, leak=0.0)
    assert not problems and 30 <= len(text.split()) <= 100
    assert "inputs over the limit" in text and "`False` where `True` is expected" in text
    assert "is_big" not in text and "cmp_swap" not in text


def test_a_test_name_that_names_the_node_is_dropped_from_the_text():
    reasons = {"tests/t.py::test_is_big_when_over_ten": "assert False == True"}
    text, _ = issue_text(record(), reasons, leak=0.0)
    assert "is big" not in text and "is_big" not in text


def test_planned_leak_names_the_node_only_for_that_share():
    reasons = {"tests/t.py::test_limit_check": "ValueError: bad"}
    ids = [record(id=f"x{i}") for i in range(200)]
    named = sum("`is_big`" in issue_text(r, reasons, leak=0.2)[0] for r in ids)
    assert 20 <= named <= 60
    assert not any("`is_big`" in issue_text(r, reasons, leak=0.0)[0] for r in ids)


def test_issue_problems_flags_a_patch_line_an_operator_name_and_a_short_text():
    long = " ".join(["word"] * 40)
    assert issue_problems(long, record()) == []
    assert "patch line" in issue_problems(long + " if x >= 10:", record())
    assert "operator name" in issue_problems(long + " cmp_swap", record())
    assert "length" in issue_problems("too short", record())


def test_new_file_patch_creates_the_file_including_a_missing_final_newline(tmp_path):
    for text in ("a = 1\nb = 2\n", "a = 1\nb = 2"):
        out = tmp_path / ("x" if text.endswith("\n") else "y")
        out.mkdir()
        subprocess.run(
            ["git", "apply", "-"],
            cwd=out,
            input=new_file_patch("t/new.py", text),
            text=True,
            check=True,
        )
        assert (out / "t" / "new.py").read_text() == text


def test_snapshot_hides_the_test_file_and_is_a_deterministic_one_commit_repo(tmp_path):
    repo = toy_repo(tmp_path)
    mutated = CORE.replace("> 10", ">= 10")
    sha1 = write_snapshot(repo, "pkg/core.py", mutated, ["tests/test_core.py"], tmp_path / "a.tgz")
    sha2 = write_snapshot(repo, "pkg/core.py", mutated, ["tests/test_core.py"], tmp_path / "b.tgz")
    assert len(sha1) == 40 and sha1 == sha2
    with tarfile.open(tmp_path / "a.tgz") as tf:
        names = tf.getnames()
        assert "./pkg/core.py" in names and "./.git/HEAD" in names
        assert "./tests/test_core.py" not in names
        assert tf.extractfile("./pkg/core.py").read().decode() == mutated


def test_make_task_builds_a_task_the_grader_steps_accept(tmp_path):
    repo, out = toy_repo(tmp_path), tmp_path / "out"
    for sub in ("graphs", "embeddings", "snapshots"):
        (out / sub).mkdir(parents=True)
    rec = a_record(repo)
    row = {"fail_to_pass": [F2P], "reasons": {F2P: "assert False == True"}}
    files = {"pkg/core.py": CORE, "pkg/__init__.py": ""}
    made, why = make_task(
        rec, row, repo, ".", "tests", "toy", 0, out, files, 0.0, fake_factory(CORE)
    )
    task, meta = made
    assert why == "" and task["instance_id"] == "toy_00000" and task["repo"] == "synthetic/toy"
    assert set(task) == {"instance_id", "repo", "base_commit", "patch", "test_patch",
                         "problem_statement", "hints_text", "created_at"}  # fmt: skip
    assert (
        task["patch"].startswith("diff --git a/pkg/core.py")
        and "tests/test_core.py" in task["test_patch"]
    )
    assert meta["fails_before"] and meta["passes_after"]
    assert (out / "graphs" / f"toy_{task['base_commit']}.json").is_file()
    assert (out / "snapshots" / "toy_00000.tgz").is_file()


def test_verify_reports_a_gold_patch_that_does_not_fix_the_task(tmp_path):
    repo, out = toy_repo(tmp_path), tmp_path / "out"
    for sub in ("graphs", "embeddings", "snapshots"):
        (out / sub).mkdir(parents=True)
    rec = a_record(repo)
    row = {"fail_to_pass": [F2P], "reasons": {}}
    (task, _), _ = make_task(rec, row, repo, ".", "tests", "toy", 0, out, {}, 0.0, None)
    wrong = fake_factory(CORE + "# not what the patch gives\n")
    res = verify(task, [F2P], out / "snapshots" / "toy_00000.tgz", ".", wrong)
    assert res["fails_before"] and not res["passes_after"]


def test_a_failing_test_outside_the_tests_dir_is_not_exported(tmp_path):
    repo, out = toy_repo(tmp_path), tmp_path / "out"
    made, why = make_task(
        a_record(repo),
        {"fail_to_pass": ["pkg/core.py::doc"]},
        repo,
        ".",
        "tests",
        "toy",
        0,
        out,
        {},
        0.0,
        None,
    )
    assert made is None and "outside" in why


def test_bundle_files_issues_override_and_quality(tmp_path):
    repo, out = toy_repo(tmp_path), tmp_path / "out"
    for sub in ("graphs", "embeddings", "snapshots"):
        (out / sub).mkdir(parents=True)
    row = {"fail_to_pass": [F2P], "reasons": {F2P: "assert False == True"}}
    made, _ = make_task(a_record(repo), row, repo, ".", "tests", "toy", 0, out, {}, 0.0, None)
    write_bundle([made], out, {"toy_00000": "A model-written report."})
    tasks = [json.loads(line) for line in (out / "tasks.jsonl").read_text().splitlines()]
    assert tasks[0]["problem_statement"] == "A model-written report."
    gold = list(csv.DictReader(open(out / "gold_nodes.csv")))
    assert gold[0]["fail_to_pass"] == F2P and gold[0]["gold_node"].startswith("pkg.core")
    req = json.loads((out / "issue_requests.jsonl").read_text().splitlines()[0])
    assert req == issue_request(made[1]["rec"], row["reasons"]) and "is_big" not in req["prompt"]
    assert "cmp_swap" not in req["prompt"] and "x >" not in req["prompt"]
    q = quality([made], 0.0)
    assert (
        q["tasks"] == 1 and q["gold_nodes_per_task"] == 1 and q["per_repo"] == {"synthetic/toy": 1}
    )
    assert load_issues(None) == {}
