import ast
import json
import subprocess

import pytest

from pod.gold_map import gm_defs, gm_innermost
from synthetic import mutate as m

SRC = '''\
import os


def clamp(x, lo, hi):
    """Clamp x. Limit is 10."""
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def both(a, b):
    return a and b


def count(items):
    n = 0
    for _ in items:
        n += 1
    return n


def call(a, b):
    return os.path.join(a, b)


class Box:
    def __init__(self, v):
        self.v = v

    def big(self):
        return self.v >= 100

    def helper(self):
        def inner(z):
            return z == 3

        return inner(self.v)


async def fetch(u):
    return u == 7
'''


def sites(src=SRC, **kw):
    return m.find_candidates(src, "pkg/mod.py", "pkg.mod", **kw)


def by_op(op, src=SRC, **kw):
    return [c for c in sites(src, **kw) if c.operator == op]


def all_records():
    return m.mutations_for_source(SRC, "pkg/mod.py", "pkg.mod")


def test_nodes_use_dotted_ids_and_kinds():
    got = {n["id"]: n["kind"] for n in m.list_nodes_in_source(SRC, "pkg.mod")}
    assert got["pkg.mod.clamp"] == "function_like"
    assert got["pkg.mod.Box"] == "class_like"
    assert got["pkg.mod.Box.big"] == "function_like"
    assert "pkg.mod.fetch" in got


def test_async_nodes_can_be_dropped_like_the_released_graph():
    got = {n["id"] for n in m.list_nodes_in_source(SRC, "pkg.mod", include_async=False)}
    assert "pkg.mod.fetch" not in got and "pkg.mod.clamp" in got
    assert not [c for c in sites(include_async=False) if c.qual == "fetch"]
    assert [c for c in sites(include_async=True) if c.qual == "fetch"]


