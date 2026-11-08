"""Localization baselines: rank graph nodes from the issue text, score recall against gold nodes.

No model is involved. The agent has no free-text embedder offline (`search_similar_code` takes a
symbol name), so the embedding methods are seed-and-expand: BM25 picks seeds, then the graph edges
or the mean-centred embedding neighbours of the seeds lift related nodes. That mirrors what an agent
can do with its tools. Gold nodes come from pod/gold_map.py (gold_nodes.csv).
"""

from __future__ import annotations

import collections
import csv
import json
import math
import random
import re
import sys
from pathlib import Path

if "load_graph" not in globals():  # standalone; inside the kernel explore.py is inlined above
    from explore import adjacency, load_graph

LL_NON_LIB = ("tests", "test", "docs_src", "docs", "scripts", "examples")
LL_KS = (1, 5, 10)
LL_TOP = 20
LL_SEEDS = 3
LL_LAMBDA = 0.5
LL_KNN = 10
LL_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*|\d+")
LL_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
LL_STOP = frozenset(
    "the a an and or of to in is it this that for on with as be are was not but if at by from "
    "when then so do does did have has had can will would should could i we you my our your "
    "self cls none true false return def class import".split()
)
LL_HEAD = 5
LL_METHODS = (
    "random",
    "bm25",
    "bm25_graph",
    "bm25_embedding",
    "bm25_then_graph",
    "bm25_then_embedding",
)


def ll_tokens(text: str) -> list[str]:
    """Lowercase word pieces; identifiers split on snake and camel case, whole word kept."""
    out: list[str] = []
    for word in LL_WORD.findall(text or ""):
        parts = [p.lower() for p in LL_CAMEL.findall(word)]
        out += [p for p in parts if len(p) > 1 and p not in LL_STOP]
        if len(parts) > 1 and word.lower() not in LL_STOP:
            out.append(word.lower())
    return out


def ll_is_library(node_id: str) -> bool:
    top = node_id.split(".", 1)[0]
    return top not in LL_NON_LIB and not top.startswith("test_")


def ll_bm25(docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
    """A scorer for a fixed document set: scorer(query_tokens) -> one score per document."""
    n = len(docs)
    avg = sum(len(d) for d in docs) / max(n, 1)
    df: collections.Counter = collections.Counter()
    for d in docs:
        df.update(set(d))
    tfs = [collections.Counter(d) for d in docs]
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scorer(query: list[str]) -> list[float]:
        q = set(query)
        scores = []
        for tf, d in zip(tfs, docs, strict=True):
            norm = k1 * (1 - b + b * len(d) / max(avg, 1e-9))
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += idf[t] * f * (k1 + 1) / (f + norm)
            scores.append(s)
        return scores

    return scorer


def ll_order(ids: list[str], scores: list[float]) -> list[str]:
    """Best first; ties break by id so identical-text nodes rank reproducibly."""
    return [i for i, _ in sorted(zip(ids, scores, strict=True), key=lambda p: (-p[1], p[0]))]


def ll_expand(
    ids: list[str],
    base: list[float],
    neighbours: dict[str, dict[str, float]],
    seeds: int = LL_SEEDS,
) -> list[float]:
    """Add lam * seed_score * link_weight to every node linked to one of the top seeds."""
    top = max(base) if base else 0.0
    if top <= 0:
        return list(base)
    pos = {i: j for j, i in enumerate(ids)}
    seed_ids = ll_order(ids, base)[:seeds]
    out = [s / top for s in base]
    for sid in seed_ids:
        w = base[pos[sid]] / top
        for nid, link in neighbours.get(sid, {}).items():
            if nid in pos and nid != sid:
                out[pos[nid]] += LL_LAMBDA * w * link
    return out


def ll_append(
    ids: list[str],
    base: list[float],
    neighbours: dict[str, dict[str, float]],
    head: int = LL_HEAD,
    seeds: int = LL_SEEDS,
) -> list[str]:
    """What an agent does with the tools: its best `head` BM25 hits, then the seeds' neighbours.

    Neighbours go in seed-rank order, strongest link first, then the rest of the BM25 order.
    """
    order = ll_order(ids, base)
    out = order[:head]
    seen = set(out)
    for sid in order[:seeds]:
        links = neighbours.get(sid, {})
        for nid in sorted(links, key=lambda n: (-links[n], n)):
            if nid in set(ids) and nid not in seen:
                out.append(nid)
                seen.add(nid)
    return out + [i for i in order if i not in seen]


def ll_graph_neighbours(edges: list[dict]) -> dict[str, dict[str, float]]:
    return {n: {m: 1.0 for m in ms} for n, ms in adjacency(edges).items()}


def ll_embedding_neighbours(np, vectors: dict[str, list[float]], seeds: list[str], k: int = LL_KNN):
    """Top-k mean-centred cosine neighbours for each seed; raw cosine is near-constant (EDA 3)."""
    ids = sorted(vectors)
    mat = np.stack([np.asarray(vectors[i], dtype=np.float32) for i in ids])
    mat = mat - mat.mean(axis=0, keepdims=True)
    unit = mat / np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9)
    pos = {i: j for j, i in enumerate(ids)}
    out: dict[str, dict[str, float]] = {}
    for s in seeds:
        if s not in pos:
            continue
        sims = unit @ unit[pos[s]]
        sims[pos[s]] = -np.inf
        top = np.argsort(-sims, kind="stable")[: min(k, len(ids) - 1)]
        out[s] = {ids[j]: float(max(sims[j], 0.0)) for j in top}
    return out


