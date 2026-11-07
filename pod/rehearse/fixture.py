"""Build a tiny fake competition tree: tasks.jsonl, graphs/, embeddings/, listing.csv."""
import json
import sys
import zipfile
from pathlib import Path

PATCH = """diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -1,3 +1,3 @@ def alpha(x)
 def alpha(x):
-    return x + 1
+    return x + 2
"""
NODES = [{"id": "pkg.mod.alpha", "name": "pkg.mod.alpha", "text": "def alpha(x):\n    return x + 1\n"}]


def npy():
    h = ("{'descr': '<f4', 'fortran_order': False, 'shape': (256,), }").ljust(118) + "\n"
    return b"\x93NUMPY\x01\x00" + len(h).to_bytes(2, "little") + h.encode() + bytes(1024)


def main(root: Path, n: int = 5) -> None:
    (root / "graphs").mkdir(parents=True)
    (root / "embeddings").mkdir()
    tasks = []
    for i in range(n):
        sha = f"{i:040x}"
        edges = [{"source": "pkg.mod.alpha", "target": "pkg.mod.alpha", "type": "calls", "key": 0}]
        (root / "graphs" / f"pkg_{sha}.json").write_text(json.dumps({"nodes": NODES, "edges": edges}))
        with zipfile.ZipFile(root / "embeddings" / f"pkg_{sha}.npz", "w") as zf:
            zf.writestr("pkg.mod.alpha.npy", npy())
        tasks.append({"instance_id": f"pkg_{i}", "repo": "o/pkg", "base_commit": sha, "patch": PATCH,
                      "problem_statement": "alpha is wrong", "hints_text": ""})
    (root / "tasks.jsonl").write_text("\n".join(json.dumps(t) for t in tasks) + "\n")
    rows = ["name,size,creationDate"]
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rows.append(f"{p.relative_to(root).as_posix()},{p.stat().st_size},2026-10-13 11:50:18")
    (root.parent / "listing.csv").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
