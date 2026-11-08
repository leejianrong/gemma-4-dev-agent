import pytest

pytest.importorskip("matplotlib")
pd = pytest.importorskip("pandas")

from analysis import eda_async_split as sp  # noqa: E402

NODES = pd.DataFrame(
    [
        {"instance_id": "t1", "node_id": "p.f", "kind": "function_like"},
        {"instance_id": "t1", "node_id": "p.g", "kind": "function_like"},
        {"instance_id": "t1", "node_id": "p.C", "kind": "class_like"},
    ]
)
HUNKS = pd.DataFrame(
    [
        {"instance_id": "t1", "status": "mapped"},
        {"instance_id": "t1", "status": "node_missing"},
        {"instance_id": "t1", "status": "node_missing"},
    ]
)


def loc(top):
    base = {"instance_id": "t1", "repo": "a/b", "pool": "library", "gold": "p.f|p.g|p.C"}
    return pd.DataFrame([{**base, "method": "bm25", "top": top}])


def test_targets_are_split_by_kind_and_async_hunks_are_counted_as_unreachable():
    df = sp.prepare(NODES, HUNKS, loc("p.f|x|p.C"))
    row = df[df["k"] == 10].iloc[0]
    assert (row["function_like_total"], row["function_like_found"]) == (2, 1)
    assert (row["class_like_total"], row["class_like_found"]) == (1, 1)
    assert row["async_total"] == 2
    func, _ = sp.recall(df, "bm25", 10, "function_like")
    allr, n = sp.recall(df, "bm25", 10, "all")
    assert func == 0.5 and allr == pytest.approx(2 / 5) and n == 1


def test_recall_respects_k_and_ignores_tasks_without_that_kind():
    df = sp.prepare(NODES, HUNKS, loc("x|p.f|p.C"))
    assert sp.recall(df, "bm25", 1, "function_like")[0] == 0.0
    assert sp.recall(df, "bm25", 5, "function_like")[0] == 0.5
    only_fn = NODES[NODES["kind"] == "function_like"]
    df2 = sp.prepare(only_fn, HUNKS, loc("p.f"))
    val, n = sp.recall(df2, "bm25", 10, "class_like")
    assert n == 0 and val != val  # NaN: no task has a class target


def test_numbers_report_counts_for_the_caption():
    nums = sp.numbers(sp.prepare(NODES, HUNKS, loc("p.f")))
    assert nums["async_hunks"] == 2 and nums["tasks_with_async_hunks"] == 1
    assert nums["sync_function_nodes"] == 2 and nums["class_nodes"] == 1
