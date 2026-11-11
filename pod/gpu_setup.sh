#!/usr/bin/env bash
# Install what Kaggle's base image has and the offline wheelhouse needs, on a Python 3.12 GPU pod.
# Usage: WHEELHOUSE=/dir/with/wheels bash pod/gpu_setup.sh
# Order matters: torch first (vllm pins it), then everything else resolved against the wheelhouse.
# eval_runner.py later reinstalls the wheelhouse with --no-deps, so dependencies must already be here.
set -Eeuo pipefail

WHEELHOUSE="${WHEELHOUSE:?set WHEELHOUSE to the downloaded wheelhouse folder}"
PIP=(python3 -m pip install --quiet --disable-pip-version-check)

python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version' ||
  { echo "ERROR the wheelhouse is built for Python 3.12"; exit 1; }

"${PIP[@]}" torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 litellm
"${PIP[@]}" --find-links "$WHEELHOUSE" \
  vllm==0.19.1 google-adk==1.36.1 swegemma==0.2.11 adk-submission==0.2.13 adk-eval-core==0.1.0

python3 - <<'PY'
from importlib.metadata import version

names = ["torch", "torchvision", "torchaudio", "litellm", "vllm", "transformers", "google-adk",
         "swegemma", "adk-submission", "numpy"]
print("RESOLVED " + " ".join(f"{n}={version(n)}" for n in names))
import litellm, torch  # noqa: E401, F401
from adk_submission import VllmServer  # noqa: F401
from swegemma.evaluate import Evaluator  # noqa: F401

print("IMPORT-OK cuda_build=" + str(torch.version.cuda))
PY
