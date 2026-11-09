from analysis.dev_subset import pick


def test_pick_is_deterministic_and_skips_dropped_ids():
    ids = {"a/a": [f"a_{i}" for i in range(10)], "b/b": ["b_1"]}
    one = pick(ids, {"a_3"}, {"a/a": 4, "b/b": 2}, seed=0)
    two = pick(ids, {"a_3"}, {"a/a": 4, "b/b": 2}, seed=0)
    assert one == two
    assert "a_3" not in one["a/a"] and len(one["a/a"]) == 4
    assert one["b/b"] == ["b_1"]
    assert pick(ids, set(), {"a/a": 4}, seed=1) != pick(ids, set(), {"a/a": 4}, seed=2)
