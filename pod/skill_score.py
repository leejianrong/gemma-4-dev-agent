"""Score the localize skill offline: rank the defs of each task's snapshot, compare to gold nodes.

For every task with a gold node, the old-file snapshot (`snapshots/<id>.tgz`) is read, indexed with
the skill's own functions (experiments/skills/localize/scripts/localize.py), and ranked against the
issue text. Targets and metrics are the study's (pod/localize.py): gold nodes in the graph's library
pool, hit@k and recall@k. A gold node the skill never lists counts as a miss. The same graph-text
BM25 as the study runs alongside as `graph_bm25`, so the two are compared on the same tasks.
Outputs aggregate numbers and per-task rows; only the aggregates may leave the kernel owner's hands.
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import sys
import tarfile
import time
from pathlib import Path

if "sk_index" not in globals():  # standalone; in the kernel the pieces are inlined above
    _root = Path(__file__).resolve().parents[1]
    _spec = importlib.util.spec_from_file_location(
        "skill_localize", _root / "experiments/skills/localize/scripts/localize.py"
    )
    _sk = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_sk)
    sk_index, sk_rank, sk_is_library = _sk.sk_index, _sk.sk_rank, _sk.sk_is_library
    from explore import load_graph
    from localize import ll_gold, ll_is_library, ll_metrics, ll_summary, ll_task_rows, ll_write

SS_VARIANTS = ("head", "full")
SS_MAX_BYTES = 1_000_000


def ss_read_py(tgz: Path) -> dict[str, str]:
    """Library .py files of a snapshot as {relative path: source}."""
    files: dict[str, str] = {}
    try:
        with tarfile.open(tgz, "r:gz") as tf:
            for m in tf:
                name = m.name[2:] if m.name.startswith("./") else m.name
                if not m.isfile() or m.size > SS_MAX_BYTES or not sk_is_library(name):
                    continue
                fh = tf.extractfile(m)
                if fh is not None:
                    files[name] = fh.read().decode("utf-8", "replace")
    except (OSError, tarfile.TarError, EOFError):
        pass
    return files


def ss_task_rows(task: dict, graph: dict, files: dict[str, str], gold: set[str]) -> list[dict]:
    """One row per skill variant for a task, with the ranking time of that variant."""
    pool = {n["id"] for n in graph["nodes"] if ll_is_library(n["id"])}
    target = gold & pool
    if not target:
        return []
    rows = []
    for variant in SS_VARIANTS:
        t0 = time.time()
        cands = sk_index(files, variant)
        ranked = [c["id"] for c, _ in sk_rank(cands, task.get("problem_statement") or "")]
        seconds = time.time() - t0
        have = {c["id"] for c in cands}
        rows.append(
            {
                "instance_id": task["instance_id"],
                "repo": task["repo"],
                "pool": "library",
                "method": f"skill_{variant}",
                "n_candidates": len(cands),
                "n_gold_in_pool": len(target),
                "n_gold_total": len(gold),
                **ll_metrics(ranked, target),
                "gold": "|".join(sorted(target)),
                "top": "|".join(ranked[:20]),
                "seconds": round(seconds, 3),
                "coverage": round(len(target & have) / len(target), 3),
            }
        )
    return rows


def ss_timing(rows: list[dict]) -> dict:
    out = {}
    for variant in SS_VARIANTS:
        mine = [r for r in rows if r["method"] == f"skill_{variant}"]
        s = sorted(r["seconds"] for r in mine)
        if s:
            out[variant] = {
                "tasks": len(s),
                "median_s": round(statistics.median(s), 3),
                "p90_s": round(s[int(0.9 * (len(s) - 1))], 3),
                "max_s": round(s[-1], 3),
                "mean_gold_coverage": round(sum(r["coverage"] for r in mine) / len(mine), 3),
            }
    return out


def ss_run(data: Path, gold_csv: Path, out: Path) -> dict:
    import numpy as np

    out.mkdir(parents=True, exist_ok=True)
    gold = ll_gold(gold_csv)
    tasks = [
        json.loads(x)
        for x in (data / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    rows: list[dict] = []
    for i, t in enumerate(tasks, 1):
        g = gold.get(t["instance_id"])
        if not g:
            continue
        stem = f"{t['instance_id'].rsplit('_', 1)[0]}_{t['base_commit']}"
        graph = load_graph(data / "graphs" / f"{stem}.json")
        files = ss_read_py(data / "snapshots" / f"{t['instance_id']}.tgz")
        if not graph or not files:
            print(f"WARN {t['instance_id']}: graph={bool(graph)} files={len(files)}", flush=True)
            continue
        rows += ss_task_rows(t, graph, files, g)
        rows += [
            {**r, "method": "graph_bm25"}
            for r in ll_task_rows(np, t, graph, None, g)
            if r["pool"] == "library" and r["method"] == "bm25"
        ]
        if i % 10 == 0:
            print(f"score {i}/{len(tasks)} tasks", flush=True)
    summary = [r for r in ll_summary(rows) if r["pool"] == "library"]
    ll_write(out / "skill_tasks.csv", rows)
    ll_write(out / "skill_summary.csv", summary)
    report = {
        "tasks_scored": len({r["instance_id"] for r in rows}),
        "summary": [r for r in summary if r["repo"] == "all repos"],
        "per_repo": [r for r in summary if r["repo"] != "all repos"],
        "timing": ss_timing(rows),
    }
    (out / "skill_report.json").write_text(json.dumps(report, separators=(",", ":")))
    return report


def ss_main() -> int:
    """Kernel entry: re-derive the gold nodes with gold_map, then score the skill."""
    gm_run(DATA, OUTD / "map")  # noqa: F821
    report = ss_run(DATA, OUTD / "map" / "gold_nodes.csv", OUTD)  # noqa: F821
    (OUTD / "report.json").write_text(json.dumps(report, separators=(",", ":")))  # noqa: F821
    print(json.dumps(report["summary"], indent=1))
    print(json.dumps(report["timing"], indent=1))
    return 0


def ss_cli(argv: list[str]) -> int:
    report = ss_run(Path(argv[1]), Path(argv[2]), Path(argv[3]))
    print(json.dumps(report["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(ss_cli(sys.argv))
