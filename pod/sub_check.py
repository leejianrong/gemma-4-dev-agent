"""Compare our submission with the starter sample_submission, field by field, on Kaggle.

Runs in a CPU kernel with the competition data attached, so nothing is downloaded locally. It
lists the sample's files, flattens every YAML file on both sides (resolving !include), reports keys
only on one side and values that differ, and tries the real `adk_submission.validate_directory`
(which our local pre-flight only mirrors). SUBMISSION_FILES is injected by kaggle/build_kernel.py.
Outputs (OUT_DIR): subdiff.json, subdiff.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml


class _Loader(yaml.SafeLoader):
    pass


def sc_loader(base: Path):
    def include(loader, node):
        p = base / loader.construct_scalar(node)
        text = p.read_text(encoding="utf-8") if p.is_file() else None
        if text is None:
            return f"<missing include {p.name}>"
        return text if p.suffix == ".md" else yaml.load(text, Loader=_Loader)  # noqa: S506

    class L(_Loader):
        pass

    L.add_constructor("!include", include)
    return L


def sc_flatten(value, prefix="") -> dict:
    """{'a.b': leaf, 'tools[0]': ...}; lists index by position, long strings by sha-like length."""
    out: dict = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(sc_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, list):
        if all(not isinstance(v, (dict, list)) for v in value):
            out[prefix] = value
        else:
            for i, v in enumerate(value):
                out.update(sc_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = value
    return out


def sc_load_dir(root: Path) -> tuple[dict, list[str]]:
    flat: dict = {}
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    for rel in files:
        if rel.endswith((".yaml", ".yml")):
            data = yaml.load(
                (root / rel).read_text(encoding="utf-8"), Loader=sc_loader((root / rel).parent)
            )  # noqa: S506
            flat.update({f"{rel}::{k}": v for k, v in sc_flatten(data).items()})
        elif rel.endswith(".md"):
            flat[f"{rel}::<text>"] = (root / rel).read_text(encoding="utf-8")
    return flat, files


def sc_short(v, n=80):
    s = json.dumps(v) if not isinstance(v, str) else v
    return s if len(s) <= n else f"<{len(s)} chars> {s[:n]}..."


def sc_diff(sample: dict, ours: dict) -> dict:
    only_sample = sorted(k for k in sample if k not in ours)
    only_ours = sorted(k for k in ours if k not in sample)
    differ = sorted(k for k in sample if k in ours and sample[k] != ours[k])
    return {
        "only_in_sample": {k: sc_short(sample[k]) for k in only_sample},
        "only_in_ours": {k: sc_short(ours[k]) for k in only_ours},
        "differ": {k: {"sample": sc_short(sample[k]), "ours": sc_short(ours[k])} for k in differ},
        "same": len([k for k in sample if k in ours and sample[k] == ours[k]]),
    }


def sc_find_sample(data: Path) -> Path | None:
    hits = [p for p in data.rglob("sample_submission*") if p.is_dir()]
    return sorted(hits, key=lambda p: len(p.parts))[0] if hits else None


def sc_try_validate(path: Path) -> dict:
    try:
        import adk_submission  # noqa: PLC0415
    except Exception as e:
        return {"available": False, "import_error": f"{type(e).__name__}: {e}"}
    try:
        return {
            "available": True,
            "result": sc_short(adk_submission.validate_directory(path), 2000),
        }
    except Exception as e:
        return {"available": True, "raised": f"{type(e).__name__}: {e}"}


def sc_run(data: Path, out: Path, files: dict[str, str]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    ours_dir = out / "our_submission"
    for rel, text in files.items():
        (ours_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (ours_dir / rel).write_text(text, encoding="utf-8")
    sample = sc_find_sample(data)
    report: dict = {"sample_dir": str(sample) if sample else None}
    ours, ours_files = sc_load_dir(ours_dir)
    report["our_files"] = ours_files
    if sample:
        theirs, their_files = sc_load_dir(sample)
        report["sample_files"] = their_files
        report["diff"] = sc_diff(theirs, ours)
    report["validate_ours"] = sc_try_validate(ours_dir)
    if sample:
        report["validate_sample"] = sc_try_validate(sample)
    (out / "subdiff.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def sc_main() -> int:
    """Kernel entry; DATA, OUTD and SUBMISSION_FILES come from the kernel wrapper."""
    rep = sc_run(DATA, OUTD, SUBMISSION_FILES)  # noqa: F821
    print(json.dumps(rep, indent=1)[:6000])
    return 0 if rep.get("sample_dir") else 1