def test_test_files_are_skipped(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("def f(x):\n    return x < 1\n")
    (tmp_path / "pkg" / "test_a.py").write_text("def t(x):\n    return x < 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "b.py").write_text("def u(x):\n    return x < 1\n")
    files = [p.relative_to(tmp_path).as_posix() for p in m.source_files(tmp_path)]
    assert files == ["pkg/__init__.py", "pkg/a.py"]
    assert m.module_name("pkg/__init__.py") == "pkg"
    assert m.module_name("pkg/a.py") == "pkg.a"


def mutate_one(op, qual):
    cands = [c for c in by_op(op) if c.qual == qual]
    assert cands, (op, qual)
    return m.apply_candidate(SRC, cands[0])


def test_comparison_swap():
    assert "if x <= lo:" in mutate_one("cmp_swap", "clamp")
    assert "return self.v > 100" in mutate_one("cmp_swap", "Box.big")


def test_boolean_swap():
    assert "return a or b" in mutate_one("bool_swap", "both")


def test_off_by_one_leaves_docstrings_alone():
    cands = by_op("const_off_by_one")
    assert cands
    assert not [c for c in cands if "Limit" in SRC.splitlines()[c.line - 1]]
    out = mutate_one("const_off_by_one", "count")
    assert "n = 1" in out or "n = -1" in out or "n += 2" in out or "n += 0" in out


def test_dropped_guard_keeps_the_lines():
    out = mutate_one("drop_guard", "clamp")
    assert "if False:" in out
    assert len(out.splitlines()) == len(SRC.splitlines())


def test_swapped_args():
    assert "os.path.join(b, a)" in mutate_one("swap_args", "call")


def test_wrong_return():
    assert "return None" in mutate_one("wrong_return", "clamp")


def test_every_mutation_is_valid_and_one_small_change():
    recs = all_records()
    assert recs
    for r in recs:
        ast.parse(r["mutated_text"])
        assert r["mutated_text"] != SRC
        assert len(r["mutated_text"].splitlines()) == len(SRC.splitlines())
        pairs = zip(SRC.splitlines(), r["mutated_text"].splitlines(), strict=True)
        changed = [i for i, (a, b) in enumerate(pairs) if a != b]
        assert 1 <= len(changed) <= 2, r["operator"]
        assert r["line"] - 1 in changed


def test_reverse_patch_restores_the_original(tmp_path):
    recs = all_records()
    assert len(recs) >= 6
    for i, r in enumerate(recs[:6]):
        d = tmp_path / str(i)
        (d / "pkg").mkdir(parents=True)
        (d / "pkg" / "mod.py").write_text(r["mutated_text"])
        (d / "gold.patch").write_text(r["gold_patch"])
        subprocess.run(["git", "apply", "gold.patch"], cwd=d, check=True)
        assert (d / "pkg" / "mod.py").read_text() == SRC
        assert r["gold_patch"].startswith("diff --git a/pkg/mod.py b/pkg/mod.py\n")


def test_gold_node_is_the_innermost_def_like_a24():
    defs = gm_defs(SRC)
    for r in all_records():
        assert r["innermost"] == gm_innermost(defs, r["line"])[3]


def test_nested_function_falls_back_to_its_parent_method():
    recs = all_records()
    nested = [r for r in recs if r["innermost"] == "Box.helper.inner"]
    assert nested
    assert nested[0]["gold_node"] == "pkg.mod.Box.helper"
    assert nested[0]["fell_back"] is True
    direct = [r for r in recs if r["innermost"] == "clamp"]
    assert direct[0]["gold_node"] == "pkg.mod.clamp" and direct[0]["fell_back"] is False


def test_non_ascii_text_before_a_site_does_not_shift_the_edit():
    src = 'def f(x):\n    s = "héllo wörld"\n    return x < 3\n'
    c = [c for c in m.find_candidates(src, "a.py", "a") if c.operator == "cmp_swap"][0]
    assert m.apply_candidate(src, c).splitlines()[2] == "    return x <= 3"


def make_tree(tmp_path):
    root = tmp_path / "src"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("")
    (root / "pkg" / "mod.py").write_text(SRC)
    return root


def test_same_seed_same_records_other_seed_differs(tmp_path):
    root = make_tree(tmp_path)
    a, b, c = (m.generate(root, n=5, seed=s) for s in (0, 0, 1))
    assert [r["id"] for r in a] == [r["id"] for r in b]
    assert [(r["line"], r["operator"]) for r in a] != [(r["line"], r["operator"]) for r in c]
    assert len(a) == 5


def test_cli_writes_jsonl(tmp_path):
    root = make_tree(tmp_path)
    out = tmp_path / "out.jsonl"
    assert m.main([str(root), str(out), "--n", "4", "--seed", "0", "--repo", "demo"]) == 0
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert len(rows) == 4
    assert rows[0]["repo"] == "demo" and rows[0]["commit"] == "PLACEHOLDER"
    assert {"file", "gold_node", "operator", "mutated_text", "gold_patch"} <= set(rows[0])


def test_unparsable_file_gives_no_candidates():
    assert m.find_candidates("def (:\n", "a.py", "a") == []


@pytest.mark.parametrize("src", ["def f(x):\n    return None\n", "def f():\n    pass\n"])
def test_nothing_to_mutate_is_fine(src):
    assert m.mutations_for_source(src, "a.py", "a") == []


def test_methods_of_lowercase_classes_still_have_nodes():
    src = "class curry:\n    def call(self, x):\n        return x < 2\n"
    recs = m.mutations_for_source(src, "a.py", "a")
    assert recs and recs[0]["gold_node"] == "a.curry.call" and recs[0]["fell_back"] is False
    ids = {n["id"] for n in m.list_nodes_in_source(src, "a")}
    assert ids == {"a.curry", "a.curry.call"}


def multi(k=2, n=5, seed=0, src=SRC):
    return m.multi_mutations_for_source(src, "pkg/mod.py", "pkg.mod", k=k, n=n, seed=seed)


def changed_lines(patch):
    return sum(1 for ln in patch.splitlines() if ln[:1] in "+-" and ln[:3] not in ("+++", "---"))


def test_multi_records_hold_k_bugs_in_k_different_nodes_of_one_file():
    recs = multi(k=3)
    assert recs
    for r in recs:
        assert r["operator"] == "multi" and len(r["operators"]) == 3
        assert len(set(r["gold_nodes"])) == 3 and r["gold_node"] == r["gold_nodes"][0]
        assert r["file"] == "pkg/mod.py" and r["sites"] == 3
        ast.parse(r["mutated_text"])
        assert r["mutated_text"] != SRC
        assert changed_lines(r["gold_patch"]) >= 6  # at least one removed and one added line each


def test_multi_gold_patch_restores_the_original_file(tmp_path):
    r = multi(k=2)[0]
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(r["mutated_text"])
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "gold.patch").write_text(r["gold_patch"])
    subprocess.run(["git", "apply", "gold.patch"], cwd=tmp_path, check=True)
    assert (tmp_path / "pkg" / "mod.py").read_text() == SRC


def test_multi_is_deterministic_and_respects_n():
    assert multi(seed=1) == multi(seed=1)
    assert len(multi(n=2)) <= 2
    assert [r["id"] for r in multi(seed=1)] != [r["id"] for r in multi(seed=2)] or len(multi()) <= 2


def test_multi_needs_k_different_nodes_and_returns_nothing_otherwise():
    one_node = "def f(a, b):\n    if a < b:\n        return a\n    return b\n"
    assert multi(k=2, src=one_node) == []
