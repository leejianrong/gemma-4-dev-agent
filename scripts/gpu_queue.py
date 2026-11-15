"""Helpers around pueue for the local GPU (docs/GPU_RUNS.md section 16). Standard library only.

    gpu_queue.py add RUN_ID BUNDLE MODEL [--seed N] [--tasks N]   queue one dev-subset run
    gpu_queue.py eta                                                 queue with finish times
    gpu_queue.py wait-vram [--util 0.88] [--margin-mib 512]         block until the GPU has room

pueue runs one job at a time (its default group); this adds what it lacks: a wait until the GPU has
free VRAM (nothing caps VRAM under WSL2, and the Windows desktop takes some) and a finish-time
estimate from the durations in experiments/runs.csv. A job's label is RUN_ID|MODEL|N_TASKS.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs.csv"
MINIMAL_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG")  # pueue stores a job's whole environment


def vram_mib(smi_line: str) -> tuple[int, int]:
    """(used, total) MiB from one `nvidia-smi --query-gpu=memory.used,memory.total` csv row."""
    used, total = (int(x) for x in smi_line.replace("MiB", "").split(","))
    return used, total


def need_mib(util: float, total_mib: int, margin_mib: int) -> int:
    """VRAM a vLLM server takes (util of the whole card) plus a margin that is never touched."""
    return int(util * total_mib) + margin_mib


def estimate_s(rows: list[dict], model: str, n_tasks: int) -> float | None:
    """Seconds for n_tasks: median minutes_per_task of past runs of the model (else of all runs)."""

    def mpt(r: dict) -> float | None:
        try:
            return float(r["minutes_per_task"])
        except (KeyError, ValueError):
            return None

    same = [m for r in rows if r.get("model") == model and (m := mpt(r))]
    anyrun = [m for r in rows if (m := mpt(r))]
    pool = same or anyrun
    return statistics.median(pool) * 60 * n_tasks if pool else None


def parse_time(text: str) -> datetime:
    """pueue timestamps carry nanoseconds, which datetime cannot read."""
    head, _, tail = text.partition(".")
    zone = tail[tail.index("+") :] if "+" in tail else ""
    return datetime.fromisoformat(f"{head}.{tail[:6]}{zone}" if tail else text)


def state(task: dict) -> tuple[str, dict]:
    st = task["status"]
    return (st, {}) if isinstance(st, str) else next(iter(st.items()))


def schedule(tasks: dict, rows: list[dict], now: datetime) -> list[dict]:
    """Per unfinished job: label, state, estimate, start and end. The queue is sequential, so a
    queued job starts when the one before it ends (a running job past its estimate ends now)."""
    out, cursor = [], now
    for task in sorted(tasks.values(), key=lambda t: t["id"]):
        name, info = state(task)
        if name not in ("Running", "Queued", "Stashed"):
            continue
        run_id, _, rest = (task.get("label") or task["command"]).partition("|")
        model, _, n = rest.partition("|")
        est = estimate_s(rows, model, int(n)) if n.isdigit() else None
        start = parse_time(info["start"]) if name == "Running" else cursor
        end = max(start + timedelta(seconds=est), now) if est is not None else None
        out.append(
            {
                "id": task["id"],
                "label": run_id,
                "state": name,
                "est_s": est,
                "start": start,
                "end": end,
            }
        )
        if name != "Stashed":
            cursor = end or cursor
    return out


def read_rows() -> list[dict]:
    return list(csv.DictReader(RUNS.open(encoding="utf-8"))) if RUNS.is_file() else []


def pueue_json() -> dict:
    res = subprocess.run(["pueue", "status", "--json"], capture_output=True, text=True, check=True)
    return json.loads(res.stdout)["tasks"]


def smi() -> tuple[int, int]:
    res = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=True,
    )
    return vram_mib(res.stdout.splitlines()[0])


def cmd_eta(_: argparse.Namespace) -> int:
    now = datetime.now().astimezone()
    jobs = schedule(pueue_json(), read_rows(), now)
    if not jobs:
        print("queue empty")
    for j in jobs:
        est = f"{j['est_s'] / 3600:.1f} h" if j["est_s"] is not None else "unknown"
        end = j["end"].astimezone().strftime("%a %H:%M") if j["end"] else "unknown"
        start = j["start"].astimezone().strftime("%a %H:%M")
        print(f"{j['id']:>3} {j['state']:<8} {j['label']:<28} est {est:>7}  {start} -> {end}")
    used, total = smi()
    print(f"GPU {used}/{total} MiB used")
    return 0


def cmd_wait_vram(a: argparse.Namespace) -> int:
    deadline = time.time() + a.timeout
    while True:
        used, total = smi()
        need = need_mib(a.util, total, a.margin_mib)
        if total - used >= need:
            print(f"vram ok: {total - used} MiB free, need {need}", flush=True)
            return 0
        if time.time() > deadline:
            print(f"vram wait timed out: {total - used} MiB free, need {need}", file=sys.stderr)
            return 1
        print(f"waiting for vram: {total - used} MiB free, need {need}", flush=True)
        time.sleep(a.poll)


def cmd_add(a: argparse.Namespace) -> int:
    n = a.tasks
    label = f"{a.run_id}|{a.model}|{n}"
    job = [str(ROOT / "pod" / "local_job.sh"), a.bundle, a.model, a.run_id, str(a.seed), str(n)]
    env = {k: os.environ[k] for k in MINIMAL_ENV if k in os.environ}
    env["PATH"] = f"{Path.home() / '.cargo/bin'}:{env.get('PATH', '')}"
    cmd = ["pueue", "add", "--label", label, "--working-directory", str(ROOT), "--", *job]
    return subprocess.run(cmd, env=env).returncode


def main(argv: list[str]) -> int:
    if not shutil.which("pueue", path=f"{Path.home() / '.cargo/bin'}:{os.environ['PATH']}"):
        sys.exit("pueue not found: cargo install --locked pueue")
    os.environ["PATH"] = f"{Path.home() / '.cargo/bin'}:{os.environ['PATH']}"
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("run_id")
    add.add_argument("bundle")
    add.add_argument("model")
    add.add_argument("--seed", type=int, default=1)
    add.add_argument("--tasks", type=int, default=36, help="size of the dev subset (36)")
    add.set_defaults(fn=cmd_add)
    sub.add_parser("eta").set_defaults(fn=cmd_eta)
    w = sub.add_parser("wait-vram")
    w.add_argument("--util", type=float, default=float(os.environ.get("ER_VLLM_GPU_UTIL", "0.88")))
    w.add_argument("--margin-mib", type=int, default=512)
    w.add_argument("--poll", type=int, default=30)
    w.add_argument("--timeout", type=int, default=6 * 3600)
    w.set_defaults(fn=cmd_wait_vram)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
