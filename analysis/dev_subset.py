"""GEM-12: pick the fixed dev subset for ablations, deterministically.

Rule: rich is held out (winners are confirmed there, GEM-33). From the other repos we drop tasks
whose baseline test run was inconclusive (they carry no signal until the sandbox gap is
understood, GEM-16), then draw a fixed number per repo with a seeded shuffle. The id list is
written to data/dev_subset.json, which is gitignored: it is derived from competition data, and the
rule plus the seed regenerate it. Usage: python -m analysis.dev_subset
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

HELD_OUT = "Textualize/rich"
PER_REPO = {"fastapi/fastapi": 30, "psf/requests": 6, "encode/httpx": 1}
SEED = 0


def pick(
    ids_by_repo: dict[str, list[str]], drop: set[str], per_repo: dict[str, int], seed: int
) -> dict[str, list[str]]:
    out = {}
    for repo, n in per_repo.items():
        pool = sorted(i for i in ids_by_repo.get(repo, []) if i not in drop)
        random.Random(f"{seed}:{repo}").shuffle(pool)
        out[repo] = sorted(pool[:n])
    return out


def load(hunks: Path, results: Path, run_dir_classes: Path | None = None):
    ids: dict[str, list[str]] = {}
    seen = set()
    with open(hunks, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["instance_id"] not in seen:
                seen.add(r["instance_id"])
                ids.setdefault(r["repo"], []).append(r["instance_id"])
    from analysis.failure_classes import classify_run

    drop = {r["instance_id"] for r in classify_run(results, hunks) if r["class"] == "inconclusive"}
    return ids, drop


if __name__ == "__main__":
    ids, drop = load(Path("data/map/gold_hunks.csv"), Path("data/runs/gemma-4-eval-runner"), None)
    ids.pop(HELD_OUT, None)
    chosen = pick(ids, drop, PER_REPO, SEED)
    flat = sorted(i for v in chosen.values() for i in v)
    Path("data/dev_subset.json").write_text(
        json.dumps({"seed": SEED, "per_repo": PER_REPO, "ids": flat}, indent=1), encoding="utf-8"
    )
    print({k: len(v) for k, v in chosen.items()}, "total", len(flat), "dropped", len(drop))
