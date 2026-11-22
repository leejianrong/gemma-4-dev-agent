#!/usr/bin/env bash
# One queued run on the local GPU: build the eval kernel, wait for free VRAM, run it in the container.
# Usage (scripts/gpu_queue.py add calls it through pueue):
#   pod/local_job.sh BUNDLE MODEL RUN_ID SEED N_TASKS
# BUNDLE is a folder under experiments/bundles; the tasks are the first N_TASKS of data/dev_subset.json
# (LOCAL_IDS_FILE swaps the list, LOCAL_DATA_DIR the task data; gpu_queue.py add --ids-file/--data-dir sets them).
set -euo pipefail
BUNDLE="${1:?bundle}" MODEL="${2:?model}" RUN_ID="${3:?run id}" SEED="${4:?seed}" N="${5:?n tasks}"
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

IDS_FILE="${LOCAL_IDS_FILE:-data/dev_subset.json}"  # a JSON object with `ids`, or a bare list
IDS=$(python3 -c "import json,sys;d=json.load(open(sys.argv[2]));print(','.join((d['ids'] if isinstance(d,dict) else d)[:int(sys.argv[1])]))" "$N" "$IDS_FILE")
python3 scripts/gpu_queue.py wait-vram  # before the build: a build while waiting would race the next job
KAGGLE_USER=$(python3 -I -c "import json,os;print(json.load(open(os.path.expanduser('~/.kaggle/credentials.json')))['username'])")
SUBMISSION_DIR="experiments/bundles/$BUNDLE" EVAL_TASKS="$IDS" EVAL_MODEL="$MODEL" EVAL_RUN_ID="$RUN_ID" \
  EVAL_SEED="$SEED" EVAL_MAX_MIN=480 python3 kaggle/build_kernel.py "$KAGGLE_USER" eval >/dev/null
mkdir -p "$HOME/gpu-work/out/$RUN_ID"
OUT="$HOME/gpu-work/out/$RUN_ID"
python3 scripts/gpu_queue.py sample "$OUT/gpu_samples.csv" --container "gemma-$RUN_ID" &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT
[ ! -d "experiments/bundles/$BUNDLE/adapters" ] || export LOCAL_ADAPTERS_DIR="$PWD/experiments/bundles/$BUNDLE/adapters"
pod/local_run.sh run "$RUN_ID" >"$OUT/container.log" 2>&1
kill $SAMPLER 2>/dev/null || true
# a run whose GPU ran out of free VRAM can stall (docs/GPU_RUNS.md section 16): flag it
python3 scripts/gpu_queue.py check-samples "$OUT/gpu_samples.csv" || touch "$OUT/SUSPECT_VRAM"
tail -n 5 "$OUT/container.log" | cut -c1-300
