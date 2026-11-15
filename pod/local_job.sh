#!/usr/bin/env bash
# One queued run on the local GPU: build the eval kernel, wait for free VRAM, run it in the container.
# Usage (scripts/gpu_queue.py add calls it through pueue):
#   pod/local_job.sh BUNDLE MODEL RUN_ID SEED N_TASKS
# BUNDLE is a folder under experiments/bundles; the tasks are the first N_TASKS of data/dev_subset.json.
set -euo pipefail
BUNDLE="${1:?bundle}" MODEL="${2:?model}" RUN_ID="${3:?run id}" SEED="${4:?seed}" N="${5:?n tasks}"
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

IDS=$(python3 -c "import json,sys;print(','.join(json.load(open('data/dev_subset.json'))['ids'][:int(sys.argv[1])]))" "$N")
python3 scripts/gpu_queue.py wait-vram  # before the build: a build while waiting would race the next job
KAGGLE_USER=$(python3 -I -c "import json,os;print(json.load(open(os.path.expanduser('~/.kaggle/credentials.json')))['username'])")
SUBMISSION_DIR="experiments/bundles/$BUNDLE" EVAL_TASKS="$IDS" EVAL_MODEL="$MODEL" EVAL_RUN_ID="$RUN_ID" \
  EVAL_SEED="$SEED" EVAL_MAX_MIN=480 python3 kaggle/build_kernel.py "$KAGGLE_USER" eval >/dev/null
mkdir -p "$HOME/gpu-work/out/$RUN_ID"
pod/local_run.sh run "$RUN_ID" >"$HOME/gpu-work/out/$RUN_ID/container.log" 2>&1
tail -n 5 "$HOME/gpu-work/out/$RUN_ID/container.log" | cut -c1-300
