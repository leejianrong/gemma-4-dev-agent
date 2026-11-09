"""A call-graph builder in the competition's file layout (stdlib only).

Layout (docs/QUESTIONS.md A36): {directed, multigraph, graph: {repo_name}, nodes: [{id, name,
text}], edges: [{key, source, target, type: "calls"}]}. Node ids are dotted (pkg.mod.Class.method)
and follow the same eligibility rule as `synthetic.mutate`: a def has a node when every enclosing
def is a class. The real graphs hold no async functions, so they are left out unless asked for.
Calls are resolved statically and best effort: `f()`, `self.m()`, imported names and aliases,
relative imports and `Class()` instantiation; anything else is dropped.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

from synthetic.mutate import module_name, source_files


def read_tree(root: Path, include_tests: bool = True) -> dict[str, str]:
    """{relative path: source} of the Python files under root (tests included, like real graphs)."""
    root = Path(root)
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8", errors="replace")
        for p in source_files(root, include_tests=include_tests)
    }


def _chain(func: ast.AST) -> list[str] | None:
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
        return parts[::-1]
    return None


def _imports(tree: ast.AST, module: str, is_init: bool) -> dict[str, str]:
    """Local name -> absolute dotted target, for every import statement in the file."""
    pkg = module if is_init else module.rpartition(".")[0]
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    out[a.asname] = a.name
                else:
                    head = a.name.split(".")[0]
                    out[head] = head
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg.split(".") if pkg else []
                up = up[: len(up) - (node.level - 1)] if node.level > 1 else up
                base = ".".join(p for p in (".".join(up), base) if p)
            for a in node.names:
                if a.name != "*":
                    out[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
    return out


def _condensed_class(lines: list[str], node: ast.ClassDef) -> str:
    """Class header, docstring and method signatures; method bodies are dropped."""
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    skip: set[int] = set()
    for ch in ast.walk(node):
        if ch is node or not isinstance(ch, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        body_start = ch.body[0].lineno
        if body_start > ch.lineno:  # a one-line `def f(): ...` keeps its line
            skip.update(range(body_start, ch.end_lineno + 1))
    return "\n".join(lines[i - 1] for i in range(start, node.end_lineno + 1) if i not in skip)


@functools.lru_cache(maxsize=4096)
def _file_nodes(source: str, module: str, is_init: bool, include_async: bool):
    """(nodes, imports) of one file; nodes carry their raw call chains. Cached by content."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return (), {}
    lines = source.splitlines()
    out: list[dict] = []

    def visit(body: list[ast.stmt], prefix: str, in_class: bool) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                is_async = isinstance(node, ast.AsyncFunctionDef)
                qual = f"{prefix}{node.name}"
                if isinstance(node, ast.ClassDef):
                    out.append(
                        {
                            "id": f"{module}.{qual}",
                            "name": node.name,
                            "text": _condensed_class(lines, node),
                            "calls": [],
                            "cls": "",
                        }
                    )
                    visit(node.body, f"{qual}.", True)
                elif include_async or not is_async:
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                    calls = [
                        c
                        for n in ast.walk(node)
                        if isinstance(n, ast.Call) and (c := _chain(n.func)) is not None
                    ]
                    out.append(
                        {
                            "id": f"{module}.{qual}",
                            "name": node.name,
                            "text": "\n".join(lines[start - 1 : node.end_lineno]),
                            "calls": calls,
                            "cls": prefix.rstrip(".") if in_class else "",
                        }
                    )
            elif isinstance(node, ast.If | ast.Try | ast.With):
                for field in ("body", "orelse", "finalbody"):
                    visit(getattr(node, field, []), prefix, in_class)
                for handler in getattr(node, "handlers", []):
                    visit(handler.body, prefix, in_class)

    visit(tree.body, "", False)
    return tuple(out), _imports(tree, module, is_init)


def _resolve(chain: list[str], module: str, cls: str, imports: dict[str, str], ids: set[str]):
    head, rest = chain[0], chain[1:]
    cands: list[str] = []
    if not rest:
        cands += [f"{module}.{head}", imports.get(head, "")]
    elif head in ("self", "cls") and cls and len(rest) == 1:
        cands.append(f"{module}.{cls}.{rest[0]}")
    else:
        tail = ".".join(rest)
        cands.append(f"{module}.{head}.{tail}")
        if head in imports:
            cands.append(f"{imports[head]}.{tail}")
    return next((c for c in cands if c and c in ids), None)


def graph_nodes(files: dict[str, str], include_async: bool = False) -> list[dict]:
    """Just the nodes {id, name, text} of build_graph, without resolving calls."""
    out: dict[str, dict] = {}
    for path in sorted(files):
        module, is_init = module_name(path), path.endswith("__init__.py")
        nodes, _ = _file_nodes(files[path], module, is_init, include_async)
        for n in nodes:  # ids are unique in a graph: the first definition wins
            out.setdefault(n["id"], {"id": n["id"], "name": n["name"], "text": n["text"]})
    return list(out.values())


def build_graph(files: dict[str, str], repo_name: str, include_async: bool = False) -> dict:
    """The graph of {relative path: source}; deterministic whatever the order of `files`."""
    per_file = []
    for path in sorted(files):
        module = module_name(path)
        is_init = path.endswith("__init__.py")
        nodes, imports = _file_nodes(files[path], module, is_init, include_async)
        per_file.append((module, nodes, imports))
    ids = {n["id"] for _, nodes, _ in per_file for n in nodes}
    nodes_out, edges = [], []
    seen: set[tuple[str, str]] = set()
    placed: set[str] = set()
    for module, nodes, imports in per_file:
        for n in nodes:
            if n["id"] in placed:  # a def repeated under if/else: keep the first
                continue
            placed.add(n["id"])
            nodes_out.append({"id": n["id"], "name": n["name"], "text": n["text"]})
            for chain in n["calls"]:
                target = _resolve(chain, module, n["cls"], imports, ids)
                if target and target != n["id"] and (n["id"], target) not in seen:
                    seen.add((n["id"], target))
                    edges.append({"key": 0, "source": n["id"], "target": target, "type": "calls"})
    return {
        "directed": True,
        "multigraph": True,
        "graph": {"repo_name": repo_name},
        "nodes": nodes_out,
        "edges": edges,
    }
