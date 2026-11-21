#!/usr/bin/env python3
"""Answer semula's parked model calls with Claude Haiku (docs/research/teacher-traces.md).

Our harness calls a semula container as its model. This worker, on the host, takes each
parked call and asks a fresh `claude -p --model haiku` with every tool switched off. The
agent's own tools run in the no-network task container, so Haiku only returns text.
Synthetic and non-competition tasks only (rules 4b): the request holds the task text.

  python scripts/teacher_worker.py [--container semula-teacher] [--workers 2] [--model haiku]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

INSTRUCTION = (
    "You are the language model behind an autonomous software-engineering agent. "
    "The JSON on stdin is the next chat request: `messages` so far (system prompt first) "
    "and the `tools` you may call. "
    "Decide the agent's next step exactly as a strong model would, following the system prompt. "
    "Reply with ONE JSON object and nothing else. To call a tool: "
    '{"tool":"<name>","arguments":{...}} using only a listed tool and its schema. '
    'To end the session with text: {"text":"<message>"}. One tool call per reply. '
    "Rules: always make a real source edit and call submit_patch before any text reply; "
    "never end with text until submit_patch has succeeded or the call budget is spent. "
    "Never write tool-result text yourself."
)
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def _sh(container: str, *args: str, timeout: int = 90) -> str:
    return subprocess.run(
        ["docker", "exec", container, "semula", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    ).stdout


def to_answer(raw: str) -> dict:
    """Haiku's reply as a semula answer; anything but a valid tool reply becomes text."""
    text = FENCE.sub("", raw.strip())
    try:
        obj = json.loads(text)
    except ValueError:
        return {"content": raw.strip() or "Done."}
    if isinstance(obj, dict) and isinstance(obj.get("tool"), str):
        args = obj.get("arguments")
        return {
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "function": {
                            "name": obj["tool"],
                            "arguments": args if isinstance(args, dict) else {},
                        }
                    }
                ],
            }
        }
    if isinstance(obj, dict) and "text" in obj:
        return {"content": str(obj["text"]) or "Done."}
    return {"content": raw.strip() or "Done."}


def ask_haiku(request: dict, model: str, timeout: int) -> str:
    body = json.dumps({"messages": request.get("messages"), "tools": request.get("tools")})
    with tempfile.TemporaryDirectory() as cwd:  # empty dir: nothing of ours for it to read
        out = subprocess.run(
            [
                "claude",
                "-p",
                INSTRUCTION,
                "--model",
                model,
                "--tools",
                "",
                "--strict-mcp-config",
                "--disable-slash-commands",
                "--setting-sources",
                "",
                "--no-session-persistence",
                "--output-format",
                "text",
            ],
            input=body,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    if out.returncode != 0:
        raise RuntimeError(f"claude exit {out.returncode}")
    return out.stdout


def handle(container: str, pid: str, model: str, stats: dict, lock: threading.Lock) -> None:
    t0 = time.time()
    try:
        request = json.loads(_sh(container, "show", pid, "--json"))["request"]
        answer = to_answer(ask_haiku(request, model, timeout=240))
        path = f"/tmp/ans-{pid}.json"
        subprocess.run(
            ["docker", "exec", "-i", container, "sh", "-c", f"cat > {path}"],
            input=json.dumps(answer),
            text=True,
            check=True,
        )
        _sh(container, "answer", pid, "--file", path)
        key = "tool" if "message" in answer else "text"
    except Exception as e:  # leave the call parked; the loop will not retry it
        print(f"FAIL {pid}: {type(e).__name__} {str(e)[:120]}", flush=True)
        key = "fail"
    with lock:
        stats[key] = stats.get(key, 0) + 1
        stats["secs"] = stats.get("secs", 0) + time.time() - t0
        print(f"{pid[-6:]} {key} {time.time() - t0:.0f}s total={stats}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", default="semula-teacher")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--model", default="haiku")
    a = ap.parse_args()
    seen: set[str] = set()
    stats: dict = {}
    lock = threading.Lock()
    with ThreadPoolExecutor(a.workers) as pool:
        while True:
            try:
                rows = json.loads(_sh(a.container, "pending", "--wait", "30", "--json", timeout=60))
            except Exception as e:
                print("pending failed:", type(e).__name__, flush=True)
                time.sleep(5)
                continue
            for r in rows:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    pool.submit(handle, a.container, r["id"], a.model, stats, lock)


if __name__ == "__main__":
    main()
