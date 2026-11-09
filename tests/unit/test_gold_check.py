from types import SimpleNamespace

from analysis.gold_check import error_class, row, summarize


def res(resolved, text=""):
    return SimpleNamespace(repo="a/b", resolved=resolved, test_output=text, error=None)


def test_error_class_names_the_first_reason():
    assert error_class("E   ModuleNotFoundError: No module named 'x'\n1 error in 0.1s") == (
        "missing_module"
    )
    assert error_class("recursive dependency involving fixture 'httpbin'") == "fixture_error"
    assert error_class("2 failed, 5 passed") == "assertion"
    assert error_class("nothing recognisable") == "other"


def test_row_keeps_a_verdict_and_no_output():
    assert row(res(True)) == {"repo": "a/b", "resolved": True, "error": None}
    bad = row(res(False, "ModuleNotFoundError"))
    assert bad["resolved"] is False and bad["error"] == "missing_module"
    assert "ModuleNotFoundError" not in str(bad)


def test_summarize_counts_by_error():
    rows = [row(res(True)), row(res(False, "ModuleNotFoundError")), row(res(False, "3 failed"))]
    assert summarize(rows) == {
        "tasks": 3,
        "resolved": 1,
        "errors": {"missing_module": 1, "assertion": 1},
    }
