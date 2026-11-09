#!/usr/bin/env bash
# Assert the analysis container cannot reach the network or write to the data mount or its root.
set -u
IMG="${1:-gemma-dev-analysis}"
D="$(mktemp -d)"
trap 'rmdir "$D"' EXIT
run() {
  docker run --rm --network none --read-only --tmpfs /tmp:rw,size=64m --cap-drop ALL \
    --security-opt no-new-privileges --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$D:/data:ro" "$IMG" python -c "$1"
}
bad=0
check() {
  if [ "$2" = "$3" ]; then echo "  ok   $1"; else echo "  FAIL $1 (got $3)"; bad=1; fi
}
check "no network" blocked "$(run 'import socket
try:
    socket.create_connection(("1.1.1.1", 53), 2); print("open")
except OSError: print("blocked")')"
check "data is read-only" blocked "$(run 'try:
    open("/data/x", "w"); print("writable")
except OSError: print("blocked")')"
check "root fs is read-only" blocked "$(run 'try:
    open("/etc/x", "w"); print("writable")
except OSError: print("blocked")')"
check "numpy present" ok "$(run 'import numpy; print("ok")')"
exit $bad
