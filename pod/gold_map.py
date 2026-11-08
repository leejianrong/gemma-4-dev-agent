"""Map gold patches onto code-graph nodes by old-file line numbers. Stdlib only; runs on Kaggle.

Text matching of removed lines was about 70% precise. This reads each patched file as it was at
`base_commit` (from the task's snapshot), takes the line ranges of every function and class with
`ast`, and walks each hunk by its OLD line numbers, crediting every changed line to the innermost
enclosing def or class (or to module level). The dotted name is then looked up in the graph.

Independent checks on the mapping itself:
  * `consistent`: the hunk's context and removed lines equal the old file at the computed lines
    (proves we read the right file version and counted lines correctly);
  * `text_agree`: removed lines also appear in the mapped node's graph text.

Outputs (OUT_DIR): gold_nodes.csv, gold_hunks.csv, mapping_samples.md, report.json.
Usage: gold_map.py DATA_DIR OUT_DIR
"""

from __future__ import annotations

import ast
import collections
import csv
import json
import random
import re
import statistics
import sys
import tarfile
from pathlib import Path

if "parse_patch" not in globals():  # standalone; inside the kernel explore.py is inlined above
    from explore import load_graph, map_hunk, module_candidates, parse_patch

GM_NON_LIB = ("docs_src/", "docs/", "scripts/", "tests/", "test/", "examples/")
GM_MODULE = "<module>"


def gm_is_library(path: str) -> bool:
    return path.endswith(".py") and not path.startswith(GM_NON_LIB)


def gm_kind(node_id: str) -> str:
    return "class_like" if node_id.rsplit(".", 1)[-1][:1].isupper() else "function_like"


GM_COMMENT = re.compile(r"\s+#.*$")


def gm_clean(line: str) -> str | None:
    """A line as the graph would hold it: no trailing comment, no decorator; None if trivial."""
    s = GM_COMMENT.sub("", line.strip())
    return None if len(s) <= 3 or s.startswith(("#", "@")) else s


def gm_clean_set(lines: list[str]) -> set[str]:
    return {c for c in (gm_clean(x) for x in lines) if c}


def gm_header_ok(node_id: str, text: str) -> bool:
    """The node's first non-decorator line names the function or class we mapped to."""
    leaf = node_id.rsplit(".", 1)[-1]
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("@"):
            return leaf in line
    return False


def gm_read_old_files(tgz: Path, paths: set[str]) -> tuple[dict[str, str], list[str]]:
    """Return {path: text} for the wanted paths from a .tgz snapshot, plus a few member names."""
    found: dict[str, str] = {}
    sample: list[str] = []
    want = set(paths)
    try:
        with tarfile.open(tgz, "r:gz") as tf:
            for m in tf:
                if len(sample) < 3:
                    sample.append(m.name)
                if not m.isfile() or not want:
                    if not want:
                        break
                    continue
                name = m.name[2:] if m.name.startswith("./") else m.name
                for p in want:
                    if name == p or name.endswith("/" + p):
                        fh = tf.extractfile(m)
                        if fh is not None:
                            found[p] = fh.read().decode("utf-8", "replace")
                            want = want - {p}
                        break
    except (OSError, tarfile.TarError, EOFError):
        pass
    return found, sample


def gm_defs(source: str) -> list[tuple[int, int, int, str]] | None:
    """(start, end, col, qualname) of every def and class, nested ones too; None if unparsable."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    out: list[tuple[int, int, int, str]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = f"{prefix}.{ch.name}" if prefix else ch.name
                start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                out.append((start, ch.end_lineno or ch.lineno, ch.col_offset, q))
                visit(ch, q)
            else:
                visit(ch, prefix)

    visit(tree, "")
    return out


def gm_async_names(source: str) -> set[str]:
    """Qualified names of every `async def` (methods and nested ones included)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return set()
    out: set[str] = set()

    def visit(node: ast.AST, prefix: str) -> None:
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = f"{prefix}.{ch.name}" if prefix else ch.name
                if isinstance(ch, ast.AsyncFunctionDef):
                    out.add(q)
                visit(ch, q)
            else:
                visit(ch, prefix)

    visit(tree, "")
    return out


