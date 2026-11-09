"""Stage 1 of the synthetic task set (docs/SYNTHETIC_DATASET.md): inject one bug into a Python tree.

Pure stdlib. For a source tree it lists graph-style nodes (dotted ids), applies ONE mutation
operator at a time with a text edit on the original source (no `ast.unparse`, so a mutant differs
from the original in one or two lines), and emits a record per mutant: the file, the gold node, the
operator, the mutated file text and the reverse patch. That patch is the gold patch for the task;
the mutated tree is the base.

The gold node is the innermost def or class that contains the mutated line, the same rule as
`pod/gold_map.py` (A24). A nested function has no graph node, so it falls back to its parent.

Usage: python -m synthetic.mutate SRC_DIR OUT.jsonl --n 50 --seed 0
SRC_DIR is the import root: the directory that holds the top-level package.
"""

from __future__ import annotations

import argparse
import ast
import collections
import difflib
import json
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER = "PLACEHOLDER"
OPERATORS = ("cmp_swap", "bool_swap", "const_off_by_one", "drop_guard", "swap_args", "wrong_return")
SKIP_DIRS = {"tests", "test", "testing", "docs", "doc", "examples", "benchmarks", "build"}
CMP_SWAP = {
    ast.Eq: "!=",
    ast.NotEq: "==",
    ast.Lt: "<=",
    ast.LtE: "<",
    ast.Gt: ">=",
    ast.GtE: ">",
    ast.Is: "is not",
    ast.IsNot: "is",
    ast.In: "not in",
    ast.NotIn: "in",
}
CMP_TOKEN = re.compile(rb"is\s+not\b|not\s+in\b|\bis\b|\bin\b|==|!=|<=|>=|<|>")
BOOL_TOKEN = re.compile(rb"\b(and|or)\b")
GUARD_BODIES = (ast.Return, ast.Raise, ast.Continue, ast.Break)


@dataclass(frozen=True)
class Def:
    start: int  # first line, decorators included
    end: int
    col: int
    qual: str
    kind: str  # function_like or class_like
    is_async: bool


@dataclass(frozen=True)
class Candidate:
    operator: str
    line: int  # 1-based line of the first edit
    offset: int  # byte offset of the first edit
    edits: tuple[tuple[int, int, bytes], ...]  # (start, end, replacement), byte offsets
    qual: str  # innermost def containing the edit
    path: str
    module: str


def source_files(root: Path, include_tests: bool = False) -> list[Path]:
    """Python files under root, sorted; tests, docs, examples and setup files are skipped."""
    out = []
    for p in sorted(Path(root).rglob("*.py")):
        rel = p.relative_to(root)
        if not include_tests:
            if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
                continue
            name = rel.name
            if name.startswith("test_") or name.endswith("_test.py"):
                continue
            if name in {"conftest.py", "setup.py"}:
                continue
        out.append(p)
    return out


def module_name(rel_path: str) -> str:
    parts = rel_path.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def collect_defs(tree: ast.AST) -> list[Def]:
    """Every def and class, nested ones too (the shape of pod.gold_map.gm_defs)."""
    out: list[Def] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                q = f"{prefix}.{ch.name}" if prefix else ch.name
                start = min([ch.lineno] + [d.lineno for d in ch.decorator_list])
                kind = "class_like" if isinstance(ch, ast.ClassDef) else "function_like"
                is_async = isinstance(ch, ast.AsyncFunctionDef)
                out.append(Def(start, ch.end_lineno or ch.lineno, ch.col_offset, q, kind, is_async))
                visit(ch, q)
            else:
                visit(ch, prefix)

    visit(tree, "")
    return out


def innermost(defs: list[Def], line: int) -> Def | None:
    """Deepest def containing `line` (pod.gold_map.gm_innermost without the indent option)."""
    best = None
    for d in defs:
        if d.start <= line <= d.end and (best is None or d.start >= best.start):
            best = d
    return best


def graph_eligible(qual: str, kinds: dict[str, str]) -> bool:
    """A def has a graph node when every enclosing def is a class: functions, classes, methods.

    A function nested in a function has no node. A24 found this by lookup in the graph; here the
    graph is not available, so the rule is structural.
    """
    parts = qual.split(".")
    return all(kinds.get(".".join(parts[:i])) == "class_like" for i in range(1, len(parts)))


def resolve_node(qual: str, kinds: dict[str, str]) -> tuple[str, bool]:
    """Walk up from a nested def to the nearest qualname with a node: (qualname, fell_back)."""
    q, fell = qual, False
    while "." in q and not graph_eligible(q, kinds):
        q, fell = q.rpartition(".")[0], True
    return q, fell


