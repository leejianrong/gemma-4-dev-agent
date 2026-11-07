"""Analyse the competition's tasks, code graphs and embeddings on CPU. Stdlib only.

Answers, for the paper ideas in docs/PLAN.md:
  - what the graph/embedding files contain (node keys, edge types, vector shape),
  - whether a gold patch can be mapped onto graph nodes (idea 1),
  - whether multi-node patches exist and are graph-adjacent (idea 2),
  - cheap leakage signals: does the issue name the edited symbol (idea 3).

Usage: explore.py DATA_DIR OUT_DIR
  DATA_DIR/tasks.jsonl, DATA_DIR/graphs/*.json, DATA_DIR/embeddings/*.npz
Writes OUT_DIR/results.json (per task) and OUT_DIR/report.json (compact, for logs).
Missing inputs are reported, never fatal, so a partial download still yields a report.
"""

from __future__ import annotations

import ast
import collections
import json
import re
import statistics
import sys
import zipfile
from pathlib import Path

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@\s*(.*)$")
DEF_RE = re.compile(r"(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")


def parse_patch(patch: str) -> list[dict]:
    """Split a unified diff into files and hunks (removed/added/context lines)."""
    files: list[dict] = []
    cur = None
    hunk = None
    old_path = None
    for line in patch.splitlines():
        if line.startswith("diff --git"):
            cur, hunk, old_path = None, None, None
        elif line.startswith("--- ") and hunk is None:
            old_path = line[4:].strip()
        elif line.startswith("+++ ") and hunk is None:
            new_path = line[4:].strip()
            path = old_path if new_path == "/dev/null" else new_path
            path = re.sub(r"^[ab]/", "", path or "")
            cur = {"path": path, "hunks": []}
            files.append(cur)
        elif cur is not None and (m := HUNK_RE.match(line)):
            hunk = {"ctx": m.group(1), "removed": [], "added": [], "context": []}
            cur["hunks"].append(hunk)
        elif hunk is not None:
            if line.startswith("-"):
                hunk["removed"].append(line[1:])
            elif line.startswith("+"):
                hunk["added"].append(line[1:])
            elif line.startswith(" "):
                hunk["context"].append(line[1:])
    return files


