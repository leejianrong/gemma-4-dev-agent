"""Turn resolved teacher runs into chat-format training records (docs/research/teacher-traces.md).

Input: run folders holding `task_results.csv` and `raw/traces/trace_<id>.json` (ATIF steps).
Output (local, never git; synthetic tasks only): `train.jsonl`, one record per kept trajectory
with `messages` (system, user, assistant with tool_calls, tool results), `tools` and `meta`,
plus `stats.json` with aggregate counts per filter.

  python -m analysis.teacher_dataset OUT_DIR TOOLS_JSON RUN_DIR [RUN_DIR ...] [--val-repo NAME]
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

MAX_CALLS = 28  # the harness limit the student will run under
MAX_REPEAT = 3  # the same call this many times in a row is a loop, not a lesson


def to_messages(trace: dict) -> list[dict]:
    """ATIF steps as chat messages: one assistant turn per agent step, then its tool result."""
    msgs: list[dict] = []
    for st in trace["steps"]:
        src = st["source"]
        if src in ("system", "user"):
            msgs.append({"role": src, "content": st.get("message") or ""})
            continue
        calls = st.get("tool_calls") or []
        turn: dict = {"role": "assistant", "content": st.get("message") or None}
        if calls:
            turn["tool_calls"] = [
                {
                    "id": c["tool_call_id"],
                    "type": "function",
                    "function": {
                        "name": c["function_name"],
                        "arguments": json.dumps(c["arguments"]),
                    },
                }
                for c in calls
            ]
        msgs.append(turn)
        if calls:
            obs = (st.get("observation") or {}).get("content", "")
            msgs.append({"role": "tool", "tool_call_id": calls[-1]["tool_call_id"], "content": obs})
    return msgs


def _calls(msgs: list[dict]) -> list[tuple[str, str]]:
    return [
        (c["function"]["name"], c["function"]["arguments"])
        for m in msgs
        for c in m.get("tool_calls", [])
    ]


def repair(msgs: list[dict]) -> tuple[list[dict], int]:
    """Drop each text-only assistant turn that the harness answered with a system nudge, with the
    nudge. These are the teacher's malformed tool calls (`<invoke ...` as text); what is left is a
    clean sequence of valid calls. Returns the messages and how many turns were removed."""
    out: list[dict] = []
    removed = 0
    i = 0
    while i < len(msgs):
        m = msgs[i]
        text_only = m["role"] == "assistant" and m.get("content") and not m.get("tool_calls")
        if text_only and i + 1 < len(msgs) and msgs[i + 1]["role"] == "system":
            removed += 1
            i += 2
            continue
        out.append(m)
        i += 1
    return out, removed


def reject_reason(msgs: list[dict]) -> str | None:
    """Why a resolved trajectory is not worth imitating; None to keep it."""
    calls = _calls(msgs)
    names = [n for n, _ in calls]
    if "submit_patch" not in names:
        return "no submit_patch"
    if len(calls) > MAX_CALLS:
        return "over the call limit"
    run = 1
    for a, b in zip(calls, calls[1:], strict=False):
        run = run + 1 if a == b else 1
        if run >= MAX_REPEAT:
            return "repeated call loop"
    if not any(n in ("edit_file", "write_file") for n in names):
        return "no edit"
    if any(
        m["role"] == "assistant" and m.get("content") and not m.get("tool_calls") for m in msgs[:-1]
    ):
        return "text-only turn before the end"
    return None


def build(run_dirs: list[Path], tools: list[dict], val_repo: str = "") -> tuple[list[dict], dict]:
    kept: list[dict] = []
    stats: Counter = Counter()
    seen: set[str] = set()
    for rd in run_dirs:
        for row in csv.DictReader((rd / "task_results.csv").open()):
            stats["tasks"] += 1
            if row["resolved"] not in ("1", "True"):
                continue
            stats["resolved"] += 1
            tid = row["instance_id"]
            if tid in seen:
                stats["duplicate task"] += 1
                continue
            seen.add(tid)
            trace = json.loads((rd / "raw" / "traces" / f"trace_{tid}.json").read_text())
            msgs, removed = repair(to_messages(trace))
            stats["runs repaired"] += bool(removed)
            stats["turns removed"] += removed
            if why := reject_reason(msgs):
                stats[f"dropped: {why}"] += 1
                continue
            repo = row["repo"].split("/")[-1]
            stats[f"kept: {repo}"] += 1
            kept.append(
                {
                    "id": tid,
                    "messages": msgs,
                    "tools": tools,
                    "meta": {
                        "repo": repo,
                        "calls": len(_calls(msgs)),
                        "run": rd.name,
                        "split": "val" if repo == val_repo else "train",
                    },
                }
            )
    stats["kept"] = len(kept)
    return kept, dict(stats)


def main(argv: list[str]) -> int:
    val = ""
    if "--val-repo" in argv:
        i = argv.index("--val-repo")
        val = argv[i + 1]
        argv = argv[:i] + argv[i + 2 :]
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    tools = json.loads(Path(argv[2]).read_text())
    kept, stats = build([Path(p) for p in argv[3:]], tools, val)
    with (out / "train.jsonl").open("w") as fh:
        for r in kept:
            fh.write(json.dumps(r) + "\n")
    (out / "stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
