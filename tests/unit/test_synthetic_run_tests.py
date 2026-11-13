from synthetic.run_tests import Run, baseline, classify, evaluate, files_naming_module, parse_pytest

OUT = """FAILED tests/test_a.py::test_x[1 - 2] - assert 1 == 2
FAILED tests/test_b.py::test_y - boom
ERROR tests/test_c.py - ImportError
3 failed, 120 passed, 1 skipped in 1.23s
"""


def run(*ids, timed_out=False):
    return Run(10, frozenset(ids), 0.1, timed_out)


def test_parse_pytest_reads_ids_and_passed_count():
    passed, ids = parse_pytest(OUT)
    assert passed == 120
    assert ids == {"tests/test_a.py::test_x[1", "tests/test_b.py::test_y", "tests/test_c.py"}


def test_classify_outcomes():
    bad = {"pre_existing"}
    assert classify(bad, run("pre_existing"), None) == ("equivalent", [])
    assert classify(bad, run(timed_out=True), None) == ("timeout", [])
    assert classify(bad, run("a", "pre_existing"), run("a")) == ("usable", ["a"])
    assert classify(bad, run("a"), run("a", "b")) == ("flaky", ["a"])
    assert classify(bad, run(*"abcdef"), run(*"abcdef"))[0] == "too_broad"


def test_baseline_marks_tests_that_fail_in_some_runs_as_flaky():
    runs = iter([run("a", "b"), run("a"), run("a", "c")])
    base = baseline(lambda mut, args: next(runs), "tests")
    assert base["bad"] == {"a", "b", "c"} and base["flaky"] == 2


def test_files_naming_module_matches_the_module_by_name(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_one.py").write_text("from pkg.core import f\n")
    (tmp_path / "tests" / "test_two.py").write_text("import pkg\n")
    (tmp_path / "tests" / "test_three.py").write_text("from pkg import core\n")
    assert files_naming_module(tmp_path, "tests", "pkg.core") == [
        "tests/test_one.py",
        "tests/test_three.py",
    ]


def fake(results):
    calls = []

    def runner(mut, args):
        calls.append(args)
        return results.pop(0)

    return runner, calls


REC = {"id": "m1", "file": "pkg/core.py", "module": "pkg.core", "mutated_text": "x = 1\n"}


def test_evaluate_runs_targeted_then_full_then_confirms(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_one.py").write_text("import pkg.core\n")
    runner, calls = fake([run("t1"), run("t1"), run("t1")])
    row = evaluate(REC, runner, "src", "tests", tmp_path, set())
    assert row["status"] == "usable" and row["fail_to_pass"] == ["t1"]
    assert calls == [["tests/test_one.py"], ["tests"], ["t1"]]


def test_evaluate_skips_the_full_run_when_the_targeted_run_is_too_broad(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_one.py").write_text("import pkg.core\n")
    runner, calls = fake([run(*"abcdef")])
    row = evaluate(REC, runner, "src", "tests", tmp_path, set())
    assert row["status"] == "too_broad" and len(calls) == 1


def test_a_multi_site_mutant_may_fail_up_to_ten_tests_and_a_single_one_only_five(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_one.py").write_text("import pkg.core\n")
    ids = [f"t{i}" for i in range(8)]
    runner, _ = fake([run(*ids), run(*ids), run(*ids)])
    row = evaluate({**REC, "operator": "multi"}, runner, "src", "tests", tmp_path, set())
    assert row["status"] == "usable" and len(row["fail_to_pass"]) == 8
    runner, _ = fake([run(*ids)])
    row = evaluate({**REC, "operator": "cmp_swap"}, runner, "src", "tests", tmp_path, set())
    assert row["status"] == "too_broad"