def module_candidates(path: str) -> list[str]:
    """fastapi/routing.py -> ['fastapi.routing', 'routing']; src/requests/models.py likewise."""
    p = Path(path)
    if p.suffix != ".py":
        return []
    parts = list(p.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return [".".join(parts[i:]) for i in range(len(parts)) if parts[i:]]


def _norm(lines: list[str]) -> set[str]:
    return {s for s in (x.strip() for x in lines) if len(s) > 3 and not s.startswith("#")}


def map_hunk(hunk: dict, nodes: list[dict], modules: list[str]) -> list[str]:
    """Graph nodes a hunk edits. Greedy cover of the removed lines: take the node matching the
    most remaining lines (ties to the smallest node), drop those lines, repeat. Later picks need a
    line of 8+ characters so generic one-liners ("return value") do not invent nodes."""
    pool = [n for n in nodes if any(n["id"].startswith(m + ".") for m in modules)]
    if not pool:
        return []
    texts = {n["id"]: _norm((n.get("text") or "").splitlines()) for n in pool}
    size = {n["id"]: len(n.get("text") or "") for n in pool}
    remaining = _norm(hunk["removed"])
    picked: list[str] = []
    while remaining:
        scored = [(-len(remaining & texts[i]), size[i], i) for i in texts if remaining & texts[i]]
        if not scored:
            break
        _, _, best = min(scored)
        covered = remaining & texts[best]
        if picked and not any(len(x) >= 8 for x in covered):
            break
        picked.append(best)
        remaining -= covered
    if picked:
        return picked
    m = DEF_RE.search(hunk["ctx"] or "")
    if m:
        cands = [n for n in pool if n["id"].endswith("." + m.group(1))]
        if cands:
            return [min(cands, key=lambda n: len(n.get("text") or ""))["id"]]
    ctx = _norm(hunk["context"])
    for n in sorted(pool, key=lambda n: size[n["id"]]):
        if ctx and len(ctx & texts[n["id"]]) >= 2:
            return [n["id"]]
    return []


def load_graph(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def adjacency(edges: list[dict]) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = collections.defaultdict(set)
    for e in edges:
        adj[e["source"]].add(e["target"])
        adj[e["target"]].add(e["source"])
    return adj


def hops(adj: dict[str, set[str]], a: str, b: str, limit: int = 2) -> int | None:
    seen, frontier = {a}, {a}
    for d in range(1, limit + 1):
        frontier = {y for x in frontier for y in adj.get(x, ())} - seen
        if b in frontier:
            return d
        seen |= frontier
    return None


def npy_header(zf: zipfile.ZipFile, member: str) -> dict | None:
    """Read shape/dtype from a .npy inside an .npz without numpy."""
    with zf.open(member) as f:
        head = f.read(10)
        if head[:6] != b"\x93NUMPY":
            return None
        hlen = int.from_bytes(head[8:10], "little") if head[6] == 1 else None
        if hlen is None:
            return None
        return ast.literal_eval(f.read(hlen).decode("latin1").strip())


def embedding_info(path: Path) -> dict | None:
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.endswith(".npy")]
            hdr = npy_header(zf, names[0]) if names else None
            return {
                "arrays": len(names),
                "shape": hdr.get("shape") if hdr else None,
                "dtype": hdr.get("descr") if hdr else None,
            }
    except (OSError, zipfile.BadZipFile, ValueError, SyntaxError):
        return None


def analyse_task(task: dict, data: Path) -> dict:
    short = task["instance_id"].rsplit("_", 1)[0]
    stem = f"{short}_{task['base_commit']}"
    out = {"id": task["instance_id"], "repo": task["repo"], "graph": False, "emb": None}
    files = parse_patch(task.get("patch") or "")
    py = [f for f in files if f["path"].endswith(".py")]
    out.update(
        files=len(files),
        py_files=len(py),
        hunks=sum(len(f["hunks"]) for f in files),
        removed=sum(len(h["removed"]) for f in files for h in f["hunks"]),
        added=sum(len(h["added"]) for f in files for h in f["hunks"]),
        hints=bool((task.get("hints_text") or "").strip()),
    )
    g = load_graph(data / "graphs" / f"{stem}.json")
    out["emb"] = embedding_info(data / "embeddings" / f"{stem}.npz")
    if g is None:
        return out
    nodes = g.get("nodes", [])
    edges = g.get("edges", g.get("links", []))
    out.update(graph=True, nodes=len(nodes), edges=len(edges))
    if out["emb"]:
        out["emb"]["covers_nodes"] = out["emb"]["arrays"] / max(1, len(nodes))
    mapped, unmapped = [], 0
    for f in py:
        mods = module_candidates(f["path"])
        for h in f["hunks"]:
            ids = map_hunk(h, nodes, mods)
            mapped.extend(ids)
            unmapped += not ids
    mapped = sorted(set(mapped))
    out.update(mapped_nodes=mapped, unmapped_hunks=unmapped)
    text = (task.get("problem_statement") or "") + " " + (task.get("hints_text") or "")
    shorts = {m.rsplit(".", 1)[-1] for m in mapped}
    out["issue_names_symbol"] = any(s and re.search(rf"\b{re.escape(s)}\b", text) for s in shorts)
    if len(mapped) >= 2:
        adj = adjacency(edges)
        ds = [hops(adj, a, b) for i, a in enumerate(mapped) for b in mapped[i + 1 :]]
        out["pair_hops"] = [d for d in ds if d is not None]
        out["pairs"] = len(ds)
    return out


def summarise(rows: list[dict], schema: dict) -> dict:
    n = len(rows)
    withg = [r for r in rows if r["graph"]]
    multi = [r for r in withg if len(r.get("mapped_nodes", [])) >= 2]
    pairs = sum(r.get("pairs", 0) for r in multi)
    adj1 = sum(1 for r in multi for d in r.get("pair_hops", []) if d == 1)
    adj2 = sum(1 for r in multi for d in r.get("pair_hops", []) if d <= 2)
    sizes = [len(r.get("mapped_nodes", [])) for r in withg]
    return {
        "tasks": n,
        "with_graph": len(withg),
        "with_embeddings": sum(1 for r in rows if r["emb"]),
        "repos": dict(collections.Counter(r["repo"] for r in rows)),
        "graph_schema": schema,
        "tasks_with_mapped_node": sum(1 for r in withg if r.get("mapped_nodes")),
        "tasks_fully_mapped": sum(
            1 for r in withg if r.get("mapped_nodes") and not r["unmapped_hunks"]
        ),
        "median_edited_nodes": statistics.median(sizes) if sizes else None,
        "multi_node_tasks": len(multi),
        "multi_node_pairs": pairs,
        "pairs_1hop": adj1,
        "pairs_within_2hops": adj2,
        "issue_names_symbol": sum(1 for r in withg if r.get("issue_names_symbol")),
        "tasks_with_hints": sum(1 for r in rows if r["hints"]),
        "emb_shapes": dict(collections.Counter(str(r["emb"]["shape"]) for r in rows if r["emb"])),
        "emb_node_coverage_min": min(
            (r["emb"]["covers_nodes"] for r in rows if r["emb"] and "covers_nodes" in r["emb"]),
            default=None,
        ),
    }


def graph_schema(data: Path) -> dict:
    keys, etypes, ekeys, top = set(), collections.Counter(), set(), set()
    files = sorted((data / "graphs").glob("*.json"))
    for p in files:
        g = load_graph(p)
        if not g:
            continue
        top |= set(g)
        for nd in g.get("nodes", [])[:50]:
            keys |= set(nd)
        for e in g.get("edges", g.get("links", [])):
            etypes[e.get("type")] += 1
            ekeys |= set(e)
    return {
        "graph_files": len(files),
        "top_keys": sorted(top),
        "node_keys": sorted(keys),
        "edge_keys": sorted(ekeys),
        "edge_types": dict(etypes),
    }


def main(argv: list[str]) -> int:
    data, out = Path(argv[1]), Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    tasks_path = data / "tasks.jsonl"
    if not tasks_path.is_file():
        print("ERROR tasks.jsonl missing", file=sys.stderr)
        return 2
    tasks = [
        json.loads(line)
        for line in tasks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = []
    for i, t in enumerate(tasks, 1):
        try:
            rows.append(analyse_task(t, data))
        except Exception as e:  # one bad task must not lose the rest
            print(f"WARN task {t.get('instance_id')} failed: {type(e).__name__}: {e}")
            rows.append(
                {
                    "id": t.get("instance_id"),
                    "repo": t.get("repo", "?"),
                    "graph": False,
                    "emb": None,
                    "hints": False,
                    "error": str(e),
                }
            )
        if i % 20 == 0:
            print(f"explore {i}/{len(tasks)} tasks")
    report = summarise(rows, graph_schema(data))
    (out / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    print("explore done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
