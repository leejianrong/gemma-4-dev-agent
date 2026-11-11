"""GPU pod step that pod/job.sh runs instead of the analysis: fetch, install, eval.

Usage (job.sh calls it): python3 gpu_run.py DATA OUT. A built eval kernel (kaggle/build_kernel.py,
kind eval) sits next to this file as kernel.py; its parameters and the submission bundle are baked
in. The kernel finds data, wheels and weights through DATA_DIR, OUT_DIR, ER_WHEELHOUSE_DIR and
ER_MODEL_ROOT_DIR, so nothing here edits it. The Kaggle token reaches the CLI through the
environment.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WHEEL_SLUG = "metric/gemma-4-developer-agent-wheelhouse"
MODEL = os.environ.get("GPU_MODEL", "gemma-4-31b-it-qat-w4a16-ct")
MODEL_SLUG = f"google/gemma-4/other/{MODEL}/2"
T0 = time.time()


def log(msg: str) -> None:
    print(f"{msg} (t+{time.time() - T0:.0f}s)", flush=True)


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, check=True, env={**os.environ, **(env or {})})


def fetch(work: Path) -> tuple[Path, Path]:
    """Download the wheelhouse and the model unless already there; return their folders."""
    wheels, models = work / "wheelhouse", work / "models" / MODEL / "2"
    if not any(wheels.glob("*.whl")):
        log("STAGE fetch-wheelhouse")
        run(["kaggle", "datasets", "download", WHEEL_SLUG, "-p", str(wheels), "--unzip", "-q"])
    if not (models / "model.safetensors").is_file():
        log("STAGE fetch-model")
        models.mkdir(parents=True, exist_ok=True)
        run(
            ["kaggle", "models", "instances", "versions", "download", MODEL_SLUG]
            + ["-p", str(models), "--untar", "-q"]
        )
    return wheels, work / "models"


def main(argv: list[str]) -> int:
    data, out = Path(argv[1]), Path(argv[2])
    work = Path(os.environ.get("GPU_WORK", "/workspace/gpu"))
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    if shutil.which("nvidia-smi"):
        query = "--query-gpu=name,driver_version,memory.total"
        subprocess.run(["nvidia-smi", query, "--format=csv"], check=False)
    log("STAGE test-env")
    run(["bash", str(HERE / "test_env.sh")])
    if ids := os.environ.get("CONTROL_IDS"):
        log("STAGE env-check")
        run([sys.executable, str(HERE / "env_check.py"), str(data), ids])
    if os.environ.get("ENV_CHECK_ONLY"):
        return 0
    wheels, models = fetch(work)
    log("STAGE setup")
    run(["bash", str(HERE / "gpu_setup.sh")], {"WHEELHOUSE": str(wheels)})
    log("STAGE eval")
    env = {
        "DATA_DIR": str(data),
        "OUT_DIR": str(out),
        "ER_WHEELHOUSE_DIR": str(wheels),
        "ER_MODEL_ROOT_DIR": str(models),
    }
    run([sys.executable, str(HERE / "kernel.py")], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
