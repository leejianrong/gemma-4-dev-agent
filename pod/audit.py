"""Hand-check aid for the diff-to-graph-node mapping in explore.py. Stdlib only.

Writes OUT_DIR/audit.md: (1) why hunks fail to map, counted over ALL tasks, (2) a stratified
sample of mapped hunks with the evidence (which removed lines matched which node), (3) examples
of each failure category. Usage: audit.py DATA_DIR OUT_DIR
"""

from __future__ import annotations

import collections
import json
import random
import sys
from pathlib import Path

if "parse_patch" not in globals():  # standalone run; inside the kernel explore.py is inlined above
    from explore import _norm, load_graph, map_hunk, module_candidates, parse_patch


def classify_unmapped(h: dict, path: str, nodes: list[dict], mods: list[str], ids: set[str]) -> str:
    if not path.endswith(".py"):
        return "non_python_file"
    if not h["removed"] and not h["context"]:
        return "new_file_or_pure_addition_without_context"
    if not any(n["id"].startswith(m + ".") for n in nodes for m in mods):
        return "module_has_no_function_or_class_nodes"
    wanted = _norm(h["removed"])
    if not wanted:
        return "pure_addition_no_symbol_in_header_or_context"
    found_elsewhere = any(wanted & _norm((n.get("text") or "").splitlines()) for n in nodes)
    return (
        "removed_lines_in_other_module"
        if found_elsewhere
        else "removed_lines_not_in_any_node_module_level"
    )


def short(lines: list[str], n: int = 4, w: int = 110) -> str:
    out = [("    " + x.strip()[:w]) for x in lines[:n]]
    if len(lines) > n:
        out.append(f"    ... +{len(lines) - n} more")
    return "\n".join(out) if out else "    (none)"


def audit(data: Path, out: Path, seed: int = 7) -> str:
    tasks = [json.loads(x) for x in (data / "tasks.jsonl").read_text().splitlines() if x.strip()]
    cats: collections.Counter = collections.Counter()
    mapped_hunks, unmapped_by_cat = [], collections.defaultdict(list)
    node_kind = collections.Counter()
    module_node_exists = collections.Counter()
    for t in tasks:
        stem = f"{t['instance_id'].rsplit('_', 1)[0]}_{t['base_commit']}"
        g = load_graph(data / "graphs" / f"{stem}.json")
        if not g:
            continue
        nodes = g["nodes"]
        ids = {n["id"] for n in nodes}
        for f in parse_patch(t.get("patch") or ""):
            mods = module_candidates(f["path"])
            if f["path"].endswith(".py"):
                module_node_exists[
                    "module_node_present" if any(m in ids for m in mods) else "module_node_absent"
                ] += 1
            for h in f["hunks"]:
                got = map_hunk(h, nodes, mods) if f["path"].endswith(".py") else []
                if got:
                    cats["mapped"] += 1
                    texts = {n["id"]: n.get("text") or "" for n in nodes}
                    for nid in got:
                        node_kind[
                            "class_like"
                            if nid.rsplit(".", 1)[-1][:1].isupper()
                            else "function_like"
                        ] += 1
                    ev = []
                    for nid in got:
                        lines = _norm(texts[nid].splitlines())
                        ev.append((nid, len(texts[nid]), sorted(_norm(h["removed"]) & lines)[:2]))
                    mapped_hunks.append((t["instance_id"], t["repo"], f["path"], h, ev))
                else:
                    c = classify_unmapped(h, f["path"], nodes, mods, ids)
                    cats[c] += 1
                    unmapped_by_cat[c].append((t["instance_id"], f["path"], h))
    rng = random.Random(seed)
    by_repo = collections.defaultdict(list)
    for m in mapped_hunks:
        by_repo[m[1]].append(m)
    quota = {"fastapi/fastapi": 9, "Textualize/rich": 8, "psf/requests": 5, "encode/httpx": 1}
    sample = []
    for name, items in by_repo.items():
        sample += rng.sample(items, min(len(items), quota.get(name, 3)))
    L = ["# Mapping audit", "", "## Hunk outcomes over all tasks", ""]
    total = sum(cats.values())
    for k, v in cats.most_common():
        L.append(f"- {k}: {v} ({100 * v / total:.0f}%)")
    L += [
        "",
        f"Mapped node kinds: {dict(node_kind)}",
        f"Module node presence per .py file: {dict(module_node_exists)}",
        "",
    ]
    L += ["## Sample of mapped hunks (check: is the node really the edited code?)", ""]
    for tid, _repo, path, h, ev in sample:
        L += [
            f"### {tid} {path}",
            f"hunk ctx: {h['ctx'][:80]!r}",
            "removed:",
            short(h["removed"]),
            "added:",
            short(h["added"], 2),
        ]
        for nid, size, m in ev:
            L.append(f"  -> {nid} (node text {size} chars) matched: {[x[:70] for x in m]}")
        L.append("")
    L += ["## Examples per failure category", ""]
    for c, items in unmapped_by_cat.items():
        L += [f"### {c} ({len(items)} hunks)", ""]
        for tid, path, h in rng.sample(items, min(3, len(items))):
            L += [
                f"- {tid} {path} ctx={h['ctx'][:60]!r}",
                "  removed:",
                short(h["removed"], 3),
                "  added:",
                short(h["added"], 3),
            ]
        L.append("")
    text = "\n".join(L)
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.md").write_text(text, encoding="utf-8")
    return text


def audit_cli(argv: list[str]) -> int:
    print(audit(Path(argv[1]), Path(argv[2])))
    return 0


def audit_main() -> int:
    """Kernel entry: DATA and OUTD are defined by the kernel wrapper that is appended after this."""
    print(audit(DATA, OUTD))  # noqa: F821
    return 0


if __name__ == "__main__":
    raise SystemExit(audit_cli(sys.argv))
