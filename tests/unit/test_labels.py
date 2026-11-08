import pytest

pytest.importorskip("pandas")
import pandas as pd  # noqa: E402

from analysis import labels  # noqa: E402

TASKS = pd.DataFrame(
    [
        {
            "instance_id": "a_1",
            "repo": "o/a",
            "patch_lib_files": 1,
            "problem_words": 50,
            "has_traceback": 0,
            "code_blocks": 1,
            "issue_mentions_hunk_symbol": 1,
            "issue_mentions_patch_module": 0,
            "test_funcs_added": 2,
            "test_lines_added": 30,
        },
        {
            "instance_id": "a_2",
            "repo": "o/a",
            "patch_lib_files": 0,
            "problem_words": 10,
            "has_traceback": 0,
            "code_blocks": 0,
            "issue_mentions_hunk_symbol": 0,
            "issue_mentions_patch_module": 0,
            "test_funcs_added": 0,
            "test_lines_added": 5,
        },
        {
            "instance_id": "a_3",
            "repo": "o/a",
            "patch_lib_files": 2,
            "problem_words": 80,
            "has_traceback": 1,
            "code_blocks": 2,
            "issue_mentions_hunk_symbol": 0,
            "issue_mentions_patch_module": 1,
            "test_funcs_added": 1,
            "test_lines_added": 9,
        },
    ]
)
HUNKS = pd.DataFrame(
    [
        {"instance_id": "a_1", "status": "mapped", "n_added": 3, "n_removed": 1},
        {"instance_id": "a_1", "status": "node_missing", "n_added": 2, "n_removed": 0},
        {"instance_id": "a_2", "status": "non_library", "n_added": 9, "n_removed": 9},
        {"instance_id": "a_3", "status": "mapped", "n_added": 40, "n_removed": 20},
    ]
)
NODES = pd.DataFrame(
    [
        {
            "instance_id": "a_1",
            "node_id": "p.f",
            "kind": "function_like",
            "in_degree": 2,
            "out_degree": 1,
            "graph_nodes": 100,
        },
        {
            "instance_id": "a_3",
            "node_id": "p.g",
            "kind": "function_like",
            "in_degree": 0,
            "out_degree": 4,
            "graph_nodes": 50,
        },
        {
            "instance_id": "a_3",
            "node_id": "p.C",
            "kind": "class_like",
            "in_degree": 1,
            "out_degree": 1,
            "graph_nodes": 50,
        },
    ]
)
LOC = pd.DataFrame(
    [
        {"instance_id": "a_1", "pool": "library", "method": "bm25", "best_rank": 3},
        {"instance_id": "a_3", "pool": "library", "method": "bm25", "best_rank": 12},
        {"instance_id": "a_3", "pool": "all", "method": "bm25", "best_rank": 40},
    ]
)


def test_every_task_gets_one_row_with_every_defined_label():
    df = labels.build(TASKS, HUNKS, NODES, LOC)
    assert list(df["instance_id"]) == ["a_1", "a_2", "a_3"]
    assert list(df.columns) == labels.COLUMNS == [c for c, _ in labels.DEFINITIONS]


def test_counts_lines_and_hunk_kinds_come_from_library_hunks_only():
    df = labels.build(TASKS, HUNKS, NODES, LOC).set_index("instance_id")
    assert df.loc["a_1", "lib_hunks"] == 2 and df.loc["a_1", "lib_lines"] == 6
    assert df.loc["a_1", "async_hunks"] == 1 and df.loc["a_1", "gold_nodes"] == 1
    assert df.loc["a_2", "lib_hunks"] == 0 and df.loc["a_2", "lib_lines"] == 0
    assert df.loc["a_3", "gold_class_nodes"] == 1


def test_degree_rank_and_issue_signals_are_carried_through():
    df = labels.build(TASKS, HUNKS, NODES, LOC).set_index("instance_id")
    assert df.loc["a_3", "gold_max_degree"] == 4 and df.loc["a_3", "gold_median_degree"] == 3.0
    assert df.loc["a_1", "bm25_best_rank"] == 3 and df.loc["a_3", "bm25_best_rank"] == 12
    assert pd.isna(df.loc["a_2", "bm25_best_rank"])
    assert df.loc["a_1", "names_symbol"] == 1 and df.loc["a_3", "names_module"] == 1


def test_size_tier_and_difficulty_rules():
    assert [labels.size_tier(n) for n in (0, 5, 6, 15, 50, 51)] == [
        "none",
        "tiny",
        "small",
        "small",
        "medium",
        "large",
    ]
    assert labels.difficulty(0, 0, 0) == "no_library_code"
    assert labels.difficulty(10, 1, 1) == "easy"
    assert labels.difficulty(30, 1, 1) == "medium" and labels.difficulty(10, 2, 1) == "medium"
    assert labels.difficulty(10, 4, 3) == "hard" and labels.difficulty(60, 1, 1) == "hard"


def test_the_definitions_document_lists_every_label():
    doc = labels.definitions_markdown()
    assert all(f"`{c}`" in doc for c in labels.COLUMNS)