def gm_def_stats(source: str, defs, module: str | None, ids: set[str]) -> dict[str, int]:
    """Top-level functions and methods of a file, and how many have a graph node (sync vs async)."""
    asyncs = gm_async_names(source)
    out = {"async_defs": 0, "async_with_node": 0, "sync_defs": 0, "sync_with_node": 0}
    for _, _, _, q in defs:
        parts = q.split(".")
        if len(parts) > 2 or (len(parts) == 2 and not parts[0][:1].isupper()):
            continue  # nested functions are not expected in the graph
        if gm_kind(q) == "class_like":
            continue
        key = "async" if q in asyncs else "sync"
        out[f"{key}_defs"] += 1
        out[f"{key}_with_node"] += int(bool(module) and f"{module}.{q}" in ids)
    return out


def gm_innermost(defs, line: int, indent: int | None = None):
    """Deepest def containing `line`; with `indent`, only defs whose own column is left of it."""
    best = None
    for d in defs:
        s, e, col, _ = d
        if s <= line <= e and (indent is None or col < indent) and (best is None or s >= best[0]):
            best = d
    return best


def gm_attribute(h: dict, defs) -> dict[str, dict[str, int]]:
    """Credit each changed line of a hunk to a qualname (or GM_MODULE): {q: {'-': n, '+': n}}."""
    credit: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"-": 0, "+": 0})
    old = h["old_start"]
    removed_ref: tuple[int, str] | None = (
        None  # shallowest removed line of this run: (indent, node)
    )
    stack: list[tuple[int, str]] = []  # added lines of this run: (indent, node they were given)
    for kind, text in h["lines"]:
        if kind == " ":
            old += 1
            removed_ref, stack = None, []
        elif kind == "-":
            d = gm_innermost(defs, old)
            q = d[3] if d else GM_MODULE
            credit[q]["-"] += 1
            if text.strip():
                ind = len(text) - len(text.lstrip())
                if removed_ref is None or ind < removed_ref[0]:
                    removed_ref = (ind, q)
            stack = []
            old += 1
        else:  # an insertion between old line (old - 1) and old
            if not text.strip():
                continue  # blank lines take the side of their neighbours
            ind = len(text) - len(text.lstrip())
            while stack and stack[-1][0] >= ind:
                stack.pop()
            if stack:  # the body of a block this insertion opened
                q = stack[-1][1]
            elif removed_ref is not None and ind >= removed_ref[0]:  # replaces what was removed
                q = removed_ref[1]
            else:
                d = gm_innermost(defs, old - 1, ind) or gm_innermost(defs, old, ind)
                q = d[3] if d else GM_MODULE
            credit[q]["+"] += 1
            stack.append((ind, q))
    return credit


def gm_removed_texts(h: dict, defs) -> dict[str, list[str]]:
    """The removed lines credited to each qualname (for checking against the node's text)."""
    out: dict[str, list[str]] = collections.defaultdict(list)
    old = h["old_start"]
    for kind, text in h["lines"]:
        if kind == "+":
            continue
        if kind == "-":
            d = gm_innermost(defs, old)
            out[d[3] if d else GM_MODULE].append(text)
        old += 1
    return out


def gm_consistent(h: dict, old_lines: list[str]) -> bool:
    """Context and removed lines must equal the old file at the lines the hunk says."""
    old = h["old_start"]
    for kind, text in h["lines"]:
        if kind == "+":
            continue
        if old < 1 or old > len(old_lines) or old_lines[old - 1].rstrip() != text.rstrip():
            return False
        old += 1
    return True


def gm_pick_module(cands: list[str], ids: set[str], qualnames: set[str]) -> str | None:
    for c in cands:
        if any(f"{c}.{q}" in ids for q in qualnames if q != GM_MODULE):
            return c
    for c in cands:
        if any(i.startswith(c + ".") for i in ids):
            return c
    return None


def gm_resolve(module: str, qual: str, ids: set[str]) -> tuple[str | None, bool]:
    """Graph id for a qualname, walking up to the parent when a nested def has no node."""
    q, fell_back = qual, False
    while q:
        nid = f"{module}.{q}"
        if nid in ids:
            return nid, fell_back
        q = q.rpartition(".")[0]
        fell_back = True
    return None, fell_back


