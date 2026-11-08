import csv
import json

import localize as ll
import numpy as np


def test_tokens_split_identifiers_and_keep_the_whole_word():
    t = ll.ll_tokens("parseHeader and get_user_id")
    assert {"parse", "header", "parseheader", "get", "user", "id", "get_user_id"} - {
        "get_user_id"
    } <= set(t)
    assert "and" not in t and "the" not in ll.ll_tokens("the cat")


def test_bm25_ranks_the_matching_document_first_and_ignores_unseen_terms():
    docs = [ll.ll_tokens(x) for x in ["render table columns", "open socket", "table of contents"]]
    s = ll.ll_bm25(docs)(ll.ll_tokens("table columns zzz"))
    assert s[0] > s[2] > s[1] == 0.0


def test_order_breaks_ties_by_id_so_identical_nodes_are_reproducible():
    assert ll.ll_order(["b", "a", "c"], [1.0, 1.0, 2.0]) == ["c", "a", "b"]


def test_expand_lifts_a_neighbour_of_the_top_seed_above_unlinked_nodes():
    ids = ["a", "b", "c", "d"]
    base = [10.0, 1.0, 1.0, 0.0]
    out = ll.ll_expand(ids, base, {"a": {"d": 1.0}}, seeds=1)
    assert ll.ll_order(ids, out)[:2] == ["a", "d"]
    assert ll.ll_expand(ids, [0.0] * 4, {"a": {"d": 1.0}}) == [0.0] * 4


def test_append_keeps_the_bm25_head_then_adds_seed_neighbours_then_the_rest():
    ids = ["a", "b", "c", "d", "e"]
    base = [5.0, 4.0, 3.0, 0.0, 0.0]
    nb = {"a": {"e": 0.9, "d": 0.2}}
    assert ll.ll_append(ids, base, nb, head=2, seeds=1) == ["a", "b", "e", "d", "c"]
    assert ll.ll_append(ids, base, {}, head=2, seeds=1) == ["a", "b", "c", "d", "e"]


def test_embedding_neighbours_are_mean_centred_so_a_shared_offset_does_not_matter():
    base = {"a": [1, 0, 0], "b": [0.9, 0.1, 0], "c": [0, 1, 0], "d": [0, 0, 1]}
    shifted = {k: [x + 100 for x in v] for k, v in base.items()}
    got = ll.ll_embedding_neighbours(np, shifted, ["a"], k=1)
    assert list(got["a"]) == ["b"]
    assert list(ll.ll_embedding_neighbours(np, base, ["a"], k=1)["a"]) == ["b"]


def test_metrics_recall_hit_and_best_rank():
    m = ll.ll_metrics(["x", "g1", "y", "z"], {"g1", "g2"})
    assert m["recall@1"] == 0 and m["recall@5"] == 0.5 and m["hit@5"] == 1.0 and m["best_rank"] == 2
    assert ll.ll_metrics(["x"], {"g"})["best_rank"] == ""


def test_library_filter_drops_tests_and_docs_nodes():
    assert ll.ll_is_library("fastapi.routing.APIRoute")
    assert not ll.ll_is_library("tests.test_routing.test_x")
    assert not ll.ll_is_library("docs_src.tutorial.main.read")


def graph():
    names = [
        "pkg.table.render",
        "pkg.table.columns",
        "pkg.sock.open",
        "tests.test_table.test_render",
    ]
    nodes = [
        {"id": n, "text": t}
        for n, t in zip(
            names,
            [
                "def render(t): draw table columns",
                "def columns(t): return cols",
                "def open(): socket",
                "def test_render(): table",
            ],
            strict=True,
        )
    ]
    return {
        "nodes": nodes,
        "edges": [{"source": "pkg.table.render", "target": "pkg.table.columns"}],
    }


def test_task_rows_score_every_method_in_both_pools():
    task = {"instance_id": "p_1", "repo": "o/p", "problem_statement": "render table is broken"}
    rows = ll.ll_task_rows(np, task, graph(), None, {"pkg.table.columns"})
    got = {(r["pool"], r["method"]): r for r in rows}
    assert set(got) == {
        (p, m)
        for p in ("all", "library")
        for m in ("random", "bm25", "bm25_graph", "bm25_then_graph")
    }
    assert (
        got[("library", "bm25")]["n_candidates"] == 3 and got[("all", "bm25")]["n_candidates"] == 4
    )
    # columns is not named by the issue; the graph edge from the top seed (render) lifts it
    assert got[("library", "bm25_graph")]["best_rank"] <= got[("library", "bm25")]["best_rank"]


def test_a_gold_node_outside_the_pool_is_dropped_not_counted_as_a_miss():
    task = {"instance_id": "p_1", "repo": "o/p", "problem_statement": "render"}
    rows = ll.ll_task_rows(np, task, graph(), None, {"tests.test_table.test_render"})
    assert {r["pool"] for r in rows} == {"all"}


def test_end_to_end_run_writes_tasks_summary_and_report(tmp_path):
    data = tmp_path / "d"
    (data / "graphs").mkdir(parents=True)
    (data / "embeddings").mkdir()
    task = {
        "instance_id": "p_1",
        "repo": "o/p",
        "base_commit": "c0",
        "problem_statement": "render table",
    }
    (data / "tasks.jsonl").write_text(
        json.dumps(task) + "\n" + json.dumps({**task, "instance_id": "p_2"}) + "\n"
    )
    (data / "graphs" / "p_c0.json").write_text(json.dumps(graph()))
    g = graph()
    np.savez(
        data / "embeddings" / "p_c0.npz",
        **{n["id"]: np.arange(4, dtype=np.float32) + i for i, n in enumerate(g["nodes"])},
    )
    gold = tmp_path / "gold.csv"
    with open(gold, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["instance_id", "node_id"])
        w.writerow(["p_1", "pkg.table.render"])
    rep = ll.ll_run(data, gold, tmp_path / "o")
    assert rep["tasks_scored"] == 1 and rep["skipped"] == {"no_gold_node": 1}
    summ = list(csv.DictReader(open(tmp_path / "o" / "localize_summary.csv")))
    pooled = [
        r
        for r in summ
        if r["repo"] == "all repos" and r["pool"] == "library" and r["method"] == "bm25"
    ]
    assert pooled[0]["recall@1"] == "1.0" and pooled[0]["tasks"] == "1"
    tasks = list(csv.DictReader(open(tmp_path / "o" / "localize_tasks.csv")))
    bm = next(r for r in tasks if r["method"] == "bm25" and r["pool"] == "library")
    assert bm["gold"] == "pkg.table.render" and bm["top"].split("|")[0] == "pkg.table.render"
