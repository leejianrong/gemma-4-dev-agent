"""GEM-81: sibling suggestions in the localizer skill and in the two scorers."""

import importlib.util
from pathlib import Path

import skill_score as ss

from synthetic import mutate
from synthetic.score_localize import score_records

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "experiments" / "skills" / "localize" / "scripts" / "localize.py"
spec = importlib.util.spec_from_file_location("skill_localize_sib", PATH)
sk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sk)

FILES = {
    "pkg/a.py": (
        "def render_table(rows):\n    return rows\n\n\n"
        "def render_row(row):\n    return row\n\n\n"
        "def helper_a():\n    return 1\n"
    ),
    "pkg/b.py": "def render_other():\n    return 2\n\n\ndef lone():\n    return 3\n",
}


def _ranked(issue):
    return sk.sk_rank(sk.sk_index(FILES), issue)


def test_siblings_of_a_hit_are_the_other_definitions_of_its_file_best_first():
    sib = sk.sk_siblings_of(_ranked("render table rows"), "pkg.a.render_table")
    ids = [c["id"] for c in sib]
    assert set(ids) == {"pkg.a.render_row", "pkg.a.helper_a"}
    assert ids[0] == "pkg.a.render_row"  # shares the words render and row with the issue


def test_siblings_are_capped_and_never_cross_files():
    ranked = _ranked("render table rows")
    assert len(sk.sk_siblings_of(ranked, "pkg.a.render_table", cap=1)) == 1
    assert all(c["path"] == "pkg/a.py" for c in sk.sk_siblings_of(ranked, "pkg.a.render_table"))


def test_siblings_of_an_unknown_id_is_empty():
    assert sk.sk_siblings_of(_ranked("render"), "pkg.zzz.nope") == []


def test_format_siblings_lists_each_file_once_with_line_numbers():
    out = sk.sk_format_siblings(_ranked("render table rows"), hits=3, cap=8, budget=3000)
    assert out.count("pkg/a.py") == 1
    assert "pkg.a.render_row" in out and ":5" in out


def test_format_siblings_respects_the_character_budget():
    big = {
        "pkg/m.py": "".join(f"def function_number_{i}():\n    return {i}\n\n\n" for i in range(60))
    }
    ranked = sk.sk_rank(sk.sk_index(big), "function number")
    assert len(sk.sk_format_siblings(ranked, hits=3, cap=8, budget=300)) <= 300
    assert sk.sk_format_siblings(ranked, hits=3, cap=8, budget=0) == ""


def test_main_prints_siblings_only_when_asked(tmp_path, capsys):
    for name, text in FILES.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    assert sk.sk_main(["localize.py", "--root", str(tmp_path), "render table rows"]) == 0
    assert "Same file" not in capsys.readouterr().out
    argv = ["localize.py", "--root", str(tmp_path), "--siblings", "render table rows"]
    assert sk.sk_main(argv) == 0
    both = capsys.readouterr().out
    assert "Same file" in both and len(both) <= 3000


SIB_GRAPH = {
    "nodes": [
        {"id": i}
        for i in (
            "pkg.a.render_table",
            "pkg.a.render_row",
            "pkg.a.helper_a",
            "pkg.b.render_other",
            "tests.x",
        )
    ]
}
TASK = {"instance_id": "pkg_2", "repo": "o/pkg", "problem_statement": "render table row"}


def test_sibling_rows_reveal_each_gold_node_and_score_the_rest():
    gold = {"pkg.a.render_table", "pkg.a.render_row"}
    rows = ss.ss_sibling_rows(TASK, SIB_GRAPH, FILES, gold)
    by = {r["method"]: r for r in rows}
    file_row = by["skill_siblings_file"]
    # revealing either gold node gives the other two defs of the file; the other gold is in it
    assert file_row["queries"] == 2 and file_row["recall"] == 1.0
    assert file_row["precision"] == 0.5 and file_row["set_size"] == 2.0
    assert by["skill_siblings_cap1"]["set_size"] == 1.0


def test_sibling_rows_skip_tasks_outside_two_to_twenty_gold_nodes():
    assert ss.ss_sibling_rows(TASK, SIB_GRAPH, FILES, {"pkg.a.render_table"}) == []
    many = {f"pkg.a.f{i}" for i in range(25)}
    graph = {"nodes": [{"id": i} for i in many]}
    assert ss.ss_sibling_rows(TASK, graph, FILES, many) == []


def test_a_gold_node_the_skill_never_indexed_gives_an_empty_set():
    files = {"pkg/a.py": "def render_row():\n    pass\n\n\ndef helper():\n    pass\n"}
    graph = {"nodes": [{"id": "pkg.a.render_row"}, {"id": "pkg.a.ghost"}]}
    rows = ss.ss_sibling_rows(TASK, graph, files, {"pkg.a.render_row", "pkg.a.ghost"})
    file_row = {r["method"]: r for r in rows}["skill_siblings_file"]
    assert file_row["queries"] == 2
    assert file_row["recall"] == 0.0  # ghost is not in any file, and an unindexed query is empty


def test_sibling_summary_averages_by_method_and_repo():
    rows = [
        {"repo": "a/a", "method": "m", "recall": 1.0, "precision": 0.5, "set_size": 2.0},
        {"repo": "b/b", "method": "m", "recall": 0.0, "precision": 0.0, "set_size": 4.0},
    ]
    out = {(r["repo"], r["method"]): r for r in ss.ss_sibling_summary(rows)}
    allr = out[("all repos", "m")]
    assert allr["tasks"] == 2 and allr["recall"] == 0.5 and allr["mean_set_size"] == 3.0


def test_synthetic_score_reports_how_often_siblings_rescue_the_gold_node(tmp_path):
    root = tmp_path / "src"
    (root / "toy").mkdir(parents=True)
    (root / "toy" / "__init__.py").write_text("")
    body = "".join(f"def util_{i}(x):\n    return x + {i}\n\n\n" for i in range(30))
    body += "def is_big(x):\n    if x > 10:\n        return True\n    return False\n"
    (root / "toy" / "core.py").write_text(body)
    recs = mutate.generate(root, n=5, seed=0, repo="toy", commit="abc")
    res = score_records(recs, root, leak=0.0)
    s = res["siblings"]
    assert s["n"] == len(recs)
    assert 0.0 <= s["rescued"] <= 1.0
    assert s["hit@10_plus_siblings"] >= res["skill"]["hit@10"]
