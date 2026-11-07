import csv
import json

import cochange as cc
import numpy as np

IDS = [
    "pkg.a.f",
    "pkg.a.g",
    "pkg.a.Thing",
    "pkg.a.Thing.run",
    "pkg.a.Thing.stop",
    "pkg.b.h",
    "pkg.b.k",
    "tests.test_a.test_f",
]
EDGES = [
    {"source": "pkg.a.f", "target": "pkg.b.h"},
    {"source": "pkg.b.h", "target": "pkg.b.k"},
]


def graph():
    return {"nodes": [{"id": i, "text": ""} for i in IDS], "edges": EDGES}


def test_module_and_class_keys_handle_methods_and_functions():
    assert cc.cc_module("pkg.a.Thing.run") == "pkg.a" and cc.cc_module("pkg.a.f") == "pkg.a"
    assert cc.cc_class("pkg.a.Thing.run") == "pkg.a.Thing" and cc.cc_class("pkg.a.f") is None


def test_within_counts_hops_and_never_returns_the_query():
    adj = {"a": {"b"}, "b": {"a", "c"}, "c": {"b"}}
    assert cc.cc_within(adj, "a", 1) == {"b"} and cc.cc_within(adj, "a", 2) == {"b", "c"}


def test_candidates_exclude_the_query_and_the_non_library_pool():
    pool = [i for i in IDS if not i.startswith("tests")]
    got = cc.cc_candidates(np, "pkg.a.f", pool, cc.adjacency(EDGES), None)
    assert got["hop1"] == {"pkg.b.h"} and got["hop2"] == {"pkg.b.h", "pkg.b.k"}
    assert "pkg.a.f" not in got["same_module"] and "tests.test_a.test_f" not in got["same_module"]
    assert got["same_class"] == set() and "embedding10" not in got


def test_task_rows_leave_one_out_with_a_chance_rate():
    task = {"instance_id": "p_1", "repo": "o/p"}
    rows = cc.cc_task_rows(np, task, graph(), None, {"pkg.a.f", "pkg.b.h"})
    by = {r["method"]: r for r in rows}
    assert by["hop1"]["recall"] == 1.0 and by["hop1"]["precision"] == 0.75
    assert by["same_module"]["recall"] == 0.0
    assert by["hop1"]["base_rate"] == round(1 / 6, 5) and by["hop1"]["lift"] == 4.5


def test_tasks_with_one_or_too_many_gold_nodes_produce_no_rows():
    task = {"instance_id": "p_1", "repo": "o/p"}
    assert cc.cc_task_rows(np, task, graph(), None, {"pkg.a.f"}) == []
    many = {f"pkg.a.n{i}" for i in range(cc.CC_MAX_GOLD + 1)}
    g = {"nodes": [{"id": i} for i in many], "edges": []}
    assert cc.cc_task_rows(np, task, g, None, many) == []


def test_end_to_end_run_reports_skips_and_a_summary(tmp_path):
    data = tmp_path / "d"
    (data / "graphs").mkdir(parents=True)
    (data / "embeddings").mkdir()
    t = {"instance_id": "p_1", "repo": "o/p", "base_commit": "c0"}
    lines = [json.dumps(t), json.dumps({**t, "instance_id": "p_2"})]
    (data / "tasks.jsonl").write_text("\n".join(lines) + "\n")
    (data / "graphs" / "p_c0.json").write_text(json.dumps(graph()))
    gold = tmp_path / "gold.csv"
    with open(gold, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["instance_id", "node_id"])
        w.writerows([["p_1", "pkg.a.f"], ["p_1", "pkg.b.h"], ["p_2", "pkg.a.g"]])
    rep = cc.cc_run(data, gold, tmp_path / "o")
    assert rep["tasks_scored"] == 1 and rep["skipped"] == {"fewer_than_2_gold_nodes": 1}
    summ = list(csv.DictReader(open(tmp_path / "o" / "cochange_summary.csv")))
    row = next(r for r in summ if r["repo"] == "all repos" and r["method"] == "hop1")
    assert row["recall"] == "1.0" and row["tasks"] == "1"
