import zipfile
from pathlib import Path

import pytest

import submission

MODEL = "gemma-4-31b-it-qat-w4a16-ct"


def make(root: Path, model: str = MODEL) -> Path:
    root.mkdir()
    (root / "prompts").mkdir()
    (root / "prompts" / "system.md").write_text("be careful")
    (root / "agent.yaml").write_text(
        f"name: coder\nmodel: {model}\ninstruction: !include prompts/system.md\n"
    )
    return root


def test_valid_dir_passes(tmp_path):
    assert submission.check(make(tmp_path / "s")) == []


def test_repo_submission_passes():
    repo_sub = Path(__file__).resolve().parents[2] / "submission"
    assert submission.check(repo_sub) == []


def test_missing_root_config(tmp_path):
    d = make(tmp_path / "s")
    (d / "agent.yaml").unlink()
    assert any("root config" in e for e in submission.check(d))


def test_two_root_configs(tmp_path):
    d = make(tmp_path / "s")
    (d / "root_agent.yaml").write_text(f"name: x\nmodel: {MODEL}\n")
    assert any("root config" in e for e in submission.check(d))


def test_disallowed_model(tmp_path):
    d = make(tmp_path / "s", model="gemma-4-31b-it")
    assert any("model not allowed" in e for e in submission.check(d))


def test_two_models(tmp_path):
    d = make(tmp_path / "s")
    (d / "sub.yaml").write_text("name: s\nmodel: gemma-4-e2b-it-qat-w4a16-ct\n")
    assert any("exactly one declared model" in e for e in submission.check(d))


def test_provider_prefix_is_stripped(tmp_path):
    assert submission.check(make(tmp_path / "s", model=f"openai/{MODEL}")) == []


def test_symlink_rejected(tmp_path):
    d = make(tmp_path / "s")
    (d / "link.md").symlink_to(d / "prompts" / "system.md")
    assert any("symlink" in e for e in submission.check(d))


def test_bad_extension(tmp_path):
    d = make(tmp_path / "s")
    (d / "w.bin").write_bytes(b"x")
    assert any("extension" in e for e in submission.check(d))


def test_include_traversal(tmp_path):
    d = make(tmp_path / "s")
    (d / "agent.yaml").write_text(f"name: c\nmodel: {MODEL}\ninstruction: !include ../x.md\n")
    assert any("unsafe !include" in e for e in submission.check(d))


def test_incomplete_adapter(tmp_path):
    d = make(tmp_path / "s")
    (d / "adapters" / "main_lora").mkdir(parents=True)
    (d / "adapters" / "main_lora" / "adapter_config.json").write_text("{}")
    assert any("adapter_model.safetensors" in e for e in submission.check(d))


def test_zip_has_agent_yaml_at_root(tmp_path):
    out = submission.build_zip(make(tmp_path / "s"), tmp_path / "o.zip")
    assert "agent.yaml" in zipfile.ZipFile(out).namelist()


def test_zip_refuses_invalid_dir(tmp_path):
    d = make(tmp_path / "s")
    (d / "agent.yaml").unlink()
    with pytest.raises(ValueError):
        submission.build_zip(d, tmp_path / "o.zip")
