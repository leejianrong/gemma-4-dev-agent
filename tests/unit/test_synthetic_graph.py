from synthetic.graph import build_graph

FILES = {
    "pkg/__init__.py": "from .util import helper\n",
    "pkg/util.py": (
        "def helper(x):\n    return x + 1\n\n\nclass Box:\n    '''A box.'''\n\n"
        "    def open(self):\n        return self.check()\n\n"
        "    def check(self):\n        return helper(1)\n\n"
        "    async def aopen(self):\n        return 1\n"
    ),
    "pkg/main.py": (
        "import pkg.util as u\nfrom pkg.util import Box\nfrom . import util\n\n\n"
        "def run():\n    b = Box()\n    def inner():\n        return u.helper(2)\n"
        "    util.helper(3)\n    return inner()\n"
    ),
}


def ids(g):
    return {n["id"] for n in g["nodes"]}


def edges(g):
    return {(e["source"], e["target"]) for e in g["edges"]}


def test_layout_matches_the_real_graph_files():
    g = build_graph(FILES, "toy@abc")
    assert set(g) == {"directed", "multigraph", "graph", "nodes", "edges"}
    assert g["graph"] == {"repo_name": "toy@abc"}
    assert all(set(n) == {"id", "name", "text"} for n in g["nodes"])
    assert all(set(e) == {"key", "source", "target", "type"} for e in g["edges"])
    assert {e["type"] for e in g["edges"]} == {"calls"}


def test_nodes_use_dotted_ids_and_skip_nested_functions_and_async_by_default():
    g = build_graph(FILES, "toy")
    assert {"pkg.util.helper", "pkg.util.Box", "pkg.util.Box.open", "pkg.main.run"} <= ids(g)
    assert "pkg.main.run.inner" not in ids(g)
    assert "pkg.util.Box.aopen" not in ids(g)
    assert "pkg.util.Box.aopen" in ids(build_graph(FILES, "toy", include_async=True))


def test_calls_resolve_through_self_imports_aliases_and_relative_imports():
    g = build_graph(FILES, "toy")
    e = edges(g)
    assert ("pkg.util.Box.open", "pkg.util.Box.check") in e
    assert ("pkg.util.Box.check", "pkg.util.helper") in e
    assert ("pkg.main.run", "pkg.util.Box") in e  # instantiation
    assert ("pkg.main.run", "pkg.util.helper") in e  # u.helper in a nested function, util.helper
    assert all(t in ids(g) for _, t in e)


def test_class_text_is_condensed_and_function_text_is_the_source():
    g = {n["id"]: n for n in build_graph(FILES, "toy")["nodes"]}
    assert "def open(self):" in g["pkg.util.Box"]["text"]
    assert "self.check()" not in g["pkg.util.Box"]["text"]
    assert "return x + 1" in g["pkg.util.helper"]["text"]


def test_node_ids_are_unique_when_a_def_is_repeated_under_if_else():
    files = {
        "m.py": "if X:\n    def f():\n        return 1\nelse:\n    def f():\n        return 2\n"
    }
    g = build_graph(files, "toy")
    assert [n["id"] for n in g["nodes"]] == ["m.f"]
    assert "return 1" in g["nodes"][0]["text"]


def test_build_is_deterministic_and_skips_unparsable_files():
    files = dict(FILES, **{"pkg/bad.py": "def (:\n"})
    assert build_graph(files, "toy") == build_graph(dict(reversed(list(files.items()))), "toy")
