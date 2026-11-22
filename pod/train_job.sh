#!/usr/bin/env bash
# One queued LoRA training run on the local GPU (queue it with pueue; see docs/research/lora-pod-plan.md).
#   pod/train_job.sh RUN_ID [lora_train.py train flags: --smoke --epochs N --rank R --lr X]
set -euo pipefail
RUN="${1:?run id}"; shift
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
W="$HOME/gpu-work"
python3 scripts/gpu_queue.py wait-vram --util 0.70   # the desktop and a stray process take VRAM
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
mkdir -p "$W/out/$RUN"
python3 scripts/gpu_queue.py sample "$W/out/$RUN/gpu_samples.csv" &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT
"$W/train-venv/bin/python" scripts/lora_train.py train "${TRAIN_DATA:-$W/teacher-data}" \
  "$W/models/gemma-4-e4b-it-qat-w4a16-ct/2" "$W/out/$RUN/adapter" "$@" >"$W/out/$RUN/train.log" 2>&1
tail -n 4 "$W/out/$RUN/train.log" | cut -c1-200
