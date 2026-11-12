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


SMALL = {"e4b_v2": "e4b_v1", "e2b_v2": "e2b_v1"}


def _prompt(name: str) -> str:
    return (ROOT / "experiments" / "bundles" / name / "prompts" / "system.md").read_text()


@pytest.mark.parametrize("name", SMALL)
def test_small_model_bundle_passes_the_check_and_keeps_its_model(name):
    root = ROOT / "experiments" / "bundles" / name
    assert sub.check(root) == []
    assert (
        f"model: gemma-4-{name.split('_')[0]}-it-qat-w4a16-ct" in (root / "agent.yaml").read_text()
    )


@pytest.mark.parametrize("name", SMALL)
def test_small_model_bundle_differs_from_its_v1_only_in_the_prompt(name):
    parent, bundle = (_files(ROOT / "experiments" / "bundles" / n) for n in (SMALL[name], name))
    assert parent.keys() == bundle.keys()
    assert [k for k in parent if parent[k] != bundle[k]] == ["prompts/system.md"]


@pytest.mark.parametrize("name", SMALL)
def test_small_model_prompt_is_no_longer_than_the_baseline_plus_ten_percent(name):
    assert len(_prompt(name)) <= 1.1 * len((BASE / "prompts" / "system.md").read_text())


@pytest.mark.parametrize("name", SMALL)
def test_small_model_prompt_has_the_edit_copy_rule_and_the_submit_tool_rule(name):
    text = _prompt(name)
    assert "submit_patch" in text and "TOOL" in text
    assert "character for character" in text and "old_string" in text
