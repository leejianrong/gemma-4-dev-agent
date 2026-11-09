import csv
import json

from synthetic import mutate
from synthetic.export import export_bundle, problem_statement

SRC = {
    "toy/__init__.py": "",
    "toy/core.py": (
        "def is_big(x):\n    if x > 10:\n        return True\n    return False\n\n\n"
        "def pick(items, k):\n    return items[k - 1]\n"
    ),
}


def make(tmp_path):
    root = tmp_path / "src"
    for rel, text in SRC.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    recs = mutate.generate(root, n=4, seed=0, repo="toy", commit="abc")
    out = tmp_path / "bundle"
    summary = export_bundle(recs, root, out, "toy", "abc")
    rows = [json.loads(line) for line in (out / "tasks.jsonl").read_text().splitlines()]
    return root, recs, out, summary, rows


def test_bundle_has_the_competition_files_and_fields(tmp_path):
    _, recs, out, summary, rows = make(tmp_path)
    assert recs and len(rows) == len(recs) == summary["tasks"]
    fields = {"instance_id", "repo", "base_commit", "patch", "test_patch", "problem_statement"}
    assert set(rows[0]) == fields | {"hints_text", "created_at"}
    assert all(isinstance(v, str) for r in rows for v in r.values())
    assert rows[0]["repo"] == "synthetic/toy" and rows[0]["test_patch"] == ""
    assert len(rows[0]["base_commit"]) == 40 and len(rows[0]["created_at"]) == 20
    for r in rows:
        assert (out / "graphs" / f"toy_{r['base_commit']}.json").is_file()
        assert (out / "embeddings" / f"toy_{r['base_commit']}.npz").is_file()


def test_patch_is_the_gold_reverse_patch_and_gold_csv_maps_ids(tmp_path):
    _, recs, out, _, rows = make(tmp_path)
    gold = list(csv.DictReader(open(out / "gold_nodes.csv")))
    assert [g["instance_id"] for g in gold] == [r["instance_id"] for r in rows]
    assert [g["gold_node"] for g in gold] == [r["gold_node"] for r in recs]
    assert [r["patch"] for r in rows] == [r["gold_patch"] for r in recs]


def test_task_graph_holds_the_mutated_text_not_the_original(tmp_path):
    _, recs, out, _, rows = make(tmp_path)
    g = json.loads((out / "graphs" / f"toy_{rows[0]['base_commit']}.json").read_text())
    node = next(n for n in g["nodes"] if n["id"] == recs[0]["gold_node"])
    changed = recs[0]["mutated_text"].splitlines()[recs[0]["line"] - 1].strip()
    assert changed in node["text"]


def test_problem_statement_names_the_symptom_never_the_node():
    recs = [
        {"operator": op, "gold_node": "toy.core.is_big", "id": f"x{i}"}
        for i, op in enumerate(mutate.OPERATORS)
    ]
    for r in recs:
        text = problem_statement(r)
        assert "is_big" not in text and "toy" not in text and len(text) > 40
    assert problem_statement(recs[0]) == problem_statement(dict(recs[0]))


def test_leak_option_adds_the_short_name():
    r = {"operator": "cmp_swap", "gold_node": "toy.core.is_big", "id": "x"}
    assert "is_big" in problem_statement(r, leak=1.0)
    assert "is_big" not in problem_statement(r, leak=0.0)
