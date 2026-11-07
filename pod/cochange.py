"""Co-change: from one edited node, can the graph predict the other nodes the gold patch edits?

Leave-one-out over the mapped gold nodes (pod/gold_map.py) of tasks with 2 to CC_MAX_GOLD library
nodes. Each method names a candidate set from the query node; we score what share of the other gold
nodes it contains (recall), how much of the set is gold (precision), and the lift of precision over
the chance rate (other gold nodes divided by other library nodes). Tasks with more than CC_MAX_GOLD
gold nodes (one patch touches 129) are excluded and counted.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

if "ll_gold" not in globals():  # standalone; inside the kernel the other modules are inlined
    from explore import adjacency, load_graph
    from localize import ll_embedding_neighbours, ll_gold, ll_is_library, ll_load_vectors

CC_MAX_GOLD = 20
CC_METHODS = ("hop1", "hop2", "same_class", "same_module", "embedding10", "hop1_or_module")


def cc_module(node_id: str) -> str:
    """Dotted module: the parts before the first Capitalised one, else all but the last."""
    parts = node_id.split(".")
    for i, p in enumerate(parts):
        if p[:1].isupper():
            return ".".join(parts[:i])
    return ".".join(parts[:-1])


def cc_class(node_id: str) -> str | None:
    """Dotted class of a method (or the class itself); None for a module-level function."""
    parts = node_id.split(".")
    for i, p in enumerate(parts):
        if p[:1].isupper():
            return ".".join(parts[: i + 1])
    return None


def cc_within(adj: dict[str, set[str]], q: str, hops: int) -> set[str]:
    seen, frontier = {q}, {q}
    for _ in range(hops):
        frontier = {y for x in frontier for y in adj.get(x, ())} - seen
        seen |= frontier
    return seen - {q}


def cc_candidates(np, q: str, pool: list[str], adj: dict, vectors: dict | None) -> dict[str, set]:
    """Candidate set per method for query q, restricted to the pool and excluding q itself."""
    inpool = set(pool) - {q}
    mod, cls = cc_module(q), cc_class(q)
    same_mod = {i for i in inpool if cc_module(i) == mod}
    hop1 = cc_within(adj, q, 1) & inpool
    out = {
        "hop1": hop1,
        "hop2": cc_within(adj, q, 2) & inpool,
        "same_class": {i for i in inpool if cls and cc_class(i) == cls},
        "same_module": same_mod,
        "hop1_or_module": hop1 | same_mod,
    }
    if vectors:
        have = {i: vectors[i] for i in pool if i in vectors}
        if q in have and len(have) > 10:
            out["embedding10"] = (
                set(ll_embedding_neighbours(np, have, [q], k=10).get(q, {})) & inpool
            )
    return out


def cc_task_rows(np, task: dict, graph: dict, vectors: dict | None, gold: set[str]) -> list[dict]:
    pool = sorted(i["id"] for i in graph["nodes"] if ll_is_library(i["id"]))
    gold = gold & set(pool)
    if not 2 <= len(gold) <= CC_MAX_GOLD:
        return []
    adj = adjacency(graph.get("edges", []))
    base_rate = (len(gold) - 1) / max(len(pool) - 1, 1)
    acc: dict[str, list[tuple[float, float, int]]] = collections.defaultdict(list)
    for q in sorted(gold):
        others = gold - {q}
        for method, cand in cc_candidates(np, q, pool, adj, vectors).items():
            hit = len(cand & others)
            acc[method].append((hit / len(others), hit / len(cand) if cand else 0.0, len(cand)))
    rows = []
    for method, vals in acc.items():
        n = len(vals)
        prec = sum(v[1] for v in vals) / n
        rows.append(
            {
                "instance_id": task["instance_id"],
                "repo": task["repo"],
                "method": method,
                "n_gold": len(gold),
                "n_pool": len(pool),
                "queries": n,
                "recall": round(sum(v[0] for v in vals) / n, 4),
                "precision": round(prec, 4),
                "set_size": round(sum(v[2] for v in vals) / n, 1),
                "base_rate": round(base_rate, 5),
                "lift": round(prec / base_rate, 1) if base_rate else "",
            }
        )
    return rows


def cc_summary(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in rows:
        groups[(r["repo"], r["method"])].append(r)
        groups[("all repos", r["method"])].append(r)
    out = []
    for (repo, method), rs in sorted(groups.items()):
        n = len(rs)
        lifts = sorted(r["lift"] for r in rs if r["lift"] != "")
        out.append(
            {
                "repo": repo,
                "method": method,
                "tasks": n,
                "recall": round(sum(r["recall"] for r in rs) / n, 4),
                "precision": round(sum(r["precision"] for r in rs) / n, 4),
                "mean_set_size": round(sum(r["set_size"] for r in rs) / n, 1),
                "median_lift": lifts[len(lifts) // 2] if lifts else "",
            }
        )
    return out


def cc_run(data: Path, gold_csv: Path, out: Path) -> dict:
    import numpy as np

    out.mkdir(parents=True, exist_ok=True)
    gold = ll_gold(gold_csv)
    tasks = [
        json.loads(x)
        for x in (data / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    rows: list[dict] = []
    skipped: collections.Counter = collections.Counter()
    for t in tasks:
        g = gold.get(t["instance_id"], set())
        if len(g) < 2:
            skipped["fewer_than_2_gold_nodes"] += 1
            continue
        if len(g) > CC_MAX_GOLD:
            skipped[f"more_than_{CC_MAX_GOLD}_gold_nodes"] += 1
            continue
        stem = f"{t['instance_id'].rsplit('_', 1)[0]}_{t['base_commit']}"
        graph = load_graph(data / "graphs" / f"{stem}.json")
        if not graph:
            skipped["no_graph"] += 1
            continue
        got = cc_task_rows(
            np, t, graph, ll_load_vectors(np, data / "embeddings" / f"{stem}.npz"), g
        )
        if not got:
            skipped["fewer_than_2_library_gold_nodes"] += 1
        rows += got
    summary = cc_summary(rows)
    for name, data_rows in (("cochange_tasks.csv", rows), ("cochange_summary.csv", summary)):
        if data_rows:
            import csv

            with open(out / name, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(data_rows[0]))
                w.writeheader()
                w.writerows(data_rows)
    report = {
        "tasks_scored": len({r["instance_id"] for r in rows}),
        "skipped": dict(skipped),
        "max_gold": CC_MAX_GOLD,
        "summary": summary,
    }
    (out / "cochange_report.json").write_text(json.dumps(report, separators=(",", ":")))
    return report


def cc_main() -> int:
    """Kernel entry: re-derive the gold nodes with gold_map, then score co-change."""
    gm_run(DATA, OUTD / "map")  # noqa: F821
    report = cc_run(DATA, OUTD / "map" / "gold_nodes.csv", OUTD)  # noqa: F821
    (OUTD / "report.json").write_text(json.dumps(report, separators=(",", ":")))  # noqa: F821
    print(json.dumps(report["summary"], indent=1))
    return 0


def cc_cli(argv: list[str]) -> int:
    print(json.dumps(cc_run(Path(argv[1]), Path(argv[2]), Path(argv[3]))["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(cc_cli(sys.argv))
