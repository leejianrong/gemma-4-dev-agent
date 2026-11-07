import csv
import io
import json
import tarfile

import explore
import gold_map as gm

SRC = """import os

CONST = 1


def helper(x):
    return x + 1


class Thing:
    attr = 1

    def run(self, y):
        z = y * 2
        return z

    @property
    def name(self):
        return "t"


def outer():
    def inner():
        return 1
    return inner()
"""
LINES = SRC.splitlines()
IDS = {
    "pkg.mod.helper",
    "pkg.mod.Thing",
    "pkg.mod.Thing.run",
    "pkg.mod.Thing.name",
    "pkg.mod.outer",
}


def L(n):
    return " ", LINES[n - 1]


def patch(old_start, lines, path="pkg/mod.py"):
    old = sum(1 for k, _ in lines if k != "+")
    new = sum(1 for k, _ in lines if k != "-")
    body = "\n".join(k + t for k, t in lines)
    return f"--- a/{path}\n+++ b/{path}\n@@ -{old_start},{old} +{old_start},{new} @@\n{body}\n"


def hunk(old_start, lines):
    return explore.parse_patch(patch(old_start, lines))[0]["hunks"][0]


def credit(old_start, lines):
    return {k: dict(v) for k, v in gm.gm_attribute(hunk(old_start, lines), gm.gm_defs(SRC)).items()}


def test_parser_keeps_numbers_order_and_blank_context_lines():
    h = hunk(6, [L(6), ("-", "    return x + 1"), ("+", "    return x + 2"), L(8)])
    assert (h["old_start"], h["old_count"], h["new_start"]) == (6, 3, 6)
    assert [k for k, _ in h["lines"]] == [" ", "-", "+", " "]
    stripped = (
        "--- a/f.py\n+++ b/f.py\n@@ -1,3 +1,3 @@\n a\n\n-b\n+c\n"  # blank line lost its space
    )
    h2 = explore.parse_patch(stripped)[0]["hunks"][0]
    assert [k for k, _ in h2["lines"]] == [" ", " ", "-", "+"] and h2["old_count"] == 3


def test_removed_line_goes_to_the_enclosing_function():
    c = credit(6, [L(6), ("-", "    return x + 1"), ("+", "    return x + 2"), L(8)])
    assert c == {"helper": {"-": 1, "+": 1}}


def test_addition_inside_a_method_body_goes_to_that_method():
    c = credit(14, [L(14), ("+", "        w = 1"), L(15)])
    assert c == {"Thing.run": {"-": 0, "+": 1}}


def test_a_new_method_added_to_a_class_is_credited_to_the_class_not_the_previous_method():
    new = [("+", ""), ("+", "    def extra(self):"), ("+", "        return 1")]
    c = credit(15, [L(15), *new, L(16)])
    assert c == {"Thing": {"-": 0, "+": 2}}


def test_a_new_top_level_function_is_module_level():
    new = [("+", "def new():"), ("+", "    return 0"), ("+", "")]
    c = credit(8, [L(8), *new, L(9)])
    assert c == {gm.GM_MODULE: {"-": 0, "+": 2}}


def test_decorator_change_belongs_to_the_decorated_function():
    c = credit(17, [("-", "    @property"), ("+", "    @cached_property"), L(18)])
    assert c == {"Thing.name": {"-": 1, "+": 1}}


def test_module_level_constant_change_has_no_node():
    c = credit(3, [("-", "CONST = 1"), ("+", "CONST = 2"), L(4)])
    assert c == {gm.GM_MODULE: {"-": 1, "+": 1}}


def test_nested_function_without_a_graph_node_falls_back_to_its_parent():
    assert gm.gm_resolve("pkg.mod", "outer.inner", IDS) == ("pkg.mod.outer", True)
    assert gm.gm_resolve("pkg.mod", "Thing.run", IDS) == ("pkg.mod.Thing.run", False)
    assert gm.gm_resolve("pkg.mod", "missing.deep", IDS) == (None, True)


def test_consistency_check_catches_a_wrong_file_or_wrong_line_numbers():
    good = hunk(6, [L(6), ("-", "    return x + 1"), L(8)])
    assert gm.gm_consistent(good, LINES)
    shifted = hunk(7, [L(6), ("-", "    return x + 1"), L(8)])
    assert not gm.gm_consistent(shifted, LINES)


def test_module_choice_handles_the_src_layout():
    cands = explore.module_candidates("src/pkg/mod.py")
    assert gm.gm_pick_module(cands, IDS, {"helper"}) == "pkg.mod"
    assert gm.gm_pick_module(["x.y"], IDS, {"helper"}) is None


def make_tgz(path, members):
    with tarfile.open(path, "w:gz") as tf:
        for name, text in members.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_old_files_are_found_whatever_the_archive_prefix(tmp_path):
    make_tgz(tmp_path / "a.tgz", {"./pkg/mod.py": "A", "./pkg/other.py": "B"})
    make_tgz(tmp_path / "b.tgz", {"repo/pkg/mod.py": "C"})
    got, sample = gm.gm_read_old_files(tmp_path / "a.tgz", {"pkg/mod.py", "pkg/none.py"})
    assert got == {"pkg/mod.py": "A"} and sample
    assert gm.gm_read_old_files(tmp_path / "b.tgz", {"pkg/mod.py"})[0] == {"pkg/mod.py": "C"}
    assert gm.gm_read_old_files(tmp_path / "missing.tgz", {"x"})[0] == {}


