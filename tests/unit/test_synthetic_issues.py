from synthetic.issues import apply_issues, build_requests, changed_names, check_text, may_name

PATCH = """diff --git a/lib/a.py b/lib/a.py
--- a/lib/a.py
+++ b/lib/a.py
@@ -10,3 +10,4 @@ class Parser:
     keep
-    def split_values(self, s):
+    def split_values(self, s, sep=","):
+        return 1
@@ -40,2 +41,2 @@ def format_item(x):
-    y = 1
+    y = 2
"""
TASK = {
    "instance_id": "demo__abc",
    "patch": PATCH,
    "problem_statement": "Fix empty values in split (#3)\n\nEmpty strings were dropped.",
    "fail_to_pass": ["tests/test_a.py::test_split_empty_values[x-1]"],
}


def test_changed_names_come_from_hunk_headers_and_defs_in_the_patch():
    assert changed_names(PATCH) == ["Parser", "split_values", "format_item"]


def test_may_name_is_a_stable_share_of_the_ids():
    ids = [f"t{i}" for i in range(2000)]
    share = sum(may_name(i, 0.2) for i in ids) / len(ids)
    assert 0.15 < share < 0.25 and may_name("t1", 0.2) == may_name("t1", 0.2)
    assert not any(may_name(i, 0) for i in ids)


def test_requests_carry_the_message_and_test_phrase_but_never_the_diff():
    (req,) = build_requests([TASK], leak=0)
    assert "Empty strings were dropped" in req["prompt"] and "split empty values" in req["prompt"]
    assert "split_values" not in req["prompt"] and "sep=" not in req["prompt"]
    assert req["instance_id"] == "demo__abc" and req["may_name"] == []


def test_a_task_in_the_leak_share_may_name_the_changed_code():
    (req,) = build_requests([TASK], leak=1.0)
    assert req["may_name"] == ["Parser", "split_values", "format_item"]
    assert "split_values" in req["prompt"]


GOOD = (
    "When I read a comma separated line with an empty field between two commas the parser "
    "silently drops that field, so the result has fewer entries than the line has columns. "
    "It used to keep an empty string in that place. This breaks my code that relies on the "
    "position of each column in the returned list."
)


def test_check_text_accepts_a_clean_report_and_flags_problems():
    assert check_text(GOOD, ["split_values"], False) == []
    assert "too short" in check_text("It breaks.", [], False)
    assert "code block or traceback" in check_text(GOOD + "\n```\nx\n```", [], False)
    assert "names a file" in check_text(GOOD + " See lib/a.py for details.", [], False)
    assert "names the changed code" in check_text(
        GOOD + " split values is wrong.", ["split_values"], False
    )
    assert check_text(GOOD + " split values is wrong.", ["split_values"], True) == []


def test_apply_issues_replaces_text_and_keeps_the_rest():
    out = apply_issues([TASK, {**TASK, "instance_id": "other"}], {"demo__abc": GOOD})
    assert out[0]["problem_statement"] == GOOD and out[0]["patch"] == PATCH
    assert out[1]["problem_statement"] == TASK["problem_statement"]


def test_redo_requests_cover_only_flagged_texts_and_ban_the_names_used():
    from synthetic.issues import redo_requests

    clean = GOOD.replace("parser", "reader")  # "parser" is the fixture's class name
    reqs = redo_requests([TASK], {"demo__abc": clean + " split values is wrong."}, leak=0)
    assert [r["instance_id"] for r in reqs] == ["demo__abc"]
    assert "split values" in reqs[0]["prompt"] and "Do not use these words" in reqs[0]["prompt"]
    assert redo_requests([TASK], {"demo__abc": clean}, leak=0) == []
