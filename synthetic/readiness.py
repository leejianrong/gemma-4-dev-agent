"""Static check: could a repo's tests run in the offline competition sandbox? (GEM-87)

We never run repo code. For each repo we parse the test files with `ast` and list the third-party
modules they import, the plugin fixtures and markers they use, and the Python version the repo
needs. A repo is admitted only if its tests import nothing beyond the standard library, pytest, the
repo's own package and the repo's declared runtime dependencies, and show no network fixture or
missing-plugin sign.

What we could not determine: which packages the competition image has installed. The harness
streams per-repo cached site-packages into the sandbox (data/HARNESS_README.md, section 5.2), but
the list is not published. So "declared runtime dependency" is an assumption that the image has
whatever the repo needs to import, and any test-only dependency counts as missing.
Usage: python -m synthetic.readiness CACHE_DIR [--manifest M] [--update-manifest]
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

from synthetic.fetch import MANIFEST, load_manifest

SANDBOX_PYTHON = (3, 13)
STDLIB = set(sys.stdlib_module_names)
ALWAYS_OK = {"pytest", "_pytest"}
# Import names whose distribution name differs.
DIST_OF_MODULE = {"yaml": "pyyaml", "attr": "attrs", "dateutil": "python_dateutil", "PIL": "pillow"}
PLUGIN_FIXTURES = {
    "mocker": "pytest-mock",
    "httpbin": "pytest-httpbin (network fixture)",
    "httpbin_secure": "pytest-httpbin (network fixture)",
    "httpserver": "pytest-httpserver",
    "benchmark": "pytest-benchmark",
    "freezer": "pytest-freezegun",
    "snapshot": "a snapshot plugin",
    "event_loop": "pytest-asyncio",
    "aiohttp_client": "pytest-aiohttp",
}
PLUGIN_MARKERS = {"asyncio": "pytest-asyncio", "anyio": "anyio", "trio": "pytest-trio"}
NETWORK = re.compile(r"pytest\.mark\.network|\burlopen\(|socket\.create_connection\(")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def _py_files(root: Path):
    return sorted(p for p in root.rglob("*.py") if p.is_file())


def _collected(path: Path) -> bool:
    """Files pytest imports by default, or that every test run imports (conftest)."""
    n = path.name
    return n == "conftest.py" or n.startswith("test_") or n.endswith("_test.py")


def _guarded_imports(tree) -> set[int]:
    """ids of import nodes inside `try: ... except ImportError` (optional imports)."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        names = {ast.unparse(h.type) for h in node.handlers if h.type is not None}
        if any(n in names for n in ("ImportError", "ModuleNotFoundError")) or any(
            h.type is None for h in node.handlers
        ):
            for sub in node.body:
                skip.update(
                    id(x) for x in ast.walk(sub) if isinstance(x, (ast.Import, ast.ImportFrom))
                )
    return skip


def _parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None


def third_party_imports(
    tests_dir: Path, own: set[str], extra_local: set[str] | frozenset = frozenset()
) -> set[str]:
    """Top-level modules imported by test files that are not stdlib, own, or test-local.

    Test-local means a module or directory inside the tests dir, the tests dir itself, or (via
    `extra_local`) a top-level name in the repo root, which pytest puts on sys.path.
    """
    local = {p.stem for p in _py_files(tests_dir)} | {
        p.name for p in tests_dir.rglob("*") if p.is_dir()
    }
    local |= {tests_dir.name} | set(extra_local)
    found = set()
    for path in _py_files(tests_dir):
        tree = _parse(path)
        if tree is None or not _collected(path):
            continue
        guarded = _guarded_imports(tree)
        for node in ast.walk(tree):
            if id(node) in guarded:
                continue
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for n in names:
                top = n.split(".")[0]
                if top not in STDLIB and top not in own and top not in local:
                    found.add(top)
    return found


def _declared(repo: Path) -> set[str]:
    pp = repo / "pyproject.toml"
    if not pp.is_file():
        return set()
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return set()
    deps = data.get("project", {}).get("dependencies", [])
    return {norm(re.split(r"[\s<>=!~;\[(]", d, maxsplit=1)[0]) for d in deps}


def _requires_python(repo: Path) -> tuple[int, int] | None:
    pp = repo / "pyproject.toml"
    if not pp.is_file():
        return None
    try:
        spec = (
            tomllib.loads(pp.read_text(encoding="utf-8"))
            .get("project", {})
            .get("requires-python", "")
        )
    except tomllib.TOMLDecodeError:
        return None
    m = re.search(r">=\s*(\d+)\.(\d+)", spec)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _fixtures_and_markers(tests_dir: Path) -> tuple[set[str], set[str], set[str], str]:
    """Fixture names used, fixture names the tests define themselves, markers used, all text."""
    used, defined, markers, text = set(), set(), set(), []
    for path in _py_files(tests_dir):
        src = path.read_text(encoding="utf-8", errors="replace")
        text.append(src)
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any("fixture" in ast.unparse(d) for d in node.decorator_list):
                    defined.add(node.name)
                used.update(a.arg for a in node.args.args + node.args.kwonlyargs)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
                if node.value.attr == "mark" and isinstance(node.value.value, ast.Name):
                    markers.add(node.attr)
    return used, defined, markers, "\n".join(text)


