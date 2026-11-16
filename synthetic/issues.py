"""B3 of benchmark v2: model-written issue texts for the mined tasks, with checks.

`requests` turns a tasks.jsonl (from synthetic.mine) into writer prompts: the commit message and
the failing tests' names, never the diff. A hash-chosen share of tasks (`--leak`, 0.2, as in the
public set) may name the changed function or class; for the rest the writer must not. `check`
reports each text's problems; `apply` writes a tasks.jsonl with the texts in. Only synthetic tasks
from public repos go to a writer (rules 4b allow it; real competition tasks never do).
Usage: python -m synthetic.issues requests TASKS OUT.jsonl [--leak 0.2]
       python -m synthetic.issues check TASKS ISSUES.jsonl [--leak 0.2]
       python -m synthetic.issues redo TASKS ISSUES.jsonl OUT.jsonl     requests for flagged texts
       python -m synthetic.issues apply TASKS ISSUES.jsonl OUT_TASKS.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from synthetic.export import names_the_node
from synthetic.tasks import humanize_test

WORDS = (25, 120)  # the public median is 58
HEADER = re.compile(r"^@@[^@]*@@\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.M)
DEFINED = re.compile(r"^[+-]\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.M)
PATH = re.compile(r"\b[\w./-]+\.py\b")
PROMPT = """Write a bug report (30 to 100 words) as a user of a Python library would, from this
change note and the name of a check that failed before the fix.
Change note:
{message}
Check that failed: {phrase}
Rules: plain prose, as a user who hit the problem. Describe what goes wrong and what you expected.
No traceback, no code block, no file names, do not say how to fix it. {naming}
Reply with the bug report only."""


def changed_names(patch: str) -> list[str]:
    """Functions and classes the patch touches, in order, from hunk headers and def/class lines."""
    seen: dict[str, None] = {}
    for m in re.finditer(f"{HEADER.pattern}|{DEFINED.pattern}", patch, re.M):
        name = m.group(1) or m.group(2)
        if not (name.startswith("__") and name.endswith("__")):
            seen.setdefault(name)
    return list(seen)


def may_name(instance_id: str, leak: float) -> bool:
    return names_the_node({"id": instance_id}, leak)


def _flat(s: str) -> str:
    return re.sub(r"[_\s]+", " ", s.lower()).strip()


def names_any(text: str, names: list[str]) -> bool:
    flat = _flat(text)
    return any(
        len(n) >= 4 and re.search(rf"(?<![a-z0-9]){re.escape(_flat(n))}(?![a-z0-9])", flat)
        for n in names
    )


def build_requests(tasks: list[dict], leak: float = 0.2) -> list[dict]:
    out = []
    for t in tasks:
        names = changed_names(t["patch"]) if may_name(t["instance_id"], leak) else []
        phrase = humanize_test(sorted(t["fail_to_pass"])[0]) if t.get("fail_to_pass") else ""
        naming = (
            "You may mention these names the way a user would: " + ", ".join(names) + "."
            if names
            else "Do not name any function, class, module or file."
        )
        prompt = PROMPT.format(message=t["problem_statement"], phrase=phrase, naming=naming)
        out.append({"instance_id": t["instance_id"], "may_name": names, "prompt": prompt})
    return out


def check_text(text: str, names: list[str], allowed: bool) -> list[str]:
    """Problems with one text; `names` are the changed identifiers, `allowed` = may name them."""
    problems = []
    n = len(text.split())
    if n < WORDS[0]:
        problems.append("too short")
    if n > WORDS[1]:
        problems.append("too long")
    if "```" in text or "Traceback" in text:
        problems.append("code block or traceback")
    if PATH.search(text):
        problems.append("names a file")
    hit = names_any(text, names)
    if hit and not allowed:
        problems.append("names the changed code")
    return problems


def redo_requests(tasks: list[dict], issues: dict[str, str], leak: float = 0.2) -> list[dict]:
    """Requests for the texts `check_text` flags, with the names they used banned this time."""
    todo = []
    by_id = {r["instance_id"]: r for r in build_requests(tasks, leak)}
    for t in tasks:
        text = issues.get(t["instance_id"])
        names = changed_names(t["patch"])
        if text is None or not check_text(text, names, may_name(t["instance_id"], leak)):
            continue
        used = [n for n in names if names_any(text, [n])]
        req = dict(by_id[t["instance_id"]])
        if used:
            req["prompt"] += "\nDo not use these words: " + ", ".join(_flat(n) for n in used) + "."
        todo.append(req)
    return todo


def apply_issues(tasks: list[dict], issues: dict[str, str]) -> list[dict]:
    return [
        {**t, "problem_statement": issues.get(t["instance_id"], t["problem_statement"])}
        for t in tasks
    ]


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()
    ]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def main(argv: list[str]) -> int:
    args = argv[1:]
    leak = 0.2
    if "--leak" in args:
        i = args.index("--leak")
        leak = float(args[i + 1])
        del args[i : i + 2]
    if len(args) < 3 or args[0] not in {"requests", "check", "apply", "redo"}:
        print(__doc__)
        return 2
    cmd, tasks = args[0], read_jsonl(Path(args[1]))
    if cmd == "requests":
        write_jsonl(Path(args[2]), build_requests(tasks, leak))
        return 0
    issues = {r["instance_id"]: r["problem_statement"] for r in read_jsonl(Path(args[2]))}
    if cmd == "redo":  # redo TASKS ISSUES OUT.jsonl: rewrite requests for the flagged texts
        write_jsonl(Path(args[3]), redo_requests(tasks, issues, leak))
        return 0
    if cmd == "apply":
        write_jsonl(Path(args[3]), apply_issues(tasks, issues))
        return 0
    return report(tasks, issues, leak)


def report(tasks: list[dict], issues: dict[str, str], leak: float) -> int:
    """Counts only: how many texts are missing, flagged, and how many name the changed code."""
    missing = bad = names_it = 0
    kinds: dict[str, int] = {}
    words = []
    for t in tasks:
        text = issues.get(t["instance_id"])
        if text is None:
            missing += 1
            continue
        names = changed_names(t["patch"])
        allowed = may_name(t["instance_id"], leak)
        words.append(len(text.split()))
        found = check_text(text, names, allowed)
        bad += bool(found)
        for p in found:
            kinds[p] = kinds.get(p, 0) + 1
        names_it += bool(names_any(text, names))
    done = len(tasks) - missing
    words.sort()
    print(
        json.dumps(
            {
                "tasks": len(tasks),
                "missing": missing,
                "flagged": bad,
                "flags": kinds,
                "name_leak_share": round(names_it / done, 3) if done else None,
                "words_median": words[len(words) // 2] if words else None,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
