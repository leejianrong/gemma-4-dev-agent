"""Realism check for a synthetic task set: aggregate shape of the gold patches and issues.

Computes the same aggregates for a synthetic tasks.jsonl and for the real one and prints them side
by side with the distance between the gold-size histograms. Standard library only, text parsing
only; output is counts and shares, never per-task data (competition rules 4b).
Usage: python -m synthetic.realism SYNTHETIC_TASKS.jsonl [--real data/competition/tasks.jsonl]
"""

from __future__ import annotations

import json
import re
import statistics as st
import sys
from pathlib import Path

# Gold-size bins, in changed library lines (docs/BENCHMARK_V2.md): None = no upper limit.
BINS: list[tuple[int, int | None]] = [(0, 4), (5, 12), (13, 44), (45, None)]
ASYNC = re.compile(r"^[+-].*\b(async def|await)\b", re.M)


def patch_stats(patch: str) -> dict:
    lines = hunks = 0
    files = set()
    for ln in patch.splitlines():
        if ln.startswith("+++ ") and ln != "+++ /dev/null":
            files.add(ln[4:].strip())  # present with or without `diff --git` header lines
        elif ln.startswith("@@"):
            hunks += 1
        elif ln[:1] in "+-" and not ln.startswith(("+++", "---")):
            lines += 1
    return {"lines": lines, "hunks": hunks, "files": len(files), "async": bool(ASYNC.search(patch))}


def bin_shares(sizes: list[int]) -> list[float]:
    def inside(n: int, lo: int, hi: int | None) -> bool:
        return n >= lo and (hi is None or n <= hi)

    return [sum(inside(n, lo, hi) for n in sizes) / len(sizes) for lo, hi in BINS]


def quantiles(xs: list[int]) -> dict:
    q = st.quantiles(xs, n=20) if len(xs) > 1 else [xs[0]] * 19
    return {"p25": st.quantiles(xs, n=4)[0] if len(xs) > 1 else xs[0], "p90": q[17]}


def summarize(tasks: list[dict]) -> dict:
    stats = [patch_stats(t["patch"]) for t in tasks]
    sizes = [s["lines"] for s in stats]
    words = [len(t["problem_statement"].split()) for t in tasks]
    return {
        "n": len(tasks),
        "gold_lines_median": st.median(sizes),
        "gold_lines_p25": quantiles(sizes)["p25"],
        "gold_lines_p90": quantiles(sizes)["p90"],
        "hunks_median": st.median(s["hunks"] for s in stats),
        "files_median": st.median(s["files"] for s in stats),
        "async_share": sum(s["async"] for s in stats) / len(stats),
        "issue_words_median": st.median(words),
        "size_bins": bin_shares(sizes),
    }


def compare(real: dict, synth: dict) -> dict:
    """Total variation distance between the gold-size histograms (0 = same, 1 = disjoint)."""
    d = sum(abs(a - b) for a, b in zip(real["size_bins"], synth["size_bins"], strict=True)) / 2
    return {"bin_distance": round(d, 3)}


def read_tasks(path: Path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def render(real: dict, synth: dict) -> str:
    rows = [f"| {k} | {fmt(real[k])} | {fmt(synth[k])} |" for k in real if k != "size_bins"]
    labels = ["<=4", "5-12", "13-44", ">44"]
    for lab, a, b in zip(labels, real["size_bins"], synth["size_bins"], strict=True):
        rows.append(f"| share of tasks with {lab} gold lines | {a:.0%} | {b:.0%} |")
    return "\n".join(["| measure | real | synthetic |", "|---|---|---|", *rows])


def fmt(v) -> str:
    return f"{v:.2f}" if isinstance(v, float) else str(v)


def main(argv: list[str]) -> int:
    args = argv[1:]
    real_path = Path("data/competition/tasks.jsonl")
    if "--real" in args:
        i = args.index("--real")
        real_path = Path(args[i + 1])
        del args[i : i + 2]
    if not args:
        print(__doc__)
        return 2
    real, synth = summarize(read_tasks(real_path)), summarize(read_tasks(Path(args[0])))
    print(render(real, synth))
    print(f"\ngold-size histogram distance: {compare(real, synth)['bin_distance']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
