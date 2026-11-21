#!/usr/bin/env bash
# The semula side of a teacher run (docs/research/teacher-traces.md): a fresh semula container on an
# --internal docker network, plus the Haiku worker on the host.
#   scripts/teacher_stack.sh up      then run: ER_EXTERNAL_API_BASE=http://semula:8080/v1 LOCAL_GPU_NETWORK=teacher-net pod/local_run.sh run NAME
#   scripts/teacher_stack.sh down
set -euo pipefail
W="${LOCAL_GPU_WORK:-$HOME/gpu-work}"
case "${1:-}" in
  up)
    docker network inspect teacher-net >/dev/null 2>&1 || docker network create --internal teacher-net >/dev/null
    docker rm -f semula-teacher >/dev/null 2>&1 || true
    docker volume rm semula-teacher-data >/dev/null 2>&1 || true  # a fresh volume: no recorded answer may replay
    docker run -d --name semula-teacher -p 127.0.0.1:8081:8080 -e SEMULA_MODE=record \
      -v semula-teacher-data:/data ghcr.io/leejianrong/semula:0.6.0 >/dev/null
    docker network connect --alias semula teacher-net semula-teacher
    sleep 4
    nohup python3 "$(dirname "$0")/teacher_worker.py" --workers "${WORKERS:-2}" >"$W/teacher-worker.log" 2>&1 &
    echo $! >"$W/teacher-worker.pid"
    echo "up: semula on teacher-net, worker pid $(cat "$W/teacher-worker.pid")" ;;
  down)
    [ ! -f "$W/teacher-worker.pid" ] || kill "$(cat "$W/teacher-worker.pid")" 2>/dev/null || true
    rm -f "$W/teacher-worker.pid"
    docker rm -f semula-teacher >/dev/null 2>&1 || true
    docker network rm teacher-net >/dev/null 2>&1 || true
    docker volume rm semula-teacher-data >/dev/null 2>&1 || true
    echo down ;;
  *) sed -n '2,5p' "$0"; exit 2 ;;
esac