def list_nodes_in_source(source: str, module: str, include_async: bool = True) -> list[dict]:
    """Graph-style nodes of one file: dotted ids like pkg.module.Class.method."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []
    out = []
    defs = collect_defs(tree)
    kinds = {d.qual: d.kind for d in defs}
    for d in defs:
        if not graph_eligible(d.qual, kinds) or (d.is_async and not include_async):
            continue
        out.append(
            {
                "id": f"{module}.{d.qual}",
                "kind": d.kind,
                "qual": d.qual,
                "start": d.start,
                "end": d.end,
                "is_async": d.is_async,
            }
        )
    return out


def _line_offsets(src: bytes) -> list[int]:
    offs, pos = [], 0
    for ln in src.splitlines(keepends=True):
        offs.append(pos)
        pos += len(ln)
    return offs


def find_candidates(
    source: str, path: str, module: str, include_async: bool = True
) -> list[Candidate]:
    """Every place one operator can be applied, in source order. [] for an unparsable file."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return []
    src = source.encode("utf-8")
    offs = _line_offsets(src)

    def off(line: int, col: int) -> int:
        return offs[line - 1] + col

    def span(n: ast.AST) -> tuple[int, int]:
        return off(n.lineno, n.col_offset), off(n.end_lineno, n.end_col_offset)

    def one_line(*nodes: ast.AST) -> bool:
        return all(n.lineno == n.end_lineno for n in nodes)

    found: list[Candidate] = []

    def add(op: str, edits: list[tuple[int, int, bytes]], d: Def) -> None:
        edits = sorted(edits)
        found.append(
            Candidate(
                op,
                src.count(b"\n", 0, edits[0][0]) + 1,
                edits[0][0],
                tuple(edits),
                d.qual,
                path,
                module,
            )
        )

    def between(a: ast.AST, b: ast.AST, rx: re.Pattern, repl: bytes, op: str, d: Def) -> None:
        if a.end_lineno != b.lineno:
            return
        lo, hi = span(a)[1], span(b)[0]
        hit = rx.search(src, lo, hi)
        if hit:
            add(op, [(hit.start(), hit.end(), repl)], d)

    def emit(node: ast.AST, d: Def) -> None:
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in CMP_SWAP:
            repl = CMP_SWAP[type(node.ops[0])].encode()
            between(node.left, node.comparators[0], CMP_TOKEN, repl, "cmp_swap", d)
        elif isinstance(node, ast.BoolOp) and len(node.values) >= 2:
            flip = b"or" if isinstance(node.op, ast.And) else b"and"
            between(node.values[0], node.values[1], BOOL_TOKEN, flip, "bool_swap", d)
        elif (
            isinstance(node, ast.Constant)
            and type(node.value) is int
            and abs(node.value) < 10**6
            and one_line(node)
        ):
            s, e = span(node)
            if re.fullmatch(rb"\d+", src[s:e]):
                new = node.value + (1 if (node.lineno + node.col_offset) % 2 == 0 else -1)
                add("const_off_by_one", [(s, e, str(new).encode())], d)
        elif (
            isinstance(node, ast.If)
            and not node.orelse
            and len(node.body) == 1
            and isinstance(node.body[0], GUARD_BODIES)
            and not isinstance(node.test, ast.Constant)
            and one_line(node.test)
        ):
            s, e = span(node.test)
            add("drop_guard", [(s, e, b"False")], d)
        elif (
            isinstance(node, ast.Call)
            and len(node.args) >= 2
            and not any(isinstance(a, ast.Starred) for a in node.args[:2])
            and one_line(node.args[0], node.args[1])
        ):
            (s0, e0), (s1, e1) = span(node.args[0]), span(node.args[1])
            t0, t1 = src[s0:e0], src[s1:e1]
            if t0 != t1:
                add("swap_args", [(s0, e0, t1), (s1, e1, t0)], d)
        elif isinstance(node, ast.Return) and node.value is not None and one_line(node.value):
            v = node.value
            s, e = span(v)
            if isinstance(v, ast.Constant) and isinstance(v.value, bool):
                add("wrong_return", [(s, e, b"False" if v.value else b"True")], d)
            elif not isinstance(v, ast.Constant):
                add("wrong_return", [(s, e, b"None")], d)

    def visit(node: ast.AST, stack: list[tuple[Def, str]]) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            prefix = stack[-1][1] + "." if stack else ""
            q = prefix + node.name
            start = min([node.lineno] + [x.lineno for x in node.decorator_list])
            kind = "class_like" if isinstance(node, ast.ClassDef) else "function_like"
            d = Def(start, node.end_lineno or node.lineno, node.col_offset, q, kind,
                    isinstance(node, ast.AsyncFunctionDef))  # fmt: skip
            inner = [*stack, (d, q)]
            for stmt in node.body:  # decorators, defaults and annotations are not mutated
                visit(stmt, inner)
            return
        if isinstance(node, ast.JoinedStr):
            return
        if stack and stack[-1][0].kind == "function_like":
            if include_async or not any(x.is_async for x, _ in stack):
                emit(node, stack[-1][0])
        for ch in ast.iter_child_nodes(node):
            visit(ch, stack)

    for stmt in tree.body:
        visit(stmt, [])
    return found