def gm_hunk_row(task, path, idx, h, status, nodes, **extra) -> dict:
    return {
        "instance_id": task["instance_id"],
        "repo": task["repo"],
        "path": path,
        "hunk": idx,
        "old_start": h["old_start"],
        "old_count": h["old_count"],
        "status": status,
        "nodes": ";".join(nodes),
        "n_removed": len(h["removed"]),
        "n_added": len(h["added"]),
        **extra,
    }


def gm_task(task: dict, data: Path, graph: dict) -> tuple[list[dict], list[dict], dict]:
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    ids = set(nodes_by_id)
    files = parse_patch(task.get("patch") or "")
    lib = [f for f in files if gm_is_library(f["path"])]
    old_files, tar_sample = gm_read_old_files(
        data / "snapshots" / f"{task['instance_id']}.tgz", {f["path"] for f in lib}
    )
    hunk_rows: list[dict] = []
    agg: dict[str, dict] = {}
    def_stats = collections.Counter()
    for path, src in old_files.items():
        d = gm_defs(src)
        if d:
            module = gm_pick_module(module_candidates(path), ids, {q for *_, q in d})
            def_stats.update(gm_def_stats(src, d, module, ids))
    for f in files:
        for i, h in enumerate(f["hunks"]):
            if not gm_is_library(f["path"]):
                hunk_rows.append(gm_hunk_row(task, f["path"], i, h, "non_library", []))
                continue
            if h["old_count"] == 0 and not h["context"] and not h["removed"]:
                hunk_rows.append(gm_hunk_row(task, f["path"], i, h, "new_file", []))
                continue
            src = old_files.get(f["path"])
            if src is None:
                hunk_rows.append(gm_hunk_row(task, f["path"], i, h, "file_not_in_snapshot", []))
                continue
            defs = gm_defs(src)
            if defs is None:
                hunk_rows.append(gm_hunk_row(task, f["path"], i, h, "ast_failed", []))
                continue
            consistent = gm_consistent(h, src.splitlines())
            credit = gm_attribute(h, defs)
            removed_by_q = gm_removed_texts(h, defs)
            quals = {q for q in credit if q != GM_MODULE}
            module = gm_pick_module(module_candidates(f["path"]), ids, quals)
            def_lines = {q: (s, e) for s, e, _, q in defs}
            resolved: dict[str, dict] = {}
            unresolved, fell = [], False
            for q, c in credit.items():
                if q == GM_MODULE:
                    continue
                nid, fb = gm_resolve(module, q, ids) if module else (None, False)
                if nid is None:
                    unresolved.append(q)
                    continue
                fell = fell or fb
                r = resolved.setdefault(nid, {"-": 0, "+": 0, "rm": []})
                r["-"] += c["-"]
                r["+"] += c["+"]
                r["rm"] += removed_by_q.get(q, [])
            mapped = list(resolved)
            for nid, c in resolved.items():
                a = agg.setdefault(
                    nid,
                    {
                        "removed": 0,
                        "added": 0,
                        "hunks": 0,
                        "agree": [],
                        "path": f["path"],
                        "src_lines": None,
                        "text_lines": 0,
                        "first_missing": "",
                        "header_ok": 0,
                    },
                )
                a["removed"] += c["-"]
                a["added"] += c["+"]
                a["hunks"] += 1
                span = def_lines.get(nid[len(module) + 1 :])
                a["src_lines"] = (span[1] - span[0] + 1) if span else None
                text = nodes_by_id[nid].get("text") or ""
                a["text_lines"] = len(text.splitlines())
                a["header_ok"] = int(gm_header_ok(nid, text))
                # Class text in the graph keeps only the header, so compare function nodes only.
                removed = gm_clean_set(c["rm"]) if gm_kind(nid) == "function_like" else set()
                if removed:
                    have = gm_clean_set(text.splitlines())
                    a["agree"].append(len(removed & have) / len(removed))
                    missing = sorted(removed - have)
                    if missing and not a["first_missing"]:
                        a["first_missing"] = missing[0][:90]
            module_lines = credit.get(GM_MODULE, {"-": 0, "+": 0})
            status = "mapped" if mapped else ("module_level" if credit else "no_changed_code")
            if not mapped and quals:
                status = "node_missing"
            text_nodes = map_hunk(h, graph["nodes"], module_candidates(f["path"]))
            hunk_rows.append(
                gm_hunk_row(
                    task,
                    f["path"],
                    i,
                    h,
                    status,
                    mapped,
                    consistent=int(consistent),
                    module_lines=module_lines["-"] + module_lines["+"],
                    parent_fallback=int(fell),
                    unresolved=";".join(unresolved),
                    text_nodes=";".join(text_nodes),
                    text_in_line=int(bool(text_nodes) and set(text_nodes) <= set(mapped)),
                )
            )
    indeg: collections.Counter = collections.Counter(e["target"] for e in graph.get("edges", []))
    outdeg: collections.Counter = collections.Counter(e["source"] for e in graph.get("edges", []))
    node_rows = []
    for nid, a in agg.items():
        node_rows.append(
            {
                "instance_id": task["instance_id"],
                "repo": task["repo"],
                "node_id": nid,
                "kind": gm_kind(nid),
                "path": a["path"],
                "removed_lines": a["removed"],
                "added_lines": a["added"],
                "hunks": a["hunks"],
                "text_agree": round(statistics.mean(a["agree"]), 3) if a["agree"] else "",
                "src_lines": a["src_lines"] if a["src_lines"] is not None else "",
                "text_lines": a["text_lines"],
                "first_missing": a["first_missing"],
                "header_ok": a["header_ok"],
                "in_degree": indeg.get(nid, 0),
                "out_degree": outdeg.get(nid, 0),
                "graph_nodes": len(graph["nodes"]),
            }
        )
    return hunk_rows, node_rows, {"tar_sample": tar_sample, "def_stats": def_stats}


