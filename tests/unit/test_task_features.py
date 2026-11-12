from analysis import task_features as tf

PATCH_HUNKS = [
    {"status": "mapped", "path": "pkg/a.py", "n_removed": "2", "n_added": "3"},
    {"status": "module_level", "path": "pkg/b.py", "n_removed": "0", "n_added": "4"},
    {"status": "non_library", "path": "docs_src/x.py", "n_removed": "0", "n_added": "9"},
]


def _row(tid="secret_1", group="never", classes=("wrong_fix", "wrong_fix"), **kw):
    row = {
        "id": tid,
        "repo": "fastapi",
        "group": group,
        "gold_files": 1,
        "gold_hunks": 1,
        "gold_lines": 5,
        "gold_nodes": 1,
        "module_level": False,
        "new_file": False,
        "async_hunk": False,
        "docs_only": False,
        "issue_words": 100,
        "has_code": False,
        "has_traceback": False,
        "test_files": 1,
        "test_lines": 10,
        "missing_deps": False,
        "names_gold": False,
        "bm25_hit": True,
        "n_resolved": 0,
        "n_runs": len(classes),
        "runs": [
            {
                "class": c,
                "calls": 20,
                "seconds": 120.0,
                "edited": True,
                "first_edit_gold": True,
                "read_gold": True,
            }
            for c in classes
        ],
    }
    return row | kw


def test_group_of_splits_by_times_resolved():
    assert [tf.group_of(n) for n in (0, 1, 3, 4, 5)] == [
        "never",
        "flaky",
        "flaky",
        "stable",
        "stable",
    ]


def test_gold_features_ignore_non_library_hunks_and_flag_kinds():
    f = tf.gold_features(PATCH_HUNKS, [{"node_id": "pkg.a.f"}])
    assert (f["gold_files"], f["gold_hunks"], f["gold_lines"], f["gold_nodes"]) == (2, 2, 9, 1)
    assert f["module_level"] and not f["async_hunk"] and not f["docs_only"]
    assert tf.gold_features([PATCH_HUNKS[2]], [])["docs_only"]
    assert tf.gold_features([{**PATCH_HUNKS[0], "status": "node_missing"}], [])["async_hunk"]


def test_issue_features_count_words_code_traceback_and_missing_deps():
    task = {
        "problem_statement": "It fails\n```py\nx\n```\nTraceback (most recent call last):",
        "test_patch": "--- a/t.py\n+++ b/tests/t.py\n+import dirty_equals\n+x = 1\n",
        "created_at": "2024-05-01T00:00:00Z",
    }
    f = tf.issue_features(task)
    assert f["has_code"] and f["has_traceback"] and f["missing_deps"]
    assert (f["test_files"], f["test_lines"], f["year"]) == (1, 2, "2024")


def test_names_gold_matches_whole_words_and_ignores_short_names():
    assert tf.names_gold("calls get_handler twice", ["pkg.mod.get_handler"], set())
    assert not tf.names_gold("calls get_handler_2", ["pkg.mod.get_handler"], set())
    assert tf.names_gold("see routing for details", [], {"pkg/routing.py"})
    assert not tf.names_gold("an f here", ["pkg.f"], set())


def test_bm25_hit_ranks_snapshot_defs_and_is_none_without_gold():
    files = {
        "pkg/a.py": "def render_table(rows):\n    return rows\n\n\ndef other():\n    return 1\n"
    }
    assert tf.bm25_hit(files, "render table rows", ["pkg.a.render_table"]) is True
    assert tf.bm25_hit(files, "render table rows", ["pkg.a.missing"]) is False
    assert tf.bm25_hit(files, "render table rows", []) is None


def _trace(*calls):
    steps = [
        {
            "source": "agent",
            "tool_calls": [{"function_name": n, "arguments": a}],
            "observation": {"content": "{}"},
            "extra": {"elapsed_s": float(i)},
        }
        for i, (n, a) in enumerate(calls)
    ]
    return {"steps": steps}


def test_trace_features_normalise_paths_and_find_the_first_edit():
    gold = {"pkg/a.py"}
    tr = _trace(
        ("read_file", {"filepath": "/workspace/pkg/a.py"}),
        ("edit_file", {"filepath": "pkg/a.py"}),
        ("edit_file", {"filepath": "pkg/z.py"}),
    )
    assert tf.trace_features(tr, gold) == {
        "edited": True,
        "first_edit_gold": True,
        "read_gold": True,
    }
    wrong = _trace(("edit_file", {"filepath": "./pkg/z.py"}))
    assert tf.trace_features(wrong, gold) == {
        "edited": True,
        "first_edit_gold": False,
        "read_gold": False,
    }
    assert not tf.trace_features(_trace(), gold)["edited"]


def test_pod_results_reads_task_lines(tmp_path):
    log = tmp_path / "job.log"
    log.write_text(
        "noise\nTASK 1/36 a_1 status=resolved calls=28 t=238.4s\n"
        "TASK 2/36 b_2 status=error calls=9 t=480.0s\n"
    )
    assert tf.pod_results(log) == {
        "a_1": {"status": "resolved", "calls": 28, "seconds": 238.4},
        "b_2": {"status": "error", "calls": 9, "seconds": 480.0},
    }


def test_aggregate_render_unscoreable_and_levers_hold_no_task_ids():
    rows = [
        _row("secret_1", "never", ("inconclusive",) * 4),
        _row("secret_2", "never", ("wrong_fix",) * 4, missing_deps=True),
        _row(
            "secret_3",
            "never",
            ("timeout", "budget_no_patch", "wrong_fix", "wrong_fix"),
            docs_only=True,
        ),
        _row(
            "secret_4", "flaky", ("resolved", "wrong_fix", "broke_code", "resolved"), gold_lines=30
        ),
        _row("secret_5", "stable", ("resolved",) * 4),
    ]
    agg = tf.aggregate(rows)
    assert agg["groups"] == {"stable": 1, "flaky": 1, "never": 3}
    assert agg["bins"]["gold lines"][">10"]["tasks"] == 1
    unsc = tf.unscoreable(rows)
    text = tf.render(agg, unsc, tf.levers(rows))
    assert "secret_" not in text and "~" in text  # every bin here has fewer than 5 tasks
    assert (
        unsc["missing_test_deps"],
        unsc["inconclusive_in_3_plus_runs"],
        unsc["docs_only_gold"],
    ) == (1, 1, 1)
    assert unsc["genuine"] == 0
    lev = tf.levers(rows)
    assert (
        lev["flaky_tasks"] == 1
        and lev["budget_stops"] == 1
        and lev["budget_stops_read_gold_file"] == 1
    )
