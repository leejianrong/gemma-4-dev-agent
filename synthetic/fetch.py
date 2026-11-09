"""Download pinned snapshots of the synthetic-dataset repos (GEM-87).

Each manifest entry pins a repo to a release tag and the full commit SHA that tag points at. We
clone shallow at the tag and refuse the checkout unless HEAD equals the pinned SHA, so a moved
tag cannot change the dataset. Only `git` is run, and nothing from a downloaded repo is executed.
Usage: python -m synthetic.fetch CACHE_DIR [--manifest synthetic/repos.json] [NAME ...]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "repos.json"
SHA = re.compile(r"[0-9a-f]{40}")


class FetchError(RuntimeError):
    pass


def load_manifest(path: Path = MANIFEST) -> list[dict]:
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    for e in entries:
        for key in ("name", "url", "tag", "sha"):
            if not e.get(key):
                raise ValueError(f"manifest entry {e.get('name')!r} lacks {key}")
        if not SHA.fullmatch(e["sha"]):
            raise ValueError(f"{e['name']}: sha must be 40 lowercase hex characters")
    return entries


def _git(runner, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return runner(["git", *args], capture_output=True, text=True, env=env, timeout=600)


def _head(runner, dest: Path) -> str:
    res = _git(runner, "-C", str(dest), "rev-parse", "HEAD")
    return (res.stdout or "").strip()


def fetch(entry: dict, cache: Path, runner=subprocess.run) -> Path:
    """Return the checkout of `entry` under `cache`, cloning if needed. Raises on a wrong HEAD."""
    dest = Path(cache) / entry["name"]
    if dest.exists():
        head = _head(runner, dest)
        if head != entry["sha"]:
            raise FetchError(
                f"{entry['name']}: existing HEAD {head[:12]} is not {entry['sha'][:12]}"
            )
        return dest
    res = _git(runner, "clone", "--depth", "1", "--branch", entry["tag"], entry["url"], str(dest))
    if res.returncode != 0:
        raise FetchError(f"{entry['name']}: clone failed: {(res.stderr or '').strip()[:200]}")
    head = _head(runner, dest)
    if head != entry["sha"]:
        shutil.rmtree(dest, ignore_errors=True)
        raise FetchError(
            f"{entry['name']}: tag {entry['tag']} gives HEAD {head[:12]}, "
            f"pinned {entry['sha'][:12]}"
        )
    return dest


def main(argv: list[str]) -> int:
    args = argv[1:]
    manifest = MANIFEST
    if "--manifest" in args:
        i = args.index("--manifest")
        manifest = Path(args[i + 1])
        del args[i : i + 2]
    if not args:
        print(__doc__)
        return 2
    cache, names = Path(args[0]), set(args[1:])
    cache.mkdir(parents=True, exist_ok=True)
    bad = 0
    for e in load_manifest(manifest):
        if names and e["name"] not in names:
            continue
        try:
            print(f"ok   {e['name']:18s} {fetch(e, cache)}")
        except FetchError as err:
            bad += 1
            print(f"FAIL {err}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