def gm_disagreements(node_rows: list[dict], seed: int = 5, n: int = 20) -> list[str]:
    """Nodes whose graph text lacks some removed lines: is the graph text the raw source?"""
    bad = [r for r in node_rows if r["text_agree"] != "" and float(r["text_agree"]) < 0.999]
    rng = random.Random(seed)
    out = ["## Nodes whose graph text does not contain all removed lines", ""]
    for r in rng.sample(bad, min(n, len(bad))):
        out.append(
            f"- {r['instance_id']} {r['node_id']} agree={r['text_agree']} "
            f"source_lines={r['src_lines']} graph_text_lines={r['text_lines']} "
            f"first_missing={r['first_missing']!r}"
        )
    return out + [""]


def gm_samples(
    hunk_rows: list[dict],
    tasks: dict[str, dict],
    node_rows: list[dict] | None = None,
    seed: int = 11,
) -> str:
    """A seeded sample of mapped hunks with the evidence needed to judge them by eye."""
    rng = random.Random(seed)
    mapped = [r for r in hunk_rows if r["status"] == "mapped"]
    other = [r for r in hunk_rows if r["status"] not in ("mapped", "non_library")]
    pick = rng.sample(mapped, min(30, len(mapped))) + rng.sample(other, min(10, len(other)))
    lines = ["# Mapping samples", ""]
    for r in pick:
        t = tasks[r["instance_id"]]
        hunk = None
        for f in parse_patch(t.get("patch") or ""):
            if f["path"] == r["path"] and r["hunk"] < len(f["hunks"]):
                hunk = f["hunks"][r["hunk"]]
        lines.append(f"### {r['instance_id']} {r['path']} hunk {r['hunk']} status={r['status']}")
        text_nodes = r.get("text_nodes") or "-"
        lines.append(
            f"old_start={r['old_start']} nodes={r['nodes'] or '-'} text_nodes={text_nodes}"
        )
        if hunk:
            lines.append(f"header ctx: {hunk['ctx'][:70]!r}")
            for kind, text in [x for x in hunk["lines"] if x[0] != " "][:5]:
                lines.append(f"  {kind} {text.strip()[:100]}")
        lines.append("")
    if node_rows:
        lines += gm_disagreements(node_rows)
    return "\n".join(lines)


