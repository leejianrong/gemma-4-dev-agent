"""Local pre-flight and packaging for submission/.

Mirrors the limits documented in HARNESS_README.md. It is NOT a substitute for
`adk_submission.validate_directory`, which only exists on Kaggle; run that in the
notebook before every real submission.
"""

from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path

ALLOWED_EXT = {".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"}
ALLOWED_MODELS = {
    "gemma-4-31b-it-qat-w4a16-ct",
    "gemma-4-12b-it-qat-w4a16-ct",
    "gemma-4-e4b-it-qat-w4a16-ct",
    "gemma-4-e2b-it-qat-w4a16-ct",
}
MAX_BYTES = 3 * 2**30
ROOT_NAMES = ("agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml")
ADAPTER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
MODEL_RE = re.compile(r"^\s*model:\s*['\"]?([^\s'\"#]+)", re.MULTILINE)
INCLUDE_RE = re.compile(r"!include\s+(\S+)")


def _normalize_model(name: str) -> str:
    return name.split("/")[-1]


def check(root: Path) -> list[str]:
    """Return a list of problems; empty means the directory looks valid."""
    if not root.is_dir():
        return [f"{root} is not a directory"]

    errs: list[str] = []
    roots = [n for n in ROOT_NAMES if (root / n).is_file()]
    if len(roots) != 1:
        errs.append(f"expected exactly one root config, found {roots or 'none'}")

    total = 0
    models: set[str] = set()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_symlink():
            errs.append(f"symlink not allowed: {rel}")
            continue
        if not p.is_file():
            continue
        total += p.stat().st_size
        if p.suffix.lower() not in ALLOWED_EXT:
            errs.append(f"extension not allowed: {rel}")
        if p.suffix.lower() in {".yaml", ".yml"}:
            text = p.read_text(encoding="utf-8")
            models.update(_normalize_model(m) for m in MODEL_RE.findall(text))
            for inc in INCLUDE_RE.findall(text):
                if inc.startswith("/") or ".." in Path(inc).parts:
                    errs.append(f"unsafe !include {inc!r} in {rel}")
                elif not (p.parent / inc).exists():
                    errs.append(f"!include target missing: {inc!r} in {rel}")

    if total > MAX_BYTES:
        errs.append(f"unpacked size {total} exceeds 3 GiB limit")
    if len(models) != 1:
        errs.append(f"expected exactly one declared model, found {sorted(models) or 'none'}")
    elif not models <= ALLOWED_MODELS:
        errs.append(f"model not allowed: {sorted(models - ALLOWED_MODELS)}")

    adapters = root / "adapters"
    if adapters.is_dir():
        for d in sorted(x for x in adapters.iterdir() if x.is_dir()):
            if not ADAPTER_NAME.fullmatch(d.name):
                errs.append(f"unsafe adapter name: {d.name}")
            for need in ("adapter_config.json", "adapter_model.safetensors"):
                if not (d / need).is_file():
                    errs.append(f"adapter {d.name} is missing {need}")
    return errs


def build_zip(root: Path, out: Path) -> Path:
    """Zip root with agent.yaml at the archive root, in a deterministic order."""
    errs = check(root)
    if errs:
        raise ValueError("; ".join(errs))
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                info = zipfile.ZipInfo(
                    p.relative_to(root).as_posix(), date_time=(1980, 1, 1, 0, 0, 0)
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                zf.writestr(info, p.read_bytes())
    return out


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "check"
    root = Path(argv[2]) if len(argv) > 2 else Path("submission")
    if cmd == "check":
        errs = check(root)
        for e in errs:
            print(f"ERROR: {e}", file=sys.stderr)
        print("submission OK" if not errs else f"{len(errs)} problem(s)")
        return 1 if errs else 0
    if cmd == "zip":
        out = Path(argv[3]) if len(argv) > 3 else Path("dist/submission.zip")
        try:
            path = build_zip(root, out)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"wrote {path} ({path.stat().st_size / 2**20:.2f} MiB)")
        print(f"SHA-256: {digest}")
        return 0
    print("usage: submission.py [check|zip] [dir] [out]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
