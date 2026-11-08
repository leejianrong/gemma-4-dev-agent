"""Build the public writeup notebook (GEM-27): kaggle/writeup_notebook/kernel.py + metadata.

The notebook has no inputs and no GPU. It carries the exact submission bundle, rebuilds the zip
deterministically, checks its SHA-256 against the value in experiments/runs.csv, prints the prompt
and config, and prints the run log and the localization / co-change tables the paper cites.
Usage: build_notebook.py USERNAME
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kaggle" / "writeup_notebook"
SLUG = "gemma-4-graph-retrieval-study"
TITLE = "Gemma 4 Graph Retrieval Study"
sys.path.insert(0, str(ROOT / "scripts"))

BODY = """
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

OUT = Path("/kaggle/working")


def build_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, files[name].encode("utf-8"))
    return buf.getvalue()


blob = build_zip(SUBMISSION_FILES)
sha = hashlib.sha256(blob).hexdigest()
(OUT / "submission.zip").write_bytes(blob)
(OUT / "runs.csv").write_text(RUNS_CSV)
(OUT / "results_tables.json").write_text(json.dumps(RESULTS, indent=1))
print("zip sha256:", sha)
print("expected   :", EXPECTED_SHA)
assert sha == EXPECTED_SHA, "bundle does not match the submitted zip"
print("OK: this notebook's bundle is byte-identical to the submitted zip\\n")

print("== file hashes")
for name in sorted(SUBMISSION_FILES):
    print(hashlib.sha256(SUBMISSION_FILES[name].encode()).hexdigest()[:16], name)

for name in ("agent.yaml", "eval_config.yaml", "configs/sampling.yaml"):
    print(f"\\n== {name}\\n{SUBMISSION_FILES[name]}")
print("\\n== prompts/system.md\\n" + SUBMISSION_FILES["prompts/system.md"])

print("\\n== run log (experiments/runs.csv)")
for row in csv.DictReader(io.StringIO(RUNS_CSV)):
    keep = ("run_id", "subset", "n_tasks", "n_resolved", "resolution_rate", "minutes_per_task")
    print({k: row[k] for k in keep})

print("\\n== results the paper cites")
for title, rows in RESULTS.items():
    print(f"\\n{title}")
    for r in rows:
        print("  ", r)
"""


def results() -> dict:
    """The two small tables the paper quotes, from the saved summaries (all numbers sourced)."""
    out = {}
    fig = ROOT / "figures" / "eda"
    n5 = json.loads((fig / "eda_05_cochange.json").read_text())["numbers"]
    out["co-change, 50 tasks (A29): set, mean size, recall, precision, median lift"] = [
        [
            k,
            n5[f"mean_set_size_{k}"],
            round(n5[f"recall_{k}"], 3),
            round(n5[f"precision_{k}"], 3),
            n5[f"median_lift_{k}"],
        ]
        for k in ("hop1", "hop2", "same_class", "same_module", "hop1_or_module", "embedding10")
    ]
    n7 = json.loads((fig / "eda_07_async_split.json").read_text())["numbers"]
    out["BM25 recall@10 by target kind (A35)"] = [[k, v] for k, v in n7.items() if "bm25" in k]
    return out


def build(username: str) -> Path:
    from submission import build_zip  # noqa: PLC0415

    files = {
        p.relative_to(ROOT / "submission").as_posix(): p.read_text(encoding="utf-8")
        for p in sorted((ROOT / "submission").rglob("*"))
        if p.is_file()
    }
    with tempfile.TemporaryDirectory() as tmp:
        sha = hashlib.sha256(build_zip(ROOT / "submission", Path(tmp) / "s.zip").read_bytes())
    runs = (ROOT / "experiments" / "runs.csv").read_text(encoding="utf-8")
    src = (
        f"EXPECTED_SHA = {sha.hexdigest()!r}\n"
        f"SUBMISSION_FILES = {files!r}\n"
        f"RUNS_CSV = {runs!r}\n"
        f"RESULTS = {results()!r}\n" + BODY
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "kernel.py").write_text(src, encoding="utf-8")
    meta = {
        "id": f"{username}/{SLUG}",
        "title": TITLE,
        "code_file": "kernel.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": "true",
        "enable_gpu": "false",
        "enable_tpu": "false",
        "enable_internet": "false",
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    (OUT / "kernel-metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return OUT / "kernel.py"


if __name__ == "__main__":
    print(build(sys.argv[1]))
