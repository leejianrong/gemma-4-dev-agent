import subprocess
from pathlib import Path

from synthetic.mine import classify_files, clean_message, list_candidates, size_of
from synthetic.tasks import GIT, git_env


def test_classify_files_needs_a_library_file_and_a_test_file():
    got = classify_files(["src/lib/a.py", "tests/test_a.py", "CHANGES.rst"], "src/lib", "tests")
    assert got == (["src/lib/a.py"], ["tests/test_a.py"])
    assert classify_files(["src/lib/a.py", "CHANGES.rst"], "src/lib", "tests") is None
    assert classify_files(["tests/test_a.py"], "src/lib", "tests") is None
    # files outside the package and the tests dir (setup.py, docs, changelog) are left out
    assert classify_files(["src/lib/a.py", "tests/test_a.py", "setup.py"], "src/lib", "tests") == (
        ["src/lib/a.py"],
        ["tests/test_a.py"],
    )
    assert classify_files(["src/lib/a.txt", "tests/test_a.py"], "src/lib", "tests") is None


def test_clean_message_drops_issue_links_and_trailers_but_keeps_the_story():
    text = clean_message(
        "Fix quoting of empty values (#412)",
        "Empty strings were dropped.\n\nFixes #409\nSee https://example.com/x\n"
        "Co-authored-by: A B <a@b.c>\nSigned-off-by: C <c@d.e>",
    )
    assert text == "Fix quoting of empty values\n\nEmpty strings were dropped."


def test_size_of_counts_changed_lines():
    assert size_of("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n+c\n") == 3


def _commit(repo: Path, msg: str):
    env = git_env()
    subprocess.run([*GIT, "add", "-A"], cwd=repo, env=env, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", msg], cwd=repo, env=env, check=True)


def test_list_candidates_finds_commits_that_change_library_and_tests(tmp_path):
    env = git_env()
    subprocess.run([*GIT, "init", "-q", "-b", "main"], cwd=tmp_path, env=env, check=True)
    (tmp_path / "lib").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "lib" / "a.py").write_text("x = 1\n")
    _commit(tmp_path, "first")
    (tmp_path / "lib" / "a.py").write_text("x = 2\n")
    (tmp_path / "tests" / "test_a.py").write_text("def test_x(): pass\n")
    _commit(tmp_path, "Fix x\n\nbody")
    (tmp_path / "lib" / "a.py").write_text("x = 3\n")
    _commit(tmp_path, "library only")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, env=env, capture_output=True, text=True
    ).stdout.strip()
    got = list_candidates(tmp_path, head, "lib", "tests")
    assert len(got) == 1
    c = got[0]
    assert c["lib_files"] == ["lib/a.py"] and c["test_files"] == ["tests/test_a.py"]
    assert c["subject"] == "Fix x" and c["body"] == "body" and len(c["parent"]) == 40


def _run(passed=3, failed=(), timed_out=False):
    from synthetic.run_tests import Run

    return Run(passed, frozenset(failed), 1.0, timed_out)


def test_judge_keeps_commits_whose_new_tests_fail_before_and_pass_after_twice():
    from synthetic.mine import judge

    before, after = _run(failed={"t.py::a", "t.py::b"}), _run(failed={"t.py::old"})
    status, f2p = judge(before, after, before, after)
    assert (status, f2p) == ("usable", ["t.py::a", "t.py::b"])  # t.py::old fails both times


def test_judge_names_why_a_commit_is_dropped():
    from synthetic.mine import judge

    ok = _run()
    assert judge(ok, ok, ok, ok)[0] == "no_fail_to_pass"
    assert judge(_run(timed_out=True), ok, ok, ok)[0] == "timeout"
    assert judge(_run(failed={"a"}), _run(passed=0), _run(failed={"a"}), _run(passed=0))[0] == (
        "nothing_passes_after"
    )
    assert judge(_run(failed={"a"}), ok, _run(failed={"a", "b"}), ok)[0] == "flaky"


def test_mine_candidate_builds_a_verified_task_from_a_commit(tmp_path):
    import json
    import tarfile

    from synthetic.mine import mine_candidate

    repo = tmp_path / "repo"
    repo.mkdir()
    env = git_env()
    subprocess.run([*GIT, "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
    (repo / "lib").mkdir()
    (repo / "tests").mkdir()
    (repo / "lib" / "a.py").write_text("x = 1\n")
    (repo / "tests" / "test_a.py").write_text("def test_x(): pass\n")
    _commit(repo, "first")
    (repo / "lib" / "a.py").write_text("x = 2\n")
    (repo / "tests" / "test_a.py").write_text("def test_x(): assert True\n# new\n")
    _commit(repo, "Fix x (#3)\n\nx was wrong.\n\nFixes #2")
    (cand,) = list_candidates(repo, "HEAD", "lib", "tests")

    def make_runner(tree, root):
        from synthetic.run_tests import Run

        def run(mut, files):  # the fake "tests" fail until the library has the fix
            fixed = (tree / "lib" / "a.py").read_text() == "x = 2\n"
            assert files == ["tests/test_a.py"]
            return Run(
                1 if fixed else 0, frozenset() if fixed else {files[0] + "::test_x"}, 1, False
            )

        return run

    out = tmp_path / "out"
    (out / "snapshots").mkdir(parents=True)
    status, task = mine_candidate(repo, cand, "demo", "lib/..", make_runner, out)
    assert status == "usable"
    assert task["problem_statement"] == "Fix x\n\nx was wrong."
    assert task["fail_to_pass"] == ["tests/test_a.py::test_x"]
    assert "x = 2" in task["patch"] and "+# new" in task["test_patch"]
    with tarfile.open(out / "snapshots" / f"{task['instance_id']}.tgz") as tf:
        assert tf.extractfile("./lib/a.py").read() == b"x = 1\n"  # the parent state
    json.dumps(task)


def test_classify_files_keeps_tests_inside_the_package_out_of_the_library_part():
    got = classify_files(["lib/a.py", "lib/tests/test_a.py"], "lib", "lib/tests")
    assert got == (["lib/a.py"], ["lib/tests/test_a.py"])
    assert classify_files(["lib/tests/test_a.py"], "lib", "lib/tests") is None


def test_export_graphs_writes_a_graph_and_embeddings_per_mined_task(tmp_path):
    import tarfile

    from synthetic.mine import export_graphs
    from synthetic.tasks import commit_tree

    tree = tmp_path / "tree"
    (tree / "lib").mkdir(parents=True)
    (tree / "lib" / "a.py").write_text("def f(x):\n    return g(x)\n\n\ndef g(x):\n    return x\n")
    out = tmp_path / "out"
    (out / "snapshots").mkdir(parents=True)
    base = commit_tree(tree, out / "snapshots" / "demo__abc.tgz")
    task = {"instance_id": "demo__abc", "repo": "synthetic/demo", "base_commit": base}
    entries = {"demo": {"name": "demo", "package_dir": "lib"}}
    assert export_graphs(out, [task], entries) == 1
    assert (out / "graphs" / f"demo_{base}.json").is_file()
    assert (out / "embeddings" / f"demo_{base}.npz").is_file()
    assert tarfile.is_tarfile(out / "snapshots" / "demo__abc.tgz")
