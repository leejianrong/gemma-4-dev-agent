"""Whitespace-tolerant block edit for small models (arm A12).

Replaces a block of lines in one source file and checks the result still parses. Two modes:
  --file F --old TEXT --new TEXT   find the lines of TEXT ignoring indentation and runs of spaces
  --file F --start N --end M --new TEXT   replace lines N..M (1-based)
The new text is re-indented to the block it replaces. Python files must still parse, else the
edit is undone. Test files are refused. Writes only inside the repo (/workspace, or the sandbox's
workspace dir).
"""

from __future__ import annotations

import ast
import difflib
import os
import re
import sys


def ed_root(cwd: str | None = None) -> str:
    if os.path.isdir("/workspace"):
        return "/workspace"
    here = os.path.abspath(cwd or os.getcwd())
    for _ in range(5):
        if os.path.isdir(os.path.join(here, "workspace")):
            return os.path.join(here, "workspace")
        here = os.path.dirname(here)
    return "/workspace"


def ed_norm(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def ed_is_test(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    name = parts[-1]
    return (
        "tests" in parts[:-1]
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name in ("conftest.py", "pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
    )


def ed_find(lines: list[str], old: list[str]) -> list[int]:
    """Start indexes where `old` matches `lines` ignoring whitespace (blank edges dropped)."""
    want = [ed_norm(x) for x in old]
    while want and not want[0]:
        want.pop(0)
    while want and not want[-1]:
        want.pop()
    if not want:
        return []
    have = [ed_norm(x) for x in lines]
    return [i for i in range(len(have) - len(want) + 1) if have[i : i + len(want)] == want]


def ed_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def ed_reindent(new: list[str], target: str) -> list[str]:
    """Shift `new` so its first non-blank line starts at `target` (the replaced block's indent)."""
    first = next((x for x in new if x.strip()), None)
    if first is None:
        return new
    cur = ed_indent(first)
    out = []
    for x in new:
        if not x.strip():
            out.append("")
        elif x.startswith(cur):
            out.append(target + x[len(cur) :])
        else:
            out.append(target + x.lstrip())
    return out


def ed_hint(lines: list[str], old: list[str]) -> str:
    probe = next((ed_norm(x) for x in old if x.strip()), "")
    best, at = 0.0, 0
    for i, x in enumerate(lines):
        r = difflib.SequenceMatcher(None, probe, ed_norm(x)).ratio()
        if r > best:
            best, at = r, i
    if best < 0.5:
        return "No line looks like the first line of old; re-read the file with sed -n."
    lo, hi = max(0, at - 2), min(len(lines), at + 6)
    shown = "\n".join(f"{n + 1:5d}  {lines[n]}" for n in range(lo, hi))
    return f"Closest line to the first line of old is {at + 1}. Lines {lo + 1}-{hi}:\n{shown}"


def ed_apply(
    text: str, new: str, old: str | None = None, start: int | None = None, end: int | None = None
) -> tuple[str | None, str, int, int]:
    """Return (new file text or None, message, first line, last line) with 1-based line numbers."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(nl)
    trailing = lines[-1] == ""
    if trailing:
        lines = lines[:-1]
    new_lines = new.replace("\r\n", "\n").split("\n")
    if old is not None:
        old_lines = old.replace("\r\n", "\n").split("\n")
        hits = ed_find(lines, old_lines)
        if not hits:
            return None, "old not found. " + ed_hint(lines, old_lines), 0, 0
        if len(hits) > 1:
            where = ", ".join(str(h + 1) for h in hits[:6])
            return (
                None,
                f"old matches {len(hits)} places (lines {where}). "
                "Add a line above or below, or use --start/--end.",
                0,
                0,
            )
        while old_lines and not old_lines[0].strip():
            old_lines.pop(0)
        while old_lines and not old_lines[-1].strip():
            old_lines.pop()
        a = hits[0]
        b = a + len(old_lines)
    else:
        if start is None or end is None or not 1 <= start <= end <= len(lines):
            return None, f"--start/--end must satisfy 1 <= start <= end <= {len(lines)}.", 0, 0
        a, b = start - 1, end
    body = ed_reindent(new_lines, ed_indent(lines[a]))
    if body and not body[-1].strip() and len(body) > 1:
        body = body[:-1]
    out = lines[:a] + body + lines[b:]
    res = nl.join(out) + (nl if trailing else "")
    return res, "ok", a + 1, a + len(body)


def ed_region(text: str, first: int, last: int, pad: int = 3) -> str:
    lines = text.split("\n")
    lo, hi = max(1, first - pad), min(len(lines), max(last, first) + pad)
    return "\n".join(f"{n:5d}  {lines[n - 1]}" for n in range(lo, hi + 1))


def ed_main(argv: list[str]) -> int:
    opts: dict[str, str] = {}
    i = 1
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv):
            opts[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    path, new = opts.get("file"), opts.get("new")
    if not path or new is None or ("old" not in opts and "start" not in opts):
        print(
            "usage: edit.py --file PATH --new TEXT (--old TEXT | --start N --end M)",
            file=sys.stderr,
        )
        return 2
    root = opts.get("root") or ed_root()
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(os.path.realpath(root) + os.sep):
        print("refused: the file is outside the repository")
        return 1
    rel = os.path.relpath(full, os.path.realpath(root))
    if ed_is_test(rel):
        print("refused: test and runner files are discarded by the grader; edit library code")
        return 1
    if not os.path.isfile(full):
        print(f"no such file: {rel}")
        return 1
    with open(full, encoding="utf-8", newline="") as f:
        text = f.read()
    try:
        start = int(opts["start"]) if "start" in opts else None
        end = int(opts.get("end", opts.get("start", ""))) if "start" in opts else None
    except ValueError:
        print("--start and --end must be integers")
        return 1
    res, msg, first, last = ed_apply(text, new, opts.get("old"), start, end)
    if res is None:
        print("NOT EDITED: " + msg)
        return 1
    if res == text:
        print("NOT EDITED: the new text equals the old text")
        return 1
    if full.endswith(".py"):
        try:
            ast.parse(res)
        except SyntaxError as e:
            print(
                f"NOT EDITED: the result would not parse (line {e.lineno}: {e.msg}). "
                "The file is unchanged."
            )
            return 1
    with open(full, "w", encoding="utf-8", newline="") as f:
        f.write(res)
    print(f"edited {rel}, now lines {first}-{last}:")
    print(ed_region(res.replace("\r\n", "\n"), first, last))
    return 0


if __name__ == "__main__":
    raise SystemExit(ed_main(sys.argv))