def check_repo(name: str, repo: Path, modules: str | list[str], tests_rel: str | None) -> dict:
    own = {modules} if isinstance(modules, str) else set(modules)
    reasons: list[str] = []
    third: set[str] = set()
    req = _requires_python(repo)
    if req and req > SANDBOX_PYTHON:
        reasons.append(
            f"needs Python >= {req[0]}.{req[1]}, sandbox has "
            f"{SANDBOX_PYTHON[0]}.{SANDBOX_PYTHON[1]}"
        )
    if not tests_rel or not (repo / tests_rel).is_dir():
        reasons.append("no tests directory found")
    else:
        tests = repo / tests_rel
        root = {p.name for p in repo.iterdir() if p.is_dir()} | {p.stem for p in repo.glob("*.py")}
        third = third_party_imports(tests, own, root)
        declared = _declared(repo)
        missing = sorted(
            m
            for m in third - ALWAYS_OK
            if norm(m) not in declared and norm(DIST_OF_MODULE.get(m, m)) not in declared
        )
        if missing:
            reasons.append(
                "test imports not in the repo's runtime dependencies: " + ", ".join(missing)
            )
        used, defined, markers, text = _fixtures_and_markers(tests)
        for fx in sorted((used & set(PLUGIN_FIXTURES)) - defined):
            reasons.append(f"fixture `{fx}` needs {PLUGIN_FIXTURES[fx]}")
        for mk in sorted(markers & set(PLUGIN_MARKERS)):
            reasons.append(f"marker `{mk}` needs {PLUGIN_MARKERS[mk]}")
        if NETWORK.search(text):
            reasons.append("tests use network calls or a network marker")
    return {"name": name, "admit": not reasons, "reasons": reasons, "third_party": sorted(third)}


def detect_license(text: str) -> str:
    if "Apache License" in text and "Version 2.0" in text:
        return "Apache-2.0"
    if "Permission is hereby granted, free of charge" in text:
        return "MIT"
    if "Redistribution and use in source and binary forms" in text:
        return "BSD-3-Clause" if "Neither the name" in text else "BSD-2-Clause"
    return "UNKNOWN"


def find_package_dir(repo: Path, module: str) -> str | None:
    for rel in (module, f"src/{module}", f"lib/{module}"):
        if (repo / rel / "__init__.py").is_file():
            return rel
    return None


def find_tests_dir(repo: Path, package_dir: str | None = None) -> str | None:
    for rel in ("tests", "test", f"{package_dir}/tests" if package_dir else ""):
        if rel and (repo / rel).is_dir():
            return rel
    return None


def render_table(rows: list[dict]) -> str:
    out = ["| repo | verdict | reasons |", "|---|---|---|"]
    for r in rows:
        out.append(
            f"| {r['name']} | {'admit' if r['admit'] else 'reject'} | {'; '.join(r['reasons'])} |"
        )
    return "\n".join(out)


def licence_of(repo: Path) -> str:
    for name in (
        "LICENSE",
        "LICENSE.txt",
        "LICENSE.md",
        "LICENSE.rst",
        "LICENCE",
        "LICENCE.txt",
        "COPYING",
    ):
        if (repo / name).is_file():
            return detect_license((repo / name).read_text(encoding="utf-8", errors="replace"))
    return "UNKNOWN"


def main(argv: list[str]) -> int:
    args = argv[1:]
    manifest, update = MANIFEST, "--update-manifest" in args
    args = [a for a in args if a != "--update-manifest"]
    if "--manifest" in args:
        i = args.index("--manifest")
        manifest = Path(args[i + 1])
        del args[i : i + 2]
    if not args:
        print(__doc__)
        return 2
    cache = Path(args[0])
    entries, rows = load_manifest(manifest), []
    for e in entries:
        repo = cache / e["name"]
        mods = e.get("modules") or [e["name"].replace("-", "_")]
        pkg = next((p for m in mods if (p := find_package_dir(repo, m))), None)
        tests = find_tests_dir(repo, pkg)
        e.update(
            {"modules": mods, "license": licence_of(repo), "package_dir": pkg, "tests_dir": tests}
        )
        rows.append(check_repo(e["name"], repo, mods, tests))
    print(render_table(rows))
    if update:
        Path(manifest).write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
