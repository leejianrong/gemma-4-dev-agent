"""Prompt-only arms differ from the baseline in prompts/system.md alone and stay about as long."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import submission as sub  # noqa: E402

BASE = ROOT / "submission"
NAMES = ["tests_v1", "first_edit_v1", "edit_retry_v1", "doubt_v1"]


def _files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("name", NAMES)
def test_bundle_passes_the_submission_check(name):
    assert sub.check(ROOT / "experiments" / "bundles" / name) == []


@pytest.mark.parametrize("name", NAMES)
def test_bundle_changes_only_the_prompt_and_keeps_its_length(name):
    base, bundle = _files(BASE), _files(ROOT / "experiments" / "bundles" / name)
    assert base.keys() == bundle.keys()
    assert [k for k in base if base[k] != bundle[k]] == ["prompts/system.md"]
    ratio = len(bundle["prompts/system.md"]) / len(base["prompts/system.md"])
    assert 0.9 <= ratio <= 1.1
