#!/usr/bin/env bash
# Run the eval kernel on this machine's GPU, inside a container (docs/GPU_RUNS.md, "Local GPU").
#
#   pod/local_run.sh setup MODEL     venv, wheelhouse, weights, pinned test stack (needs network)
#   pod/local_run.sh gate IDS        gold patches must pass their tests (CPU, in the container)
#   pod/local_run.sh run NAME        run kaggle/eval_kernel/kernel.py, output in $LOCAL_GPU_WORK/out/NAME
#
# The harness runs repository tests and model-written shell commands, so nothing runs on the host:
# the container has no network, no capabilities and only read-only data. Build the kernel first
# (make kernel-eval). MODEL is e.g. gemma-4-e4b-it-qat-w4a16-ct. Needs uv, docker with the NVIDIA
# runtime and a kaggle login.
# ER_VLLM_GPU_UTIL is vLLM's share of VRAM (default 0.88: E4B weights are 11.5 GB on a 16 GB card).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
W="${LOCAL_GPU_WORK:-$HOME/gpu-work}"
VENV="$W/venv"
WHEELS="$W/wheelhouse"

setup() {
  local model="${1:?usage: local_run.sh setup MODEL}"
  mkdir -p "$W/models/$model/2" "$W/home"
  [ -x "$VENV/bin/python3" ] || uv venv --seed --python 3.12 "$VENV"
  [ -n "$(ls "$WHEELS"/*.whl 2>/dev/null)" ] ||
    kaggle datasets download metric/gemma-4-developer-agent-wheelhouse -p "$WHEELS" --unzip -q
  [ -f "$W/models/$model/2/model.safetensors" ] ||
    kaggle models instances versions download "google/gemma-4/other/$model/2" \
      -p "$W/models/$model/2" --untar -q
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  WHEELHOUSE="$WHEELS" bash "$REPO/pod/gpu_setup.sh"
  # gpu_setup.sh upgrades anyio, pydantic, click and others past the Kaggle image's pins, which
  # makes the repositories' tests fail on a DeprecationWarning: pin the test stack last.
  bash "$REPO/pod/test_env.sh"
}

in_container() {
  local out="$1"; shift
  mkdir -p "$W/out/$out"
  local py
  py="$(readlink -f "$VENV/bin/python3")"
  py="$(dirname "${py%/bin/*}")"  # uv's python folder, which the venv links into (also by alias)
  docker run --rm --gpus all --network none --cap-drop ALL --security-opt no-new-privileges \
    --pids-limit 4096 --memory "${LOCAL_GPU_MEM:-22g}" --shm-size 8g \
    --tmpfs /tmp:rw,exec,size=8g \
    --user "$(id -u):$(id -g)" -e HOME="$W/home" -e USER=gemma -e LOGNAME=gemma -e HF_HUB_OFFLINE=1 \
    -e PATH="$VENV/bin:/usr/local/bin:/usr/bin:/bin" \
    -e DATA_DIR=/data -e OUT_DIR=/out -e ER_WHEELHOUSE_DIR="$WHEELS" -e ER_MODEL_ROOT_DIR="$W/models" \
    -e ER_VLLM_GPU_UTIL="${ER_VLLM_GPU_UTIL:-0.88}" \
    -v "$VENV:$VENV" -v "$py:$py:ro" \
    -v "$REPO/pod:/repo/pod:ro" -v "$REPO/kaggle/eval_kernel:/repo/kernel:ro" \
    -v "$REPO/data/competition:/data:ro" -v "$WHEELS:$WHEELS:ro" -v "$W/models:$W/models:ro" \
    -v "$W/home:$W/home" -v "$W/out/$out:/out" \
    python:3.12 "$@"
}

case "${1:-}" in
  setup) setup "${2:-}" ;;
  gate) in_container gate python3 /repo/pod/env_check.py /data "${2:?usage: local_run.sh gate ID[,ID...]}" ;;
  run) in_container "${2:?usage: local_run.sh run NAME}" python3 /repo/kernel/kernel.py ;;
  *) sed -n '2,13p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