def ll_metrics(ranked: list[str], gold: set[str]) -> dict:
    row: dict = {"n_gold": len(gold)}
    for k in LL_KS:
        got = len(set(ranked[:k]) & gold)
        row[f"recall@{k}"] = got / len(gold)
        row[f"hit@{k}"] = 1.0 if got else 0.0
    ranks = [r for r, i in enumerate(ranked, 1) if i in gold]
    row["best_rank"] = ranks[0] if ranks else ""
    return row


def ll_random_ranking(ids: list[str], seed: str) -> list[str]:
    rng = random.Random(seed)
    shuffled = sorted(ids)
    rng.shuffle(shuffled)
    return shuffled


def ll_task_rows(np, task: dict, graph: dict, vectors: dict | None, gold: set[str]) -> list[dict]:
    """One row per (pool, method): pool 'all' ranks every node, 'library' skips tests and docs."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    rows = []
    query = ll_tokens(task.get("problem_statement") or "")
    edges = ll_graph_neighbours(graph.get("edges", []))
    for pool in ("all", "library"):
        ids = sorted(i for i in nodes if pool == "all" or ll_is_library(i))
        target = gold & set(ids)
        if not target:
            continue
        docs = [ll_tokens(i.replace(".", " ") + " " + (nodes[i].get("text") or "")) for i in ids]
        base = ll_bm25(docs)(query)
        runs = {
            "random": ll_random_ranking(ids, task["instance_id"]),
            "bm25": ll_order(ids, base),
            "bm25_graph": ll_order(ids, ll_expand(ids, base, edges)),
            "bm25_then_graph": ll_append(ids, base, edges),
        }
        if vectors:
            have = {i: vectors[i] for i in ids if i in vectors}
            seeds = ll_order(ids, base)[:LL_SEEDS]
            emb = ll_embedding_neighbours(np, have, seeds) if len(have) > LL_KNN else {}
            runs["bm25_embedding"] = ll_order(ids, ll_expand(ids, base, emb))
            runs["bm25_then_embedding"] = ll_append(ids, base, emb)
        for method, ranked in runs.items():
            rows.append(
                {
                    "instance_id": task["instance_id"],
                    "repo": task["repo"],
                    "pool": pool,
                    "method": method,
                    "n_candidates": len(ids),
                    "n_gold_in_pool": len(target),
                    "n_gold_total": len(gold),
                    **ll_metrics(ranked, target),
                    "gold": "|".join(sorted(target)),
                    "top": "|".join(ranked[:LL_TOP]),
                }
            )
    return rows


def ll_gold(path: Path) -> dict[str, set[str]]:
    gold: dict[str, set[str]] = collections.defaultdict(set)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            gold[r["instance_id"]].add(r["node_id"])
    return gold


def ll_load_vectors(np, path: Path) -> dict | None:
    try:
        z = np.load(path)
        return {k: z[k] for k in z.files}
    except (OSError, ValueError):
        return None


def ll_summary(rows: list[dict]) -> list[dict]:
    """Mean over tasks per repo and pooled ('all repos'), for every pool and method."""
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in rows:
        groups[(r["repo"], r["pool"], r["method"])].append(r)
        groups[("all repos", r["pool"], r["method"])].append(r)
    out = []
    for (repo, pool, method), rs in sorted(groups.items()):
        row = {"repo": repo, "pool": pool, "method": method, "tasks": len(rs)}
        for k in LL_KS:
            row[f"recall@{k}"] = round(sum(r[f"recall@{k}"] for r in rs) / len(rs), 4)
            row[f"hit@{k}"] = round(sum(r[f"hit@{k}"] for r in rs) / len(rs), 4)
        ranks = sorted(r["best_rank"] for r in rs if r["best_rank"] != "")
        row["median_best_rank"] = ranks[len(ranks) // 2] if ranks else ""
        out.append(row)
    return out


def ll_write(path: Path, rows: list[dict]) -> int:
    if not rows:
        return 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def ll_run(data: Path, gold_csv: Path, out: Path) -> dict:
    import numpy as np

    out.mkdir(parents=True, exist_ok=True)
    gold = ll_gold(gold_csv)
    tasks = [
        json.loads(x)
        for x in (data / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    rows: list[dict] = []
    skipped = collections.Counter()
    for t in tasks:
        g = gold.get(t["instance_id"])
        if not g:
            skipped["no_gold_node"] += 1
            continue
        stem = f"{t['instance_id'].rsplit('_', 1)[0]}_{t['base_commit']}"
        graph = load_graph(data / "graphs" / f"{stem}.json")
        if not graph:
            skipped["no_graph"] += 1
            continue
        vectors = ll_load_vectors(np, data / "embeddings" / f"{stem}.npz")
        if vectors is None:
            skipped["no_embeddings"] += 1
        rows += ll_task_rows(np, t, graph, vectors, g)
    summary = ll_summary(rows)
    ll_write(out / "localize_tasks.csv", rows)
    ll_write(out / "localize_summary.csv", summary)
    report = {
        "tasks_scored": len({r["instance_id"] for r in rows}),
        "skipped": dict(skipped),
        "methods": list(LL_METHODS),
        "seeds": LL_SEEDS,
        "lambda": LL_LAMBDA,
        "knn": LL_KNN,
        "summary": summary,
    }
    (out / "localize_report.json").write_text(json.dumps(report, separators=(",", ":")))
    return report


def ll_main() -> int:
    """Kernel entry: re-derive the gold nodes with gold_map, then score the baselines."""
    gm_run(DATA, OUTD / "map")  # noqa: F821
    report = ll_run(DATA, OUTD / "map" / "gold_nodes.csv", OUTD)  # noqa: F821
    (OUTD / "report.json").write_text(json.dumps(report, separators=(",", ":")))  # noqa: F821
    print(json.dumps(report["summary"][:12], indent=1))
    return 0


def ll_cli(argv: list[str]) -> int:
    report = ll_run(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    print(json.dumps(report["summary"][:12], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(ll_cli(sys.argv))
