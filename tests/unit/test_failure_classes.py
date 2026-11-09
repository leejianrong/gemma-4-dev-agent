from analysis.failure_classes import classify, patch_files

P = "diff --git a/lib/a.py b/lib/a.py\n+x\n"


def row(status):
    return {"status": status}


def test_patch_files_reads_diff_headers():
    assert patch_files(P) == {"lib/a.py"}


def test_status_decides_before_the_patch_is_read():
    assert classify(row("resolved"), P, "", {"lib/a.py"}) == "resolved"
    assert classify(row("error"), P, "", {"lib/a.py"}) == "timeout"
    assert classify(row("tool_budget"), "", "", {"lib/a.py"}) == "budget_no_patch"
    assert classify(row("empty_patch"), "", "", {"lib/a.py"}) == "no_patch"


def test_patch_in_the_wrong_file():
    assert classify(row("unresolved"), P, "", {"lib/b.py"}) == "wrong_file"


def test_broken_import_beats_a_clean_summary():
    assert classify(row("unresolved"), P, "E SyntaxError: bad", {"lib/a.py"}) == "broke_code"


def test_missing_test_module_is_inconclusive_unless_an_assertion_failed():
    log = "E ModuleNotFoundError: dirty_equals\n1 error in 0.5s"
    assert classify(row("unresolved"), P, log, {"lib/a.py"}) == "inconclusive"
    assert classify(row("unresolved"), P, log + "\n2 failed", {"lib/a.py"}) == "wrong_fix"
