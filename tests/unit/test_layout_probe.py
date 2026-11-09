import json

from pod.layout_probe import layout, shape_of


def test_shape_of_keeps_types_and_lengths_not_values():
    s = shape_of({"a": "hello", "b": [1, 2], "c": {"d": 1.5}})
    assert s["fields"]["a"] == {"type": "str", "len": 5}
    assert s["fields"]["b"]["item"] == {"type": "int"}
    assert "hello" not in json.dumps(s)


def test_layout_reads_tasks_and_graph(tmp_path):
    d = tmp_path / "data"
    (d / "graphs").mkdir(parents=True)
    (d / "tasks.jsonl").write_text(json.dumps({"repo": "x/y", "issue": "SECRET TEXT"}) + "\n")
    (d / "graphs" / "x.json").write_text(json.dumps({"nodes": [{"id": "pkg.f", "text": "code"}]}))
    res = layout(d, tmp_path / "out")
    assert res["tasks"]["fields"] == ["issue", "repo"]
    assert res["graph"]["example_ids"] == ["pkg.f"]
    assert "SECRET TEXT" not in (tmp_path / "out" / "layout.json").read_text()
