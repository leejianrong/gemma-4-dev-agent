from analysis.dev_subset import pick


def test_pick_is_deterministic_and_skips_dropped_ids():
    ids = {"a/a": [f"a_{i}" for i in range(10)], "b/b": ["b_1"]}
    one = pick(ids, {"a_3"}, {"a/a": 4, "b/b": 2}, seed=0)
    two = pick(ids, {"a_3"}, {"a/a": 4, "b/b": 2}, seed=0)
    assert one == two
    assert "a_3" not in one["a/a"] and len(one["a/a"]) == 4
    assert one["b/b"] == ["b_1"]
    assert pick(ids, set(), {"a/a": 4}, seed=1) != pick(ids, set(), {"a/a": 4}, seed=2)


def test_tasks_needing_missing_test_deps_are_found(tmp_path):
    import json

    from analysis.dev_subset import needs_missing_test_deps

    f = tmp_path / "t.jsonl"
    rows = [
        {"instance_id": "a_1", "test_patch": "from inline_snapshot import snapshot"},
        {"instance_id": "b_2", "test_patch": "def test_x(): pass"},
        {"instance_id": "c_3", "test_patch": "def test_y(httpbin): pass"},
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows))
    assert needs_missing_test_deps(f) == {"a_1", "c_3"}
