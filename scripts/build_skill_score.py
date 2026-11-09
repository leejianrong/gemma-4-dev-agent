"""Build dist/skill_score_pod.py: the skill scorer as one self-contained file for pod/job.sh.

pod/job.sh runs `python3 $EXPLORE_PY DATA_DIR OUT_DIR`. The scorer needs explore, gold_map,
localize, the skill script and skill_score, so they are inlined into one file with the helper the
Kaggle kernels use. Usage: build_skill_score.py [OUT_PATH]   (default dist/skill_score_pod.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kaggle"))
import build_kernel  # noqa: E402

PARTS = [
    "gold_map.py",
    "localize.py",
    "../experiments/skills/localize/scripts/localize.py",
    "skill_score.py",
]
TAIL = '\n\nif __name__ == "__main__":\n    raise SystemExit(ss_pod(sys.argv))\n'


def build(out: Path | None = None) -> Path:
    out = out or ROOT / "dist" / "skill_score_pod.py"
    src = build_kernel._inline("explore.py")
    for name in PARTS:
        src += "\n" + build_kernel._inline(name).replace("from __future__ import annotations\n", "")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(src + TAIL, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else None))
