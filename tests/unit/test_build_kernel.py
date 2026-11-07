import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kaggle"))
sys.path.insert(0, str(ROOT / "pod" / "rehearse"))
import build_kernel  # noqa: E402
import fixture  # noqa: E402


@pytest.fixture()
def kernel(tmp_path, monkeypatch):
    monkeypatch.setattr(build_kernel, "OUT", tmp_path / "k")
    return build_kernel.build("someone")


def run(kernel, data, out, **env):
    e = {"DATA_DIR": str(data), "OUT_DIR": str(out), "MIN_FILES": "3", "PATH": "/usr/bin:/bin"}
    e.update(env)
    return subprocess.run(
        [sys.executable, "-I", str(kernel)], env=e, capture_output=True, text=True, timeout=60
    )


def test_metadata_attaches_the_competition_and_stays_cpu_offline(kernel):
    meta = json.loads((kernel.parent / "kernel-metadata.json").read_text())
    assert meta["id"] == "someone/gemma-4-graph-explore"
    assert meta["competition_sources"] == ["gemma-4-developer-agent"]
    assert meta["enable_gpu"] == "false" and meta["enable_internet"] == "false"


def test_generated_script_runs_and_reports(kernel, tmp_path):
    fixture.main(tmp_path / "d")
    r = run(kernel, tmp_path / "d", tmp_path / "o")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STAGE preflight" in r.stdout and "STAGE done" in r.stdout
    block = r.stdout.split("RP_REPORT_BEGIN\n")[1].split("\nRP_REPORT_END")[0]
    rep = json.loads(block)
    assert rep["status"] == "ok" and rep["report"]["tasks"] == 5


def test_missing_data_fails_fast_but_still_reports(kernel, tmp_path):
    r = run(kernel, tmp_path / "nope", tmp_path / "o")
    assert r.returncode == 1
    assert "data dir" in r.stdout + r.stderr and "STAGE failed" in r.stdout
    assert '"status":"failed"' in r.stdout


def test_too_few_files_is_rejected(kernel, tmp_path):
    fixture.main(tmp_path / "d")
    r = run(kernel, tmp_path / "d", tmp_path / "o", MIN_FILES="500")
    assert r.returncode == 1 and "too few files" in r.stdout + r.stderr