def gm_summary(hunk_rows, node_rows, tasks, extra) -> dict:
    by_task = collections.defaultdict(list)
    for r in hunk_rows:
        by_task[r["instance_id"]].append(r)
    lib_status = collections.Counter(r["status"] for r in hunk_rows if r["status"] != "non_library")
    mapped = [r for r in hunk_rows if r["status"] == "mapped"]
    checked = [r for r in hunk_rows if "consistent" in r]
    nodes_per_task = collections.Counter(n["instance_id"] for n in node_rows)
    agree = [float(n["text_agree"]) for n in node_rows if n["text_agree"] != ""]
    both = [r for r in mapped if r.get("text_nodes")]
    return {
        "tasks": len(tasks),
        "hunks": len(hunk_rows),
        "library_hunk_status": dict(lib_status),
        "hunks_consistent_with_old_file": sum(r["consistent"] for r in checked),
        "hunks_checked_for_consistency": len(checked),
        "tasks_with_a_mapped_node": len(nodes_per_task),
        "tasks_where_every_library_hunk_is_mapped": sum(
            1
            for rows in by_task.values()
            if (lib := [r for r in rows if r["status"] != "non_library"])
            and all(r["status"] == "mapped" for r in lib)
        ),
        "median_nodes_per_task": statistics.median(nodes_per_task.values())
        if nodes_per_task
        else 0,
        "tasks_with_2plus_nodes": sum(1 for v in nodes_per_task.values() if v >= 2),
        "max_nodes_in_a_task": max(nodes_per_task.values(), default=0),
        "nodes": len(node_rows),
        "function_nodes_with_removed_lines": len(agree),
        "function_nodes_text_agree_all_lines": sum(1 for a in agree if a >= 0.999),
        "function_nodes_text_agree_half": sum(1 for a in agree if a >= 0.5),
        "nodes_header_names_the_mapped_node": sum(int(n["header_ok"]) for n in node_rows),
        "nodes_graph_text_lines_equal_source": sum(
            1
            for n in node_rows
            if n["src_lines"] != "" and int(n["src_lines"]) == int(n["text_lines"])
        ),
        "nodes_graph_text_shorter_than_source": sum(
            1
            for n in node_rows
            if n["src_lines"] != "" and int(n["text_lines"]) < int(n["src_lines"])
        ),
        "nodes_graph_text_longer_than_source": sum(
            1
            for n in node_rows
            if n["src_lines"] != "" and int(n["text_lines"]) > int(n["src_lines"])
        ),
        "hunks_parent_fallback": sum(r.get("parent_fallback", 0) for r in mapped),
        "text_method_hunks_compared": len(both),
        "text_method_subset_of_line_method": sum(r["text_in_line"] for r in both),
        "kinds": dict(collections.Counter(n["kind"] for n in node_rows)),
        **extra,
    }


def gm_write(path: Path, rows: list[dict]) -> int:
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def gm_run(data: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tasks = [
        json.loads(x)
        for x in (data / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    by_id = {t["instance_id"]: t for t in tasks}
    hunk_rows, node_rows = [], []
    tar_samples: list[list[str]] = []
    defs_total: collections.Counter = collections.Counter()
    for i, t in enumerate(tasks, 1):
        stem = f"{t['instance_id'].rsplit('_', 1)[0]}_{t['base_commit']}"
        g = load_graph(data / "graphs" / f"{stem}.json")
        if not g:
            print(f"WARN {t['instance_id']}: no graph")
            continue
        try:
            h, n, extra = gm_task(t, data, g)
        except Exception as e:  # one bad task must not lose the rest
            print(f"WARN {t['instance_id']} failed: {type(e).__name__}: {e}")
            continue
        hunk_rows += h
        node_rows += n
        if len(tar_samples) < 3:
            tar_samples.append(extra["tar_sample"])
        defs_total.update(extra["def_stats"])
        if i % 20 == 0:
            print(f"map {i}/{len(tasks)} tasks", flush=True)
    report = gm_summary(
        hunk_rows,
        node_rows,
        by_id,
        {"snapshot_member_names_sample": tar_samples, "defs_in_patched_files": dict(defs_total)},
    )
    report["gold_hunks.csv"] = gm_write(out / "gold_hunks.csv", hunk_rows)
    report["gold_nodes.csv"] = gm_write(out / "gold_nodes.csv", node_rows)
    (out / "mapping_samples.md").write_text(
        gm_samples(hunk_rows, by_id, node_rows), encoding="utf-8"
    )
    (out / "report.json").write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    return report


def gm_main() -> int:
    """Kernel entry: DATA and OUTD are defined by the kernel wrapper appended after this."""
    print(json.dumps(gm_run(DATA, OUTD), indent=1))  # noqa: F821
    return 0


def gm_cli(argv: list[str]) -> int:
    print(json.dumps(gm_run(Path(argv[1]), Path(argv[2])), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(gm_cli(sys.argv))
