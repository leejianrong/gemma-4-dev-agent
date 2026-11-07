import csv
import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pod" / "rehearse"))
import eda_extract  # noqa: E402
import fixture  # noqa: E402


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_task_row_counts_patch_and_issue_features():
    t = {
        "instance_id": "pkg_1",
        "repo": "o/pkg",
        "base_commit": "c0",
        "created_at": "2025-01-01",
        "problem_statement": (
            "Calling `alpha` in pkg/mod.py fails.\n```py\nalpha(1)\n```\n"
            "Traceback (most recent call last)\nsee https://x.y"
        ),
        "hints_text": "",
        "patch": fixture.PATCH,
        "test_patch": (
            "--- a/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1,1 +1,3 @@\n"
            " x = 1\n+def test_alpha():\n+    assert True\n"
        ),
    }
    r = eda_extract.eda_task_row(t, Path("/nonexistent"))
    assert r["code_blocks"] == 1 and r["has_traceback"] == 1 and r["urls"] == 1
    assert r["patch_files"] == 1 and r["patch_lib_files"] == 1 and r["patch_removed"] == 1
    assert r["issue_mentions_hunk_symbol"] == 1 and r["issue_mentions_patch_module"] == 1
    assert r["test_funcs_added"] == 1 and r["snapshot_mib"] == ""


def test_library_filter_excludes_docs_scripts_tests():
    assert eda_extract.eda_is_library("fastapi/routing.py")
    assert not eda_extract.eda_is_library("docs_src/app/tutorial001.py")
    assert not eda_extract.eda_is_library("scripts/release.py")
    assert not eda_extract.eda_is_library("README.md")


def test_node_helpers():
    assert eda_extract.eda_kind("pkg.mod.Klass") == "class_like"
    assert eda_extract.eda_kind("pkg.mod.func") == "function_like"
    assert eda_extract.eda_module2("fastapi._compat.v2.ModelField.validate") == "fastapi._compat"
    assert eda_extract.eda_parent("pkg.mod.Klass.meth") == "pkg.mod.Klass"


def test_largest_component_and_degrees():
    edges = [
        {"source": "a", "target": "b"},
        {"source": "b", "target": "c"},
        {"source": "d", "target": "d"},
    ]
    indeg, outdeg, adj = eda_extract.eda_degrees([], edges)
    assert outdeg["a"] == 1 and indeg["c"] == 1
    assert eda_extract.eda_largest_component(["a", "b", "c", "d"], adj) == 3


def test_run_writes_all_tables_without_numpy_embeddings(tmp_path, monkeypatch):
    fixture.main(tmp_path / "d")
    rep = eda_extract.eda_run(tmp_path / "d", tmp_path / "o")
    assert rep["tasks.csv"] == 5 and rep["graph_stats.csv"] == 5
    assert (tmp_path / "o" / "report.json").is_file()
    assert json.loads((tmp_path / "o" / "report.json").read_text())["total_mib"] < 1
    t = rows(tmp_path / "o" / "tasks.csv")
    assert t[0]["repo"] == "o/pkg"
    with gzip.open(tmp_path / "o" / "node_degrees.csv.gz", "rt") as f:
        assert len(list(csv.reader(f))) == 1 + 5  # header + one node per graph


def test_embedding_knn_agreement_against_random_baseline(tmp_path):
    np = pytest.importorskip("numpy")
    ids = [f"pkg.mod.f{i}" for i in range(12)]
    rng = np.random.default_rng(0)
    base = rng.normal(size=(12, 256)).astype("float32")
    base[1] = base[0] + 0.01  # f1 is f0's nearest neighbour
    path = tmp_path / "e.npz"
    np.savez(path, **dict(zip(ids, base, strict=True)))
    adj = {ids[0]: {ids[1]}, ids[1]: {ids[0]}}
    nodes = [{"id": i} for i in ids]
    import random

    nn, sample, got, dups = eda_extract.eda_embeddings(
        np, path, nodes, adj, {ids[0]}, random.Random(1), k=3, n_query=12
    )
    row = next(r for r in nn if r["is_edited"] == 1)
    assert row["hits_1hop"] == 1 and row["degree"] == 1 and row["k"] == 3
    assert row["expected_1hop"] == pytest.approx(3 * 1 / 11, abs=1e-3)
    assert len(sample) == 12 and len(sample[0][1]) == 256 and len(got) == 12
    assert dups[0]["duplicate_groups"] == 0 and dups[0]["unique_vectors"] == 12


def test_duplicate_vectors_are_grouped_and_classified():
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(1)
    v = {k: rng.normal(size=256).astype("float32") for k in "abcd"}
    ids = [
        "pkg.mod.Klass",  # parent of the next node: shares a vector with it
        "pkg.mod.Klass.run",
        "pkg.mod.one",  # siblings with identical text
        "pkg.mod.two",
        "pkg.x.alpha",  # unrelated pair
        "pkg.y.beta",
        "pkg.mod.solo",
    ]
    vecs = [v["a"], v["a"], v["b"], v["b"], v["c"], v["c"], v["d"]]
    mat = np.stack(vecs)
    text = {"pkg.mod.one": "def f(): pass", "pkg.mod.two": "def f(): pass"}
    nodes = [{"id": i, "text": text.get(i, f"body of {i}")} for i in ids]
    summary, examples = eda_extract.eda_duplicates(np, ids, mat, nodes, "stem", "o/pkg")
    assert summary["unique_vectors"] == 4 and summary["duplicate_groups"] == 3
    assert summary["nodes_in_duplicate_groups"] == 6 and summary["largest_group"] == 2
    assert summary["groups_parent_child"] == 1 and summary["groups_siblings"] == 1
    assert summary["groups_unrelated"] == 1 and summary["groups_identical_text"] == 1
    assert {e["relation"] for e in examples} == {"parent_child", "siblings", "unrelated"}