def test_end_to_end_run_maps_validates_and_reports(tmp_path):
    data = tmp_path / "d"
    (data / "graphs").mkdir(parents=True)
    (data / "snapshots").mkdir()
    gold = patch(6, [L(6), ("-", "    return x + 1"), ("+", "    return x + 2"), L(8)])
    task = {"instance_id": "pkg_1", "repo": "o/pkg", "base_commit": "c0ffee", "patch": gold}
    (data / "tasks.jsonl").write_text(json.dumps(task) + "\n")
    nodes = [{"id": i, "text": ""} for i in IDS]
    nodes[[n["id"] for n in nodes].index("pkg.mod.helper")]["text"] = (
        "def helper(x):\n    return x + 1\n"
    )
    (data / "graphs" / "pkg_c0ffee.json").write_text(json.dumps({"nodes": nodes, "edges": []}))
    make_tgz(data / "snapshots" / "pkg_1.tgz", {"./pkg/mod.py": SRC})
    rep = gm.gm_run(data, tmp_path / "o")
    assert (
        rep["tasks_with_a_mapped_node"] == 1
        and rep["tasks_where_every_library_hunk_is_mapped"] == 1
    )
    assert (
        rep["hunks_consistent_with_old_file"] == 1
        and rep["function_nodes_text_agree_all_lines"] == 1
    )
    assert rep["text_method_subset_of_line_method"] == rep["text_method_hunks_compared"] == 1
    rows = list(csv.DictReader(open(tmp_path / "o" / "gold_nodes.csv")))
    assert [r["node_id"] for r in rows] == ["pkg.mod.helper"] and rows[0]["text_agree"] == "1.0"
    assert "pkg_1" in (tmp_path / "o" / "mapping_samples.md").read_text()


def run_one(tmp_path, gold):
    data = tmp_path / "d"
    (data / "graphs").mkdir(parents=True)
    (data / "snapshots").mkdir()
    task = {"instance_id": "pkg_1", "repo": "o/pkg", "base_commit": "c0ffee", "patch": gold}
    (data / "tasks.jsonl").write_text(json.dumps(task) + "\n")
    nodes = [{"id": i, "text": "\n".join(LINES)} for i in sorted(IDS)]
    (data / "graphs" / "pkg_c0ffee.json").write_text(json.dumps({"nodes": nodes, "edges": []}))
    make_tgz(data / "snapshots" / "pkg_1.tgz", {"./pkg/mod.py": SRC})
    rep = gm.gm_run(data, tmp_path / "o")
    return (
        rep,
        list(csv.DictReader(open(tmp_path / "o" / "gold_nodes.csv"))),
        list(csv.DictReader(open(tmp_path / "o" / "gold_hunks.csv"))),
    )


def test_a_nested_function_and_its_parent_are_one_node_with_merged_counts(tmp_path):
    gold = patch(
        23, [L(23), ("-", "        return 1"), ("-", "    return inner()"), ("+", "    return 2")]
    )
    rep, nodes, hunks = run_one(tmp_path, gold)
    assert [n["node_id"] for n in nodes] == ["pkg.mod.outer"]
    assert nodes[0]["removed_lines"] == "2" and nodes[0]["hunks"] == "1"
    assert hunks[0]["nodes"] == "pkg.mod.outer" and hunks[0]["parent_fallback"] == "1"


def test_a_module_level_only_hunk_has_no_node_and_is_reported_as_such(tmp_path):
    gold = patch(3, [("-", "CONST = 1"), ("+", "CONST = 2"), L(4)])
    rep, nodes, hunks = run_one(tmp_path, gold)
    assert nodes == [] and hunks[0]["status"] == "module_level"
    assert rep["tasks_with_a_mapped_node"] == 0 and rep["library_hunk_status"] == {
        "module_level": 1
    }


def test_text_checks_ignore_comments_and_decorators_the_graph_strips():
    assert gm.gm_clean("    return x  # type: ignore[arg-type]") == "return x"
    assert gm.gm_clean("    @property") is None and gm.gm_clean("# note") is None
    assert gm.gm_clean_set(["a = 1  # c", "@cached", "b = 2"]) == {"a = 1", "b = 2"}


def test_header_check_names_the_mapped_function_or_class():
    assert gm.gm_header_ok("pkg.mod.Thing.run", "def run(self, y):\n    return y")
    assert gm.gm_header_ok("pkg.mod.Thing.name", "@property\ndef name(self):\n    pass")
    assert not gm.gm_header_ok("pkg.mod.Thing.run", "def other(self):\n    return 1")


def test_def_stats_split_sync_and_async_and_skip_nested_functions():
    src = (
        "def a():\n    def nested():\n        pass\n\n\nasync def b():\n    pass\n\n\n"
        "class C:\n    def m(self):\n        pass\n\n    async def n(self):\n        pass\n"
    )
    ids = {"pkg.mod.a", "pkg.mod.C", "pkg.mod.C.m"}  # the graph has no async nodes
    got = gm.gm_def_stats(src, gm.gm_defs(src), "pkg.mod", ids)
    assert got == {"async_defs": 2, "async_with_node": 0, "sync_defs": 2, "sync_with_node": 2}
    assert gm.gm_async_names(src) == {"b", "C.n"}
