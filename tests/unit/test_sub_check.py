import json

import sub_check as sc


def write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


SAMPLE = {
    "agent.yaml": "name: a\nmodel: m1\ninstruction: !include prompts/system.md\n"
    "tools:\n  - x\n  - y\n",
    "prompts/system.md": "hello",
    "extra.yaml": "k: 1\n",
}
OURS = {
    "agent.yaml": "name: a\nmodel: m2\ninstruction: !include prompts/system.md\n"
    "tools:\n  - x\n  - y\n  - z\n",
    "prompts/system.md": "hello",
}


def test_flatten_indexes_lists_of_mappings_and_keeps_scalar_lists_whole():
    flat = sc.sc_flatten({"a": {"b": 1}, "t": ["x", "y"], "m": [{"k": 1}]})
    assert flat == {"a.b": 1, "t": ["x", "y"], "m[0].k": 1}


def test_includes_are_resolved_on_both_sides(tmp_path):
    write(tmp_path, SAMPLE)
    flat, files = sc.sc_load_dir(tmp_path)
    assert flat["agent.yaml::instruction"] == "hello"
    assert "extra.yaml" in files and flat["extra.yaml::k"] == 1


def test_diff_lists_missing_extra_and_changed_fields(tmp_path):
    write(tmp_path / "s", SAMPLE)
    write(tmp_path / "o", OURS)
    d = sc.sc_diff(sc.sc_load_dir(tmp_path / "s")[0], sc.sc_load_dir(tmp_path / "o")[0])
    assert d["differ"]["agent.yaml::model"] == {"sample": "m1", "ours": "m2"}
    assert "extra.yaml::k" in d["only_in_sample"] and d["only_in_ours"] == {}
    assert d["same"] >= 2


def test_a_missing_include_is_reported_not_raised(tmp_path):
    write(tmp_path, {"agent.yaml": "instruction: !include nope.md\n"})
    assert sc.sc_load_dir(tmp_path)[0]["agent.yaml::instruction"].startswith("<missing include")


def test_run_finds_the_sample_and_degrades_without_adk_submission(tmp_path):
    data = tmp_path / "data"
    write(data / "sample_submission", SAMPLE)
    rep = sc.sc_run(data, tmp_path / "out", OURS)
    assert rep["sample_dir"].endswith("sample_submission") and rep["diff"]["differ"]
    assert rep["validate_ours"]["available"] is False
    assert json.loads((tmp_path / "out" / "subdiff.json").read_text())["our_files"]


def test_run_without_a_sample_still_writes_a_report(tmp_path):
    rep = sc.sc_run(tmp_path / "data", tmp_path / "out", OURS)
    assert rep["sample_dir"] is None and "diff" not in rep


def test_includes_resolve_relative_to_the_including_file(tmp_path):
    write(
        tmp_path,
        {
            "sub_agents/a.yaml": "instruction: !include ../prompts/p.md\n",
            "prompts/p.md": "deep",
        },
    )
    assert sc.sc_load_dir(tmp_path)[0]["sub_agents/a.yaml::instruction"] == "deep"
