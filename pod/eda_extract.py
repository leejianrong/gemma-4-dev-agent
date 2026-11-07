"""Emit small tables for exploratory data analysis from the competition data (Kaggle CPU kernel).

Stdlib only, except the embedding tables which need numpy (present on Kaggle; skipped if absent).
The 21 GiB of snapshots never leave Kaggle; only these small CSVs come back.

Outputs (OUT_DIR):
  tasks.csv           one row per task: issue/patch/test-patch features
  hunks.csv           one row per diff hunk: path, kind, sizes, number of text-mapped graph nodes
  graph_stats.csv     one row per graph: nodes, edges, degree summary, largest weak component
  node_degrees.csv.gz one row per node: stem, kind, in/out degree, text size
  edited_nodes.csv    text-mapped edited nodes with degree and percentile (approximate mapping)
  emb_nn.csv          embedding kNN agreement with call-graph neighbours/parents vs random
  emb_sample.csv.gz   a sample of raw vectors for local PCA / t-SNE
  report.json         row counts and byte sizes
Usage: eda_extract.py DATA_DIR OUT_DIR
"""

from __future__ import annotations

import collections
import csv
import gzip
import json
import random
import re
import sys
import zipfile
from pathlib import Path

if "parse_patch" not in globals():  # standalone; inside the kernel explore.py is inlined above
    from explore import DEF_RE, load_graph, map_hunk, module_candidates, parse_patch

EDA_NON_LIB = ("docs_src/", "docs/", "scripts/", "tests/", "test/", "examples/")
EDA_TEST_DEF = re.compile(r"^\+\s*(?:async\s+)?def\s+(test_\w+)")
EDA_FENCE = re.compile(r"```")
EDA_URL = re.compile(r"https?://\S+")
EDA_TRACE = re.compile(r"Traceback \(most recent call last\)")


def eda_is_library(path: str) -> bool:
    return path.endswith(".py") and not path.startswith(EDA_NON_LIB)


def eda_kind(node_id: str) -> str:
    return "class_like" if node_id.rsplit(".", 1)[-1][:1].isupper() else "function_like"


def eda_module2(node_id: str) -> str:
    return ".".join(node_id.split(".")[:2])


def eda_parent(node_id: str) -> str:
    return node_id.rsplit(".", 1)[0] if "." in node_id else ""


