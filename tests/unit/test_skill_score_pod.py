import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "pod" / "rehearse"))
import build_skill_score  # noqa: E402
import fixture  # noqa: E402

OLD = "def alpha(x):\n    return x + 1\n\n\ndef beta(y):\n    return y\n"


def add_snapshots(data: Path) -> None:
    (data / "snapshots").mkdir()
    for i in range(5):
        with tarfile.open(data / "snapshots" / f"pkg_{i}.tgz", "w:gz") as tf:
            body = OLD.encode()
            info = tarfile.TarInfo("./pkg/mod.py")
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))


def test_standalone_script_scores_the_skill_from_data_and_out_dirs(tmp_path):
    script = build_skill_score.build(tmp_path / "skill_score_pod.py")
    compile(script.read_text(encoding="utf-8"), "skill_score_pod.py", "exec")
    fixture.main(tmp_path / "data")
    add_snapshots(tmp_path / "data")
    r = subprocess.run(
        [sys.executable, "-I", str(script), str(tmp_path / "data"), str(tmp_path / "out")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert report["tasks_scored"] == 5
    methods = {row["method"]: row for row in report["summary"]}
    assert set(methods) == {"skill_head", "skill_full", "graph_bm25"}
    assert methods["skill_head"]["hit@10"] == 1.0
    assert report["timing"]["head"]["tasks"] == 5
