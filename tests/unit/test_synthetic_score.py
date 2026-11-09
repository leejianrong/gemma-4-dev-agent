from synthetic import mutate
from synthetic.score_localize import score_records, summarize_hits


def test_summarize_hits_counts_the_first_gold_rank():
    s = summarize_hits([1, 4, 11, None])
    assert s == {"n": 4, "hit@1": 0.25, "hit@5": 0.5, "hit@10": 0.5, "found": 3}


def test_score_runs_both_rankers_on_a_toy_tree(tmp_path):
    root = tmp_path / "src"
    (root / "toy").mkdir(parents=True)
    (root / "toy" / "__init__.py").write_text("")
    (root / "toy" / "core.py").write_text(
        "def is_big(x):\n    if x > 10:\n        return True\n    return False\n\n\n"
        "def pick(items, k):\n    return items[k - 1]\n\n\n"
        "def total(items):\n    s = 0\n    for i in items:\n        s += i\n    return s\n"
    )
    recs = mutate.generate(root, n=5, seed=0, repo="toy", commit="abc")
    res = score_records(recs, root, leak=1.0)
    for ranker in ("skill", "graph_bm25"):
        assert res[ranker]["n"] == len(recs)
        assert res[ranker]["hit@10"] == 1.0  # a 3-function tree and the name is leaked