def eda_word_hit(words: set[str], text: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def eda_task_row(t: dict, snap_dir: Path) -> dict:
    ps = t.get("problem_statement") or ""
    hints = t.get("hints_text") or ""
    text = ps + "\n" + hints
    files = parse_patch(t.get("patch") or "")
    tfiles = parse_patch(t.get("test_patch") or "")
    names, stems = set(), set()
    for f in files:
        if f["path"].endswith(".py"):
            stems.add(Path(f["path"]).stem)
        for h in f["hunks"]:
            names |= {m.group(1) for m in DEF_RE.finditer(h["ctx"] or "")}
    names = {n for n in names if len(n) >= 4 and not n.startswith("__")}
    stems = {s for s in stems if len(s) >= 3 and s != "__init__"}
    hunks = [h for f in files for h in f["hunks"]]
    lib = [f for f in files if eda_is_library(f["path"])]
    snap = snap_dir / f"{t['instance_id']}.tgz"
    return {
        "instance_id": t["instance_id"],
        "repo": t["repo"],
        "base_commit": t["base_commit"],
        "created_at": t.get("created_at", ""),
        "problem_chars": len(ps),
        "problem_words": len(ps.split()),
        "problem_lines": ps.count("\n") + 1 if ps else 0,
        "code_blocks": len(EDA_FENCE.findall(ps)) // 2,
        "has_traceback": int(bool(EDA_TRACE.search(ps))),
        "urls": len(EDA_URL.findall(ps)),
        "hints_chars": len(hints),
        "patch_files": len(files),
        "patch_py_files": sum(1 for f in files if f["path"].endswith(".py")),
        "patch_lib_files": len(lib),
        "patch_hunks": len(hunks),
        "patch_removed": sum(len(h["removed"]) for h in hunks),
        "patch_added": sum(len(h["added"]) for h in hunks),
        "patch_new_files": sum(
            1
            for f in files
            if f["hunks"] and all(not h["removed"] and not h["context"] for h in f["hunks"])
        ),
        "test_files": len(tfiles),
        "test_lines_added": sum(len(h["added"]) for f in tfiles for h in f["hunks"]),
        "test_funcs_added": sum(
            1 for line in (t.get("test_patch") or "").splitlines() if EDA_TEST_DEF.match(line)
        ),
        "issue_mentions_hunk_symbol": int(eda_word_hit(names, text)),
        "issue_mentions_patch_module": int(eda_word_hit(stems, text)),
        "snapshot_mib": round(snap.stat().st_size / 2**20, 1) if snap.is_file() else "",
    }


def eda_hunk_rows(t: dict, nodes: list[dict] | None) -> tuple[list[dict], list[str]]:
    rows, mapped_all = [], []
    for f in parse_patch(t.get("patch") or ""):
        lib = eda_is_library(f["path"])
        mods = module_candidates(f["path"]) if lib else []
        for h in f["hunks"]:
            ids = map_hunk(h, nodes, mods) if (nodes and lib) else []
            mapped_all += ids
            rows.append(
                {
                    "instance_id": t["instance_id"],
                    "repo": t["repo"],
                    "path": f["path"],
                    "is_python": int(f["path"].endswith(".py")),
                    "is_library": int(lib),
                    "ctx": (h["ctx"] or "")[:60].replace("\n", " "),
                    "n_removed": len(h["removed"]),
                    "n_added": len(h["added"]),
                    "n_context": len(h["context"]),
                    "is_new_file_hunk": int(not h["removed"] and not h["context"]),
                    "n_mapped_nodes": len(ids),
                }
            )
    return rows, sorted(set(mapped_all))


def eda_degrees(nodes: list[dict], edges: list[dict]) -> tuple[dict, dict, dict]:
    indeg, outdeg = collections.Counter(), collections.Counter()
    adj: dict[str, set[str]] = collections.defaultdict(set)
    for e in edges:
        s, tg = e["source"], e["target"]
        outdeg[s] += 1
        indeg[tg] += 1
        if s != tg:
            adj[s].add(tg)
            adj[tg].add(s)
    return indeg, outdeg, adj


def eda_largest_component(ids: list[str], adj: dict[str, set[str]]) -> int:
    seen, best = set(), 0
    for start in ids:
        if start in seen:
            continue
        stack, size = [start], 0
        seen.add(start)
        while stack:
            cur = stack.pop()
            size += 1
            for nb in adj.get(cur, ()):
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        best = max(best, size)
    return best


def eda_embeddings(
    np,
    path: Path,
    nodes: list[dict],
    adj: dict,
    edited: set[str],
    rng: random.Random,
    k: int = 10,
    n_query: int = 200,
    n_sample: int = 16,
):
    """kNN agreement rows and a small vector sample for one graph; ([], []) when unusable."""
    try:
        z = np.load(path)
        keys = set(z.files)
        ids = [n["id"] for n in nodes if n["id"] in keys]
        if len(ids) < 4:
            return [], [], []
        mat = np.stack([z[i] for i in ids]).astype(np.float32)
    except (OSError, ValueError, zipfile.BadZipFile):
        return [], [], []
    norms = np.linalg.norm(mat, axis=1)
    unit = mat / np.maximum(norms[:, None], 1e-9)
    n = len(ids)
    k_eff = min(k, n - 1)
    parents = collections.Counter(eda_parent(i) for i in ids)
    pos = {i: j for j, i in enumerate(ids)}
    pick = [pos[i] for i in sorted(edited) if i in pos]
    rest = [j for j in range(n) if j not in set(pick)]
    rng.shuffle(rest)
    queries = (pick + rest)[:n_query]
    sims = unit[queries] @ unit.T
    for r, q in enumerate(queries):
        sims[r, q] = -np.inf
    top = np.argpartition(-sims, k_eff - 1, axis=1)[:, :k_eff]
    rows = []
    for r, q in enumerate(queries):
        order = top[r][np.argsort(-sims[r, top[r]])]
        qid = ids[q]
        nb_ids = [ids[j] for j in order]
        deg = len(adj.get(qid, ()))
        psize = parents[eda_parent(qid)]
        rows.append(
            {
                "n_nodes": n,
                "k": k_eff,
                "kind": eda_kind(qid),
                "is_edited": int(qid in edited),
                "degree": deg,
                "hits_1hop": sum(1 for x in nb_ids if x in adj.get(qid, ())),
                "expected_1hop": round(k_eff * deg / (n - 1), 4),
                "parent_size": psize,
                "hits_same_parent": sum(1 for x in nb_ids if eda_parent(x) == eda_parent(qid)),
                "expected_same_parent": round(k_eff * (psize - 1) / (n - 1), 4),
                "top1_cos": round(float(sims[r, order[0]]), 4),
                "norm": round(float(norms[q]), 4),
            }
        )
    chosen = rng.sample(range(n), min(n_sample, n))
    sample = [(ids[j], [f"{x:.4f}" for x in mat[j]]) for j in chosen]
    return rows, sample, ids


def eda_write(path: Path, rows: list[dict]) -> int:
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def eda_run(data: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    try:
        import numpy as np
    except ImportError:
        np = None
    tasks = [
        json.loads(x)
        for x in (data / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    by_stem: dict[str, list[dict]] = collections.defaultdict(list)
    for t in tasks:
        by_stem[f"{t['instance_id'].rsplit('_', 1)[0]}_{t['base_commit']}"].append(t)
    task_rows = [eda_task_row(t, data / "snapshots") for t in tasks]
    hunk_rows, graph_rows, edited_rows, nn_rows = [], [], [], []
    emb_sample: list[list] = []
    n_node_rows = 0
    with gzip.open(out / "node_degrees.csv.gz", "wt", newline="", encoding="utf-8") as gz:
        nd = csv.writer(gz)
        nd.writerow(["stem", "kind", "in_degree", "out_degree", "text_chars"])
        for si, (stem, group) in enumerate(sorted(by_stem.items())):
            g = load_graph(data / "graphs" / f"{stem}.json")
            if not g:
                for t in group:
                    hunk_rows += eda_hunk_rows(t, None)[0]
                continue
            nodes = g["nodes"]
            edges = g.get("edges", g.get("links", []))
            indeg, outdeg, adj = eda_degrees(nodes, edges)
            ids = [n["id"] for n in nodes]
            tot = sorted(indeg[i] + outdeg[i] for i in ids)
            repo = group[0]["repo"]
            graph_rows.append(
                {
                    "stem": stem,
                    "repo": repo,
                    "tasks": len(group),
                    "nodes": len(nodes),
                    "edges": len(edges),
                    "class_like": sum(1 for i in ids if eda_kind(i) == "class_like"),
                    "isolated": sum(1 for i in ids if not adj.get(i)),
                    "max_degree": tot[-1] if tot else 0,
                    "mean_degree": round(sum(tot) / len(tot), 3) if tot else 0,
                    "largest_component": eda_largest_component(ids, adj),
                }
            )
            for n in nodes:
                nd.writerow(
                    [
                        stem,
                        eda_kind(n["id"]),
                        indeg[n["id"]],
                        outdeg[n["id"]],
                        len(n.get("text") or ""),
                    ]
                )
                n_node_rows += 1
            edited_here: set[str] = set()
            for t in group:
                rows, mapped = eda_hunk_rows(t, nodes)
                hunk_rows += rows
                for nid in mapped:
                    d = indeg[nid] + outdeg[nid]
                    pct = sum(1 for x in tot if x <= d) / len(tot)
                    edited_rows.append(
                        {
                            "instance_id": t["instance_id"],
                            "repo": repo,
                            "kind": eda_kind(nid),
                            "in_degree": indeg[nid],
                            "out_degree": outdeg[nid],
                            "degree_percentile": round(pct, 4),
                            "n_nodes": len(nodes),
                            "node_id": nid,
                        }
                    )
                edited_here |= set(mapped)
            if np is not None:
                rng = random.Random(stem)
                rows, sample, _ = eda_embeddings(
                    np, data / "embeddings" / f"{stem}.npz", nodes, adj, edited_here, rng
                )
                for r in rows:
                    nn_rows.append({"stem": stem, "repo": repo, **r})
                for nid, vec in sample:
                    emb_sample.append([stem, repo, nid, eda_kind(nid), eda_module2(nid), *vec])
            if (si + 1) % 20 == 0:
                print(f"eda {si + 1}/{len(by_stem)} graphs", flush=True)
    report = {
        "tasks.csv": eda_write(out / "tasks.csv", task_rows),
        "hunks.csv": eda_write(out / "hunks.csv", hunk_rows),
        "graph_stats.csv": eda_write(out / "graph_stats.csv", graph_rows),
        "node_degrees.csv.gz": n_node_rows,
        "edited_nodes.csv": eda_write(out / "edited_nodes.csv", edited_rows),
        "emb_nn.csv": eda_write(out / "emb_nn.csv", nn_rows),
    }
    with gzip.open(out / "emb_sample.csv.gz", "wt", newline="", encoding="utf-8") as gz:
        w = csv.writer(gz)
        w.writerow(["stem", "repo", "node_id", "kind", "module2", *[f"v{i}" for i in range(256)]])
        w.writerows(emb_sample)
    report["emb_sample.csv.gz"] = len(emb_sample)
    report["numpy_available"] = np is not None
    report["bytes"] = {
        p.name: p.stat().st_size for p in sorted(out.iterdir()) if p.name != "report.json"
    }
    total = sum(report["bytes"].values())
    report["total_mib"] = round(total / 2**20, 2)
    if total > 25 * 2**20:
        print(f"WARN output is {total / 2**20:.1f} MiB, over the 25 MiB target")
    (out / "report.json").write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    return report


def eda_main() -> int:
    """Kernel entry: DATA and OUTD are defined by the kernel wrapper appended after this."""
    print(json.dumps(eda_run(DATA, OUTD), indent=1))  # noqa: F821
    return 0


def eda_cli(argv: list[str]) -> int:
    print(json.dumps(eda_run(Path(argv[1]), Path(argv[2])), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(eda_cli(sys.argv))
