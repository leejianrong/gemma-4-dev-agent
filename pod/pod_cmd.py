"""Print the shell command a RunPod CPU pod runs: write the job files, then run pod/job.sh.

The scripts travel inside the command (no fetch at boot, so nothing can hang before the wrapper's
watchdog). The Kaggle token is read by name from .env and goes only into the command text; this
script never prints anything else about it. Usage:
    RP_JOB_CMD="$(python3 pod/pod_cmd.py pod/layout_probe.py)" ... rp up 2>&1 | python3 -m pod.scrub
Extra arguments are non-secret KEY=VALUE pairs exported before the job, for example
WANT_SNAPSHOTS=1, or @path files shipped beside the job under their own name (the GPU job ships
kernel.py and gpu_setup.sh this way).
"""

from __future__ import annotations

import base64
import gzip
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
    """Write text to dest from a gzip+base64 block, keeping the command small (RunPod limits it)."""
    blob = base64.b64encode(gzip.compress(text.encode("utf-8"), 9, mtime=0)).decode()
    lines = "\n".join(blob[i : i + 76] for i in range(0, len(blob), 76))
    return f"base64 -d <<'{tag}' | gunzip > {dest}\n{lines}\n{tag}\n"


def command(
    analysis: Path, token: str, env: list[str] | None = None, files: list[Path] | None = None
) -> str:
    extra = "".join(f"export {shlex.quote(e)}\n" for e in env or [])
    extra_files = "".join(
        heredoc(f.name, f.read_text(encoding="utf-8"), f"EOF_{i}")
        for i, f in enumerate(files or [])
    )
    return (
        f"export KAGGLE_API_TOKEN={shlex.quote(token)}\n"
        + extra
        + "mkdir -p /workspace/job && cd /workspace/job\n"
        + heredoc("job.sh", (ROOT / "job.sh").read_text(encoding="utf-8"), "EOF_JOB_SH")
        + heredoc("analysis.py", analysis.read_text(encoding="utf-8"), "EOF_ANALYSIS_PY")
        + extra_files
        + "export EXPLORE_PY=/workspace/job/analysis.py\n"
        "bash job.sh\n"
    )


if __name__ == "__main__":
    rest = sys.argv[2:]
    shipped = [Path(a[1:]) for a in rest if a.startswith("@")]
    pairs = [a for a in rest if not a.startswith("@")]
    sys.stdout.write(command(Path(sys.argv[1]), env_value(ENV, "KAGGLE_API_TOKEN"), pairs, shipped))
