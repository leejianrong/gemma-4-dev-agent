"""Score the localizer skill on synthetic tasks, with the graph-text BM25 for comparison.

For each mutation record the buggy tree is the source tree with the mutated file swapped in. The
skill ranks the definitions of that tree (`experiments/skills/localize/scripts/localize.py`,
imported by path) and the comparison ranker is BM25 over graph node text from `synthetic.graph`.
A task is a hit at k when its gold node is among the top k ids. Library pool only.
`siblings.rescued` is the share of tasks where the gold node is outside the top 10 but is one of
the up to 8 same-file definitions the skill lists for each of its top 3 hits.
Usage: python -m synthetic.score_localize SRC_DIR --repo NAME --n 100 --seed 0 [--leak 0.0]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

from synthetic import mutate
from synthetic.export import problem_statement
from synthetic.graph import graph_nodes, read_tree

SKILL = Path(__file__).resolve().parents[1] / "experiments/skills/localize/scripts/localize.py"
NON_LIB = {"tests", "test", "docs", "docs_src", "examples", "scripts"}


def load_skill():
    spec = importlib.util.spec_from_file_location("localize_skill", SKILL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["localize_skill"] = mod
    spec.loader.exec_module(mod)
    return mod


def summarize_hits(ranks: list[int | None]) -> dict:
    n = len(ranks)

    def hit(k: int) -> float:
        return round(sum(r is not None and r <= k for r in ranks) / max(n, 1), 3)

    return {
        "n": n,
        "hit@1": hit(1),
        "hit@5": hit(5),
        "hit@10": hit(10),
        "found": sum(r is not None for r in ranks),
    }


def _rank_of(gold: str, ids: list[str]) -> int | None:
    return ids.index(gold) + 1 if gold in ids else None


def score_records(
    records: list[dict], src_root: Path, leak: float = 0.0, class_text: str = "head"
) -> dict:
    sk = load_skill()
    files = read_tree(src_root)
    base = {
        path: [dict(c, path=path) for c in sk.sk_defs(text, sk.sk_module_id(path), class_text)]
        for path, text in sorted(files.items())
        if sk.sk_is_library(path)
    }
    skill_ranks, graph_ranks = [], []
    in_top10 = rescued = 0
    t_skill = t_graph = 0.0
    for rec in records:
        issue = problem_statement(rec, leak)
        path = rec["file"]
        t0 = time.perf_counter()
        cands: list[dict] = []
        for p, defs in base.items():
            if p == path:
                fresh = sk.sk_defs(rec["mutated_text"], sk.sk_module_id(p), class_text)
                defs = [dict(c, path=p) for c in fresh]
            cands += defs
        ranked = sk.sk_rank(cands, issue)
        t_skill += time.perf_counter() - t0
        skill_ranks.append(_rank_of(rec["gold_node"], [c["id"] for c, _ in ranked]))
        top10 = {c["id"] for c, _ in ranked[:10]}
        sib = {s["id"] for c, _ in ranked[:3] for s in sk.sk_siblings_of(ranked, c["id"], 8)}
        in_top10 += rec["gold_node"] in top10
        rescued += rec["gold_node"] not in top10 and rec["gold_node"] in sib
        t0 = time.perf_counter()
        task_files = dict(files)
        task_files[path] = rec["mutated_text"]
        nodes = [n for n in graph_nodes(task_files) if n["id"].split(".")[0] not in NON_LIB]
        docs = [sk.sk_tokens(n["id"].replace(".", " ") + " " + n["text"]) for n in nodes]
        scores = sk.sk_bm25(docs)(sk.sk_tokens(issue))
        order = sorted(zip(nodes, scores, strict=True), key=lambda p: (-p[1], p[0]["id"]))
        graph_ranks.append(_rank_of(rec["gold_node"], [n["id"] for n, _ in order]))
        t_graph += time.perf_counter() - t0
    n = max(len(records), 1)
    return {
        "skill": dict(summarize_hits(skill_ranks), seconds_per_task=round(t_skill / n, 4)),
        "graph_bm25": dict(summarize_hits(graph_ranks), seconds_per_task=round(t_graph / n, 4)),
        "siblings": {
            "n": len(records),
            "rescued": round(rescued / n, 3),
            "hit@10_plus_siblings": round((in_top10 + rescued) / n, 3),
        },
        "leak": leak,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--leak", type=float, default=0.0)
    ap.add_argument("--class-text", default="head", choices=["head", "full"])
    args = ap.parse_args(argv[1:])
    recs = mutate.generate(Path(args.src), n=args.n, seed=args.seed, repo=args.repo)
    res = score_records(recs, Path(args.src), args.leak, args.class_text)
    res["mutants"] = mutate.summarize(recs)["mutants"]
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
