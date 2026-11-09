"""Print the shell command a RunPod CPU pod runs: write the job files, then run pod/job.sh.

The scripts travel inside the command (no fetch at boot, so nothing can hang before the wrapper's
watchdog). The Kaggle token is read by name from .env and goes only into the command text; this
script never prints anything else about it. Usage:
    RP_JOB_CMD="$(python3 pod/pod_cmd.py pod/layout_probe.py)" ... rp up 2>&1 | python3 pod/scrub.py
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = ROOT.parent / ".env"


def env_value(path: Path, name: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, val = line.partition("=")
        if sep and key.strip() == name:
            return val.strip().strip("'\"")
    raise SystemExit(f"{name} not found in {path.name}")


def heredoc(dest: str, text: str, tag: str) -> str:
    assert f"\n{tag}\n" not in text
    return f"cat > {dest} <<'{tag}'\n{text.rstrip()}\n{tag}\n"


def command(analysis: Path, token: str) -> str:
    return (
        f"export KAGGLE_API_TOKEN={shlex.quote(token)}\n"
        "mkdir -p /workspace/job && cd /workspace/job\n"
        + heredoc("job.sh", (ROOT / "job.sh").read_text(encoding="utf-8"), "EOF_JOB_SH")
        + heredoc("analysis.py", analysis.read_text(encoding="utf-8"), "EOF_ANALYSIS_PY")
        + "export EXPLORE_PY=/workspace/job/analysis.py\n"
        "bash job.sh\n"
    )


if __name__ == "__main__":
    sys.stdout.write(command(Path(sys.argv[1]), env_value(ENV, "KAGGLE_API_TOKEN")))
