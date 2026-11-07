import json
import zipfile

import explore

PATCH = """diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,6 +1,6 @@ class Thing
 def alpha(x):
-    return x + 1
+    return x + 2

 def beta(y):
-    value = y * 3
+    value = y * 4
     return value
"""

ADD_ONLY = """diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -4,3 +4,4 @@ def beta(y)
     value = y * 3
+    value += 1
     return value
"""

NODES = [
    {"id": "pkg.mod.alpha", "name": "pkg.mod.alpha", "text": "def alpha(x):\n    return x + 1\n"},
    {
        "id": "pkg.mod.beta",
        "name": "pkg.mod.beta",
        "text": "def beta(y):\n    value = y * 3\n    return value\n",
    },
    {"id": "pkg.other.gamma", "name": "pkg.other.gamma", "text": "def gamma():\n    return 1\n"},
]


def test_parse_patch_splits_files_and_hunks():
    files = explore.parse_patch(PATCH)
    assert [f["path"] for f in files] == ["pkg/mod.py"]
    h = files[0]["hunks"][0]
    assert h["removed"] == ["    return x + 1", "    value = y * 3"]
    assert h["added"] == ["    return x + 2", "    value = y * 4"]


def test_module_candidates():
    assert explore.module_candidates("src/requests/models.py") == [
        "src.requests.models",
        "requests.models",
        "models",
    ]
    assert explore.module_candidates("pkg/__init__.py") == ["pkg"]
    assert explore.module_candidates("README.md") == []


def test_map_hunk_finds_both_functions_in_one_hunk():
    h = explore.parse_patch(PATCH)[0]["hunks"][0]
    assert sorted(explore.map_hunk(h, NODES, ["pkg.mod"])) == ["pkg.mod.alpha", "pkg.mod.beta"]


def test_generic_line_does_not_invent_a_second_node():
    nodes = NODES + [{"id": "pkg.mod.delta", "text": "def delta():\n    return value\n"}]
    hunk = {
        "ctx": "",
        "removed": ["    value = y * 3", "    return value"],
        "added": [],
        "context": [],
    }
    assert explore.map_hunk(hunk, nodes, ["pkg.mod"]) == ["pkg.mod.beta"]


def test_map_hunk_ignores_other_modules():
    h = explore.parse_patch(PATCH)[0]["hunks"][0]
    assert explore.map_hunk(h, NODES, ["pkg.other"]) == []


def test_addition_only_falls_back_to_header_function():
    h = explore.parse_patch(ADD_ONLY)[0]["hunks"][0]
    assert explore.map_hunk(h, NODES, ["pkg.mod"]) == ["pkg.mod.beta"]


def test_hops():
    adj = explore.adjacency([{"source": "a", "target": "b"}, {"source": "b", "target": "c"}])
    assert explore.hops(adj, "a", "b") == 1
    assert explore.hops(adj, "a", "c") == 2
    assert explore.hops(adj, "a", "z") is None


def _write_fixture(root, with_graph=True):
    (root / "graphs").mkdir(parents=True)
    (root / "embeddings").mkdir()
    task = {
        "instance_id": "pkg_1",
        "repo": "o/pkg",
        "base_commit": "c0ffee",
        "patch": PATCH,
        "problem_statement": "alpha returns the wrong value",
        "hints_text": "",
    }
    (root / "tasks.jsonl").write_text(json.dumps(task) + "\n")
    if with_graph:
        edges = [{"source": "pkg.mod.alpha", "target": "pkg.mod.beta", "type": "calls", "key": 0}]
        (root / "graphs" / "pkg_c0ffee.json").write_text(
            json.dumps({"nodes": NODES, "edges": edges})
        )
        with zipfile.ZipFile(root / "embeddings" / "pkg_c0ffee.npz", "w") as zf:
            zf.writestr("pkg.mod.alpha.npy", _npy())


def _npy():
    header = "{'descr': '<f4', 'fortran_order': False, 'shape': (256,), }"
    header = header.ljust(118) + "\n"
    return b"\x93NUMPY\x01\x00" + len(header).to_bytes(2, "little") + header.encode() + bytes(1024)


def test_end_to_end_report(tmp_path):
    _write_fixture(tmp_path / "d")
    assert explore.main(["x", str(tmp_path / "d"), str(tmp_path / "o")]) == 0
    rep = json.loads((tmp_path / "o" / "report.json").read_text())
    assert rep["tasks"] == 1 and rep["with_graph"] == 1 and rep["with_embeddings"] == 1
    assert rep["tasks_with_mapped_node"] == 1
    assert rep["multi_node_tasks"] == 1 and rep["pairs_1hop"] == 1
    assert rep["issue_names_symbol"] == 1
    assert rep["graph_schema"]["edge_types"] == {"calls": 1}
    assert rep["emb_shapes"] == {"(256,)": 1}


def test_missing_graph_is_reported_not_fatal(tmp_path):
    _write_fixture(tmp_path / "d", with_graph=False)
    assert explore.main(["x", str(tmp_path / "d"), str(tmp_path / "o")]) == 0
    rep = json.loads((tmp_path / "o" / "report.json").read_text())
    assert rep["with_graph"] == 0 and rep["tasks"] == 1


def test_missing_tasks_file_fails_loudly(tmp_path):
    (tmp_path / "d").mkdir()
    assert explore.main(["x", str(tmp_path / "d"), str(tmp_path / "o")]) == 2


NO_GIT_HEADER = """--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,2 +1,2 @@ def alpha(x)
 def alpha(x):
-    return x + 1
+    return x + 2
--- a/pkg/other.py
+++ b/pkg/other.py
@@ -1,2 +1,2 @@ def gamma()
 def gamma():
-    return 1
+    return 3
"""


def test_multi_file_patch_without_diff_git_lines_keeps_files_separate():
    files = explore.parse_patch(NO_GIT_HEADER)
    assert [f["path"] for f in files] == ["pkg/mod.py", "pkg/other.py"]
    assert files[0]["hunks"][0]["removed"] == ["    return x + 1"]
    assert files[1]["hunks"][0]["removed"] == ["    return 1"]
    for f in files:
        for h in f["hunks"]:
            assert not any(
                x.startswith("-") or x.startswith("++") for x in h["removed"] + h["added"]
            )


def test_header_function_breaks_ties_between_nodes_sharing_a_line():
    nodes = [
        {"id": "pkg.mod.aaa", "text": "def aaa():\n    return shared_value + 1\n"},
        {"id": "pkg.mod.bbb", "text": "def bbb():\n    return shared_value + 1\n"},
    ]
    hunk = {
        "ctx": "def bbb():",
        "removed": ["    return shared_value + 1"],
        "added": [],
        "context": [],
    }
    assert explore.map_hunk(hunk, nodes, ["pkg.mod"]) == ["pkg.mod.bbb"]
