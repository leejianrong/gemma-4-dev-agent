"""Report the file layouts of the competition data without copying its content (GEM-83).

Writes OUT_DIR/layout.json: field names and types of tasks.jsonl, the keys of one graph, the keys,
dtypes and shapes of one embeddings archive, and how node ids line up between them. Only names,
types, counts and a few example symbol ids are kept; no issue text, patch or source text.
Usage: layout_probe.py DATA_DIR OUT_DIR
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def shape_of(v, depth: int = 0):
    """A short description of a JSON value: its type, and the types inside it."""
    if isinstance(v, dict):
        if depth >= 2:
            return {"type": "dict", "keys": sorted(v)[:12]}
        return {
            "type": "dict",
            "fields": {k: shape_of(x, depth + 1) for k, x in list(v.items())[:25]},
        }
    if isinstance(v, list):
        return {"type": "list", "len": len(v), "item": shape_of(v[0], depth + 1) if v else None}
    if isinstance(v, str):
        return {"type": "str", "len": len(v)}
    return {"type": type(v).__name__}


def task_layout(path: Path) -> dict:
    rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    return {
        "n_tasks": len(rows),
        "fields": sorted({k for r in rows for k in r}),
        "first_row_shape": shape_of(rows[0]) if rows else None,
        "repos": sorted({str(r.get("repo")) for r in rows}),
    }


def graph_layout(path: Path) -> dict:
    g = json.loads(path.read_text(encoding="utf-8"))
    out = {"file": path.name, "shape": shape_of(g)}
    nodes = g.get("nodes") if isinstance(g, dict) else None
    if isinstance(nodes, list) and nodes:
        first = nodes[0]
        out["n_nodes"] = len(nodes)
        out["node_keys"] = sorted(first) if isinstance(first, dict) else None
        ids = [n.get("id") for n in nodes[:5]] if isinstance(first, dict) else []
        out["example_ids"] = [i for i in ids if isinstance(i, str)][:3]
    return out


def embedding_layout(path: Path, graph_ids: set[str]) -> dict:
    import numpy as np

    z = np.load(path, allow_pickle=True)
    out = {"file": path.name, "arrays": {}}
    for k in z.files:
        a = z[k]
        out["arrays"][k] = {"dtype": str(a.dtype), "shape": list(a.shape)}
        if a.dtype.kind in "US O" and a.ndim == 1:
            vals = [str(x) for x in a[:3]]
            out["arrays"][k]["example"] = vals
            out["arrays"][k]["overlap_with_graph_ids"] = len({str(x) for x in a} & graph_ids)
    return out


def layout(data: Path, outd: Path) -> dict:
    res = {"top_level": sorted(p.name for p in data.iterdir())}
    if (data / "tasks.jsonl").is_file():
        res["tasks"] = task_layout(data / "tasks.jsonl")
    gfiles = sorted((data / "graphs").glob("*.json"))
    efiles = sorted((data / "embeddings").glob("*.npz"))
    res["n_graph_files"], res["n_embedding_files"] = len(gfiles), len(efiles)
    if gfiles:
        res["graph"] = graph_layout(gfiles[0])
        ids = set()
        raw = json.loads(gfiles[0].read_text(encoding="utf-8"))
        for n in raw.get("nodes", []) if isinstance(raw, dict) else []:
            if isinstance(n, dict) and isinstance(n.get("id"), str):
                ids.add(n["id"])
        match = [e for e in efiles if e.stem == gfiles[0].stem] or efiles[:1]
        if match:
            res["embedding"] = embedding_layout(match[0], ids)
    outd.mkdir(parents=True, exist_ok=True)
    (outd / "layout.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def lp_main() -> int:
    """Kernel entry: DATA and OUTD are defined by the kernel wrapper appended after this."""
    print(json.dumps(layout(DATA, OUTD), indent=2))  # noqa: F821
    return 0


def lp_cli(argv: list[str]) -> int:
    layout(Path(argv[1]), Path(argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(lp_cli(sys.argv))
