"""Rank the functions and classes of a repository against an issue text (BM25, stdlib only).

Usage: localize.py [--query TEXT | TEXT...] [--root DIR] [--top 10] [--no-siblings]
The default root is /workspace, or the sandbox's workspace dir above the script's cwd.
--siblings also lists the other definitions of the top hits' files (all output under 3,000 chars).

It parses every library .py file with `ast`, one candidate per function, method or class
(async included, functions nested in functions are not candidates), and ranks them with BM25 over
the dotted name plus the source text. Tests and docs are skipped. Nothing is written to disk.
"""

from __future__ import annotations

import ast
import collections
import math
import os
import re
import sys
import time

SK_NON_LIB = ("tests", "test", "docs_src", "docs", "scripts", "examples")
SK_SKIP_DIRS = frozenset({".git", "__pycache__", "node_modules", "site-packages", "venv", "build"})
SK_MAX_BYTES = 1_000_000
SK_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*|\d+")
SK_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
SK_STOP = frozenset(
    "the a an and or of to in is it this that for on with as be are was not but if at by from "
    "when then so do does did have has had can will would should could i we you my our your "
    "self cls none true false return def class import".split()
)


def sk_tokens(text: str) -> list[str]:
    """Lowercase word pieces; identifiers split on snake and camel case, whole word kept."""
    out: list[str] = []
    for word in SK_WORD.findall(text or ""):
        parts = [p.lower() for p in SK_CAMEL.findall(word)]
        out += [p for p in parts if len(p) > 1 and p not in SK_STOP]
        if len(parts) > 1 and word.lower() not in SK_STOP:
            out.append(word.lower())
    return out


def sk_parts(relpath: str) -> list[str]:
    parts = [p for p in relpath.replace("\\", "/").split("/") if p and p != "."]
    return parts[1:] if len(parts) > 1 and parts[0] == "src" else parts


def sk_module_id(relpath: str) -> str:
    parts = sk_parts(relpath)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def sk_is_library(relpath: str) -> bool:
    parts = sk_parts(relpath)
    if not parts or not parts[-1].endswith(".py"):
        return False
    return parts[0] not in SK_NON_LIB and not parts[0].startswith("test_")


def sk_start(node: ast.AST) -> int:
    return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])


def sk_class_head(node: ast.ClassDef, lines: list[str]) -> str:
    """Header, docstring and the signature of each direct method: the class without its bodies."""
    body = node.body
    first = body[0]
    stop = first.lineno - 1
    if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
        stop = first.end_lineno or first.lineno
    out = lines[sk_start(node) - 1 : stop]
    for ch in body:
        if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out += lines[sk_start(ch) - 1 : ch.body[0].lineno - 1]
    return "\n".join(out)