def apply_candidate(source: str, cand: Candidate) -> str:
    """The source with the candidate's edits applied (byte offsets, so non-ASCII text is safe)."""
    src = source.encode("utf-8")
    for s, e, new in sorted(cand.edits, reverse=True):
        src = src[:s] + new + src[e:]
    return src.decode("utf-8")


def reverse_patch(original: str, mutated: str, path: str) -> str:
    """A git-style patch that turns the mutated file back into the original (the gold patch)."""
    diff = difflib.unified_diff(
        mutated.splitlines(keepends=True),
        original.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    body = []
    for line in diff:
        body.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return f"diff --git a/{path} b/{path}\n" + "".join(body)


def is_valid_mutant(original_tree_dump: str, mutated: str, original: str) -> bool:
    """It must parse and be a real change of the program, not only of the text."""
    if mutated == original:
        return False
    try:
        return ast.dump(ast.parse(mutated)) != original_tree_dump
    except (SyntaxError, ValueError, RecursionError):
        return False


def mutations_for_source(
    source: str,
    path: str,
    module: str,
    include_async: bool = True,
    repo: str = "repo",
    commit: str = PLACEHOLDER,
) -> list[dict]:
    """One record per valid mutant of one file, in source order."""
    cands = find_candidates(source, path, module, include_async)
    if not cands:
        return []
    defs = collect_defs(ast.parse(source))
    dump = ast.dump(ast.parse(source))
    return [r for c in cands if (r := _record(source, dump, defs, c, repo, commit)) is not None]


def _record(source, dump, defs, cand: Candidate, repo: str, commit: str) -> dict | None:
    mutated = apply_candidate(source, cand)
    if not is_valid_mutant(dump, mutated, source):
        return None
    d = innermost(defs, cand.line)
    kinds = {x.qual: x.kind for x in defs}
    qual, fell = resolve_node(d.qual, kinds)
    kind = kinds[qual]
    return {
        "id": f"{repo}__{cand.module}__{cand.offset}__{cand.operator}",
        "repo": repo,
        "commit": commit,
        "file": cand.path,
        "module": cand.module,
        "operator": cand.operator,
        "line": cand.line,
        "innermost": d.qual,
        "gold_node": f"{cand.module}.{qual}",
        "gold_kind": kind,
        "fell_back": fell,
        "mutated_text": mutated,
        "gold_patch": reverse_patch(source, mutated, cand.path),
    }


def _tree_candidates(root: Path, include_async: bool, include_tests: bool):
    for p in source_files(root, include_tests):
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")
        mod = module_name(rel)
        for c in find_candidates(text, rel, mod, include_async):
            yield text, c


def count_candidates(root: Path, include_async: bool = True, include_tests: bool = False) -> int:
    return sum(1 for _ in _tree_candidates(Path(root), include_async, include_tests))


def generate(
    root: Path,
    n: int = 0,
    seed: int = 0,
    include_async: bool = True,
    include_tests: bool = False,
    repo: str | None = None,
    commit: str = PLACEHOLDER,
) -> list[dict]:
    """Up to n valid mutants drawn at random (seeded) from the whole tree; n=0 means all."""
    root = Path(root)
    repo = repo or root.resolve().name
    items = list(_tree_candidates(root, include_async, include_tests))
    random.Random(seed).shuffle(items)
    caches: dict[str, tuple] = {}
    out: list[dict] = []
    for text, c in items:
        if n and len(out) >= n:
            break
        if c.path not in caches:
            tree = ast.parse(text)
            caches[c.path] = (ast.dump(tree), collect_defs(tree))
        dump, defs = caches[c.path]
        r = _record(text, dump, defs, c, repo, commit)
        if r is not None:
            out.append(r)
    return out


def summarize(records: list[dict]) -> dict:
    """Counts of operators, files and how the gold nodes resolve."""
    return {
        "mutants": len(records),
        "by_operator": dict(collections.Counter(r["operator"] for r in records)),
        "by_file": dict(collections.Counter(r["file"] for r in records)),
        "gold_direct": sum(not r["fell_back"] for r in records),
        "gold_via_parent": sum(r["fell_back"] for r in records),
        "gold_kind": dict(collections.Counter(r["gold_kind"] for r in records)),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m synthetic.mutate", description=__doc__)
    ap.add_argument("src", type=Path, help="import root of the library")
    ap.add_argument("out", type=Path, help="JSONL file to write")
    ap.add_argument("--n", type=int, default=50, help="mutants to draw; 0 means all")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--repo", default=None, help="repo name in the records (default: SRC name)")
    ap.add_argument("--commit", default=PLACEHOLDER, help="commit SHA the tree is pinned to")
    ap.add_argument("--no-async", action="store_true", help="skip async functions (A27 setting)")
    ap.add_argument("--include-tests", action="store_true")
    a = ap.parse_args(argv)
    recs = generate(a.src, a.n, a.seed, not a.no_async, a.include_tests, a.repo, a.commit)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
    print(json.dumps(summarize(recs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
