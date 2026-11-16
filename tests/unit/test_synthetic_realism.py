from synthetic.realism import BINS, bin_shares, compare, patch_stats, summarize

PATCH = """diff --git a/lib/a.py b/lib/a.py
--- a/lib/a.py
+++ b/lib/a.py
@@ -1,3 +1,3 @@
 keep
-old1
+new1
@@ -10,3 +10,4 @@
 keep
-old2
+new2
+async def f(): pass
diff --git a/lib/b.py b/lib/b.py
--- a/lib/b.py
+++ b/lib/b.py
@@ -1,2 +1,2 @@
-x
+y
"""


def test_patch_stats_counts_changed_lines_hunks_files_and_async():
    s = patch_stats(PATCH)
    assert s == {"lines": 7, "hunks": 3, "files": 2, "async": True}


def test_bin_shares_use_the_four_size_bins():
    assert BINS == [(0, 4), (5, 12), (13, 44), (45, None)]
    assert bin_shares([1, 4, 5, 12, 13, 44, 45, 200]) == [0.25, 0.25, 0.25, 0.25]


def test_summarize_and_compare_report_a_distance_between_bins():
    real = [{"patch": PATCH, "problem_statement": "one two three"}] * 2
    small = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    synth = [{"patch": small, "problem_statement": "a b"}] * 2
    r, s = summarize(real), summarize(synth)
    assert r["n"] == 2 and r["gold_lines_median"] == 7 and r["issue_words_median"] == 3
    assert s["gold_lines_median"] == 2
    c = compare(r, s)
    assert c["bin_distance"] == 1.0  # all real tasks in one bin, all synthetic in another


def test_patch_stats_counts_files_in_a_patch_without_diff_git_headers():
    plain = (
        "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-c\n+d\n"
    )
    assert patch_stats(plain)["files"] == 2 and patch_stats(plain)["lines"] == 4