def sk_defs(source: str, module: str, class_text: str = "head") -> list[dict]:
    """Candidates of one file: {id, kind, line, text}; same-id definitions are merged."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []
    lines = source.splitlines()
    found: dict[str, dict] = {}

    def add(node: ast.AST, qual: str, kind: str, text: str) -> None:
        cid = f"{module}.{qual}" if module else qual
        if cid in found:
            found[cid]["text"] += "\n" + text
        else:
            found[cid] = {"id": cid, "kind": kind, "line": sk_start(node), "text": text}

    def visit(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                text = "\n".join(lines[sk_start(node) - 1 : node.end_lineno])
                add(node, f"{prefix}{node.name}", "function", text)
            elif isinstance(node, ast.ClassDef):
                if class_text == "full":
                    text = "\n".join(lines[sk_start(node) - 1 : node.end_lineno])
                else:
                    text = sk_class_head(node, lines)
                add(node, f"{prefix}{node.name}", "class", text)
                visit(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                for field in ("body", "orelse", "finalbody"):
                    visit(getattr(node, field, []), prefix)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body, prefix)

    visit(tree.body, "")
    return list(found.values())


def sk_index(files: dict[str, str], class_text: str = "head") -> list[dict]:
    """Candidates of every library file in {relative path: source}, in path order."""
    out: list[dict] = []
    for path in sorted(files):
        if not sk_is_library(path):
            continue
        for cand in sk_defs(files[path], sk_module_id(path), class_text):
            cand["path"] = path
            out.append(cand)
    return out


def sk_find_root(cwd: str | None = None) -> str:
    """The repo to index: /workspace, or the `workspace` dir that sits above a script's temp cwd.

    The harness's subprocess sandbox runs skill scripts on the host with no /workspace; the repo is
    <sandbox>/workspace and the script's cwd is <sandbox>/tmp/<random> (measured in GEM-79).
    """
    if os.path.isdir("/workspace"):
        return "/workspace"
    here = os.path.abspath(cwd or os.getcwd())
    for _ in range(5):
        if os.path.isdir(os.path.join(here, "workspace")):
            return os.path.join(here, "workspace")
        here = os.path.dirname(here)
    return "/workspace"


def sk_read_tree(root: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for here, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SK_SKIP_DIRS and not d.startswith("."))
        for name in sorted(names):
            full = os.path.join(here, name)
            rel = os.path.relpath(full, root)
            if not sk_is_library(rel):
                continue
            try:
                if os.path.getsize(full) > SK_MAX_BYTES:
                    continue
                with open(full, encoding="utf-8", errors="replace") as fh:
                    files[rel] = fh.read()
            except OSError:
                continue
    return files


def sk_bm25(docs: list[list[str]], k1: float = 1.5, b: float = 0.75):
    """A scorer for a fixed document set: scorer(query_tokens) -> one score per document."""
    n = len(docs)
    avg = sum(len(d) for d in docs) / max(n, 1)
    df: collections.Counter = collections.Counter()
    for d in docs:
        df.update(set(d))
    tfs = [collections.Counter(d) for d in docs]
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scorer(query: list[str]) -> list[float]:
        q = set(query)
        scores = []
        for tf, d in zip(tfs, docs, strict=True):
            norm = k1 * (1 - b + b * len(d) / max(avg, 1e-9))
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += idf[t] * f * (k1 + 1) / (f + norm)
            scores.append(s)
        return scores

    return scorer


def sk_rank(cands: list[dict], issue: str) -> list[tuple[dict, float]]:
    """Best first; ties break by id so the order is reproducible."""
    docs = [sk_tokens(c["id"].replace(".", " ") + " " + c["text"]) for c in cands]
    scores = sk_bm25(docs)(sk_tokens(issue))
    pairs = list(zip(cands, scores, strict=True))
    return sorted(pairs, key=lambda p: (-p[1], p[0]["id"]))


def sk_format(ranked: list[tuple[dict, float]], top: int) -> str:
    return "\n".join(
        f"{i:2d}. {c['id']}  {c['path']}:{c['line']}" for i, (c, _) in enumerate(ranked[:top], 1)
    )


SK_BUDGET = 3000  # characters of output in all; the agent's context is small


def sk_siblings_of(ranked: list[tuple[dict, float]], hit_id: str, cap: int = 8) -> list[dict]:
    """The other definitions of the hit's file, best BM25 score first, at most `cap`."""
    path = next((c["path"] for c, _ in ranked if c["id"] == hit_id), None)
    if path is None:
        return []
    same = [c for c, _ in ranked if c["path"] == path and c["id"] != hit_id]
    return same[:cap]


def sk_format_siblings(
    ranked: list[tuple[dict, float]], hits: int = 3, cap: int = 8, budget: int = SK_BUDGET
) -> str:
    """Siblings of the top hits, one block per file, cut off at `budget` characters."""
    lines: list[str] = []
    seen: set[str] = set()
    used = 0
    for cand, _ in ranked[:hits]:
        if cand["path"] in seen:
            continue
        seen.add(cand["path"])
        block = [f"{cand['path']} (near {cand['id']}):"]
        block += [f"  {c['id']}  :{c['line']}" for c in sk_siblings_of(ranked, cand["id"], cap)]
        for line in block:
            if used + len(line) + 1 > budget:
                return "\n".join(lines)
            lines.append(line)
            used += len(line) + 1
    return "\n".join(lines)


def sk_main(argv: list[str]) -> int:
    args = argv[1:]
    root, top, siblings, query = sk_find_root(), 10, True, None
    while args and args[0] in ("--root", "--top", "--query", "--siblings", "--no-siblings"):
        if args[0] in ("--siblings", "--no-siblings"):  # siblings are on by default
            siblings = args[0] == "--siblings"
            args = args[1:]
            continue
        if args[0] == "--root":
            root = args[1]
        elif args[0] == "--query":
            query = args[1]
        else:
            top = int(args[1])
        args = args[2:]
    issue = query or (" ".join(args) if args else sys.stdin.read())
    if not issue.strip():
        print(
            "usage: localize.py [--query TEXT] [--root DIR] [--top N] [--no-siblings] [TEXT]",
            file=sys.stderr,
        )
        return 2
    t0 = time.time()
    cands = sk_index(sk_read_tree(root))
    ranked = sk_rank(cands, issue)
    took = time.time() - t0
    head = f"Top {min(top, len(ranked))} of {len(cands)} definitions (BM25), {took:.1f}s\n"
    head += sk_format(ranked, top)
    print(head)
    if siblings:
        title = "Same file as the top hits (other edits may be needed here):\n"
        rest = SK_BUDGET - len(head) - len(title) - 2
        block = sk_format_siblings(ranked, budget=rest)
        if block:
            print("\n" + title + block)
    return 0


if __name__ == "__main__":
    raise SystemExit(sk_main(sys.argv))
