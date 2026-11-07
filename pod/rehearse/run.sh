#!/usr/bin/env bash
# Rehearse pod/job.sh locally against fake kaggle/runpodctl, injecting failures. Costs nothing.
# Each scenario asserts the job aborts FAST with the right signal and still publishes a report.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOB="${JOB:-$HERE/../job.sh}"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
python3 "$HERE/fixture.py" "$W/fx/data" 2>/dev/null || python3 "$HERE/fixture.py" "$W/fx/data"
SECRET="SECRET-TOKEN-abc123"
pass=0
bad=0

scenario() { # name, max_seconds, expect_exit(0|1), then ENV=VAL pairs
  local name=$1 maxs=$2 want=$3 start rc elapsed
  shift 3
  if [ -n "${ONLY:-}" ] && [ "$ONLY" != "$name" ]; then return 0; fi
  local run="$W/$name"
  mkdir -p "$run"
  start=$(date +%s)
  env RUN="$run/run" KAGGLE_BIN="$HERE/fake_kaggle" RUNPODCTL_BIN="$HERE/fake_runpodctl" \
    FAKE_DIR="$W/fx/data" FAKE_RELAY="$run/relay" SKIP_PIP=1 KAGGLE_API_TOKEN="$SECRET" \
    HB_SECS=1 DL_POLL=1 MIN_FILES=3 MIN_MIB=0 MAX_MIB=3000 T_SEND=10 "$@" \
    bash "$JOB" >"$run/out.log" 2>&1
  rc=$?
  elapsed=$(($(date +%s) - start))
  CUR="$run/out.log"
  check "$name: exit code $want" "[ $rc -eq $want ]"
  check "$name: finished within ${maxs}s (took ${elapsed}s)" "[ $elapsed -le $maxs ]"
  check "$name: token never in the log" "! grep -q '$SECRET' '$CUR' '$run/run/job.log'"
  check "$name: report published" "grep -q RP_REPORT_BEGIN '$CUR' && grep -q RP_REPORT_END '$CUR'"
  check "$name: relay code surfaced" "grep -q 'RP_ARTIFACT_CODE=' '$CUR'"
  check "$name: artifact reached the relay" "ls '$run/relay'/artifact.tgz >/dev/null 2>&1"
  check "$name: heartbeat seen or run too short" "grep -q '^hb ' '$CUR' || [ $elapsed -le 2 ]"
}
check() { # label, shell condition
  if eval "$2"; then pass=$((pass + 1)); echo "  ok   $1"; else bad=$((bad + 1)); echo "  FAIL $1"; fi
}
expect() {
  if [ -n "${ONLY:-}" ] && [ "$ONLY" != "$1" ]; then return 0; fi
  check "$1: log has '$2'" "grep -q -- '$2' '$CUR'"
}

echo "== happy path"
scenario happy 60 0
expect happy 'STAGE bootstrap'; expect happy 'auth-ok'; expect happy 'smoke-ok'
expect happy 'STAGE download'; expect happy 'download complete'; expect happy 'STAGE done'
expect happy 'DONE status=ok'; expect happy '"status":"ok"'; expect happy '"tasks":5'
expect happy '"tasks_with_mapped_node":5'

echo "== zipped downloads are unpacked"
scenario zip 60 0 FAKE_MODE=zip
expect zip 'DONE status=ok'

echo "== pagination across several listing pages"
scenario pages 60 0 FAKE_PAGE=3
expect pages 'DONE status=ok'

echo "== bad token fails in seconds, secret scrubbed from the error"
scenario authfail 15 1 FAKE_MODE=auth_fail
expect authfail 'token rejected or expired'; expect authfail 'STAGE failed'; expect authfail '"status":"failed"'
expect authfail '<redacted>'

echo "== rules not accepted"
scenario norules 15 1 FAKE_MODE=no_rules
expect norules 'competition rules not accepted'

echo "== listing of the wrong shape is rejected before downloading"
scenario shape 15 1 MIN_FILES=500
expect shape 'listing too small'

echo "== truncated files are caught by the size check"
scenario trunc 40 1 FAKE_MODE=truncate
expect trunc 'smoke download failed'

echo "== projected download time over budget aborts at smoke, not after hours"
scenario slowproj 40 1 FAKE_MODE=slow FAKE_SLEEP=2 T_DL=1 MIN_FILES=3
expect slowproj 'projected download'

echo "== a stalled download is killed by the stall detector"
scenario stall 90 1 FAKE_MODE=slow FAKE_SLEEP=4 DL_PAR=1 STALL_SECS=2 T_DL=1000 T_FILE=20
expect stall 'download stalled'

echo "== hanging downloads hit the per-file timeout, not the lifetime ceiling"
scenario hang 60 1 FAKE_MODE=hang T_FILE=2
expect hang 'smoke download failed'

echo "== quiet stage raises a WARN"
scenario quiet 90 1 FAKE_MODE=slow FAKE_SLEEP=3 DL_PAR=1 STALL_SECS=2 QUIET_WARN=1 T_DL=1000 T_FILE=20
expect quiet 'WARN no progress'

echo "== explore failure still publishes"
scenario nopy 60 1 EXPLORE_PY=/nonexistent.py
expect nopy 'explore.py failed'
echo
echo "passed=$pass failed=$bad"
[ "$bad" -eq 0 ]
