"""Download the competition data into data/competition/ with the kaggle CLI, politely and resumably.

Lists the files, picks tasks.jsonl, graphs/, embeddings/ and optionally snapshots/, then downloads
a few at a time. A file counts as done when it exists with the listed size, so reruns resume. On
HTTP 429 a worker backs off and retries. Needs the kaggle CLI logged in. The data stays on this
machine (data/ is gitignored); the competition rules forbid sharing it (terms 4b).

Usage: python scripts/fetch_data.py [--snapshots none|scored|all] [--workers 2] [--dest DIR]
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

COMP = "gemma-4-developer-agent"
ROW = re.compile(r"^[^ ]+,[0-9]+,")


def parse_listing(text: str) -> tuple[list[tuple[str, int]], str | None]:
    """File rows (name, size) and the next page token from `kaggle competitions files -v` output."""
    rows = []
    for line in text.splitlines():
        if ROW.match(line):
            name, size, *_ = line.split(",")
            rows.append((name, int(size)))
    tok = re.search(r"^Next Page Token = (\S+)", text, re.MULTILINE)
    return rows, tok.group(1) if tok else None


def wanted(rows, snapshots: str, scored_ids: set[str]) -> list[tuple[str, int]]:
    out = []
    for name, size in rows:
        if name == "tasks.jsonl" or name.startswith(("graphs/", "embeddings/")):
            out.append((name, size))
        elif name.startswith("snapshots/") and snapshots != "none":
            tid = name.removeprefix("snapshots/").removesuffix(".tgz")
            if snapshots == "all" or tid in scored_ids:
                out.append((name, size))
    return out


def list_files() -> list[tuple[str, int]]:
    rows, tok = [], None
    for _ in range(40):
        cmd = ["kaggle", "competitions", "files", COMP, "--page-size", "200", "-v"]
        if tok:
            cmd += ["--page-token", tok]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode:
            raise SystemExit(f"listing failed: {res.stdout[-200:]} {res.stderr[-200:]}")
        page, tok = parse_listing(res.stdout)
        rows += page
        if not tok:
            break
    return rows


def fetch_one(name: str, size: int, dest: Path, tries: int = 6) -> bool:
    target = dest / name
    if target.is_file() and target.stat().st_size == size:
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, tries + 1):
        res = subprocess.run(
            [
                "kaggle",
                "competitions",
                "download",
                COMP,
                "-f",
                name,
                "-p",
                str(target.parent),
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        z = Path(str(target) + ".zip")
        if not target.is_file() and z.is_file():
            with zipfile.ZipFile(z) as zf:
                zf.extractall(target.parent)
            z.unlink()
        if target.is_file() and target.stat().st_size == size:
            return True
        wait = 30 * attempt if "429" in res.stdout + res.stderr else 5 * attempt
        print(
            f"retry {attempt} {name}: {(res.stderr or res.stdout)[-120:].strip()} (wait {wait}s)",
            flush=True,
        )
        time.sleep(wait)
    return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshots", choices=["none", "scored", "all"], default="none")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--dest", default="data/competition")
    ap.add_argument("--scored-csv", default="data/map/gold_nodes.csv")
    args = ap.parse_args(argv)
    scored: set[str] = set()
    if args.snapshots == "scored":
        with open(args.scored_csv, newline="", encoding="utf-8") as fh:
            scored = {r["instance_id"] for r in csv.DictReader(fh)}
    todo = wanted(list_files(), args.snapshots, scored)
    total = sum(s for _, s in todo)
    print(f"{len(todo)} files, {total / 2**30:.1f} GiB -> {args.dest}", flush=True)
    dest, done, failed, t0 = Path(args.dest), 0, [], time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        for (name, _), ok in zip(
            todo, ex.map(lambda t: fetch_one(t[0], t[1], dest), todo), strict=True
        ):
            done += 1
            if not ok:
                failed.append(name)
            if done % 20 == 0 or done == len(todo):
                print(
                    f"{done}/{len(todo)} done, {len(failed)} failed, {time.time() - t0:.0f}s",
                    flush=True,
                )
    print("FAILED:", failed[:10] if failed else "none", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
