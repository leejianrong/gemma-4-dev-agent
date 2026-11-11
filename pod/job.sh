#!/usr/bin/env bash
# Pod-side job: fetch tasks.jsonl + graphs + embeddings from Kaggle (about 850 MiB) and analyse them.
# PIP_EXTRA="numpy ..." installs extra packages for the analysis script.
# WANT_SNAPSHOTS=1 also fetches snapshots/ (about 20 GB; raise MAX_MIB and the pod disk);
# SNAP_IDS=id1,id2,... limits that to those tasks.
#
# Observability contract (grep these tokens in `pod logs`):
#   STAGE <name>        a stage began          STAGE failed (...)  the job is dying, with the stage
#   hb ...              heartbeat every HB_SECS   WARN / ERROR      something is fishy / broken
#   RP_REPORT_BEGIN..END  compact JSON result (published on success AND failure)
#   RP_ARTIFACT_CODE=   relay code for the tarball
# Early-abort checks: auth probe, listing-shape check, disk check, smoke download with projected
# time, stall detector, slow-rate warning. The token is never printed.
set -Eeuo pipefail

RUN="${RUN:-/workspace/run}"
DATA="$RUN/data"
OUT="$RUN/out"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMP="${COMP:-gemma-4-developer-agent}"
KAGGLE="${KAGGLE_BIN:-kaggle}"
RUNPODCTL="${RUNPODCTL_BIN:-runpodctl}"
HB_SECS="${HB_SECS:-60}"
QUIET_WARN="${QUIET_WARN:-600}"
DL_POLL="${DL_POLL:-15}"
DL_PAR="${DL_PAR:-4}"
STALL_SECS="${STALL_SECS:-240}"
MIN_RATE_MBS="${MIN_RATE_MBS:-0.3}"
MIN_FILES="${MIN_FILES:-100}"
T_BOOT="${T_BOOT:-300}"
T_AUTH="${T_AUTH:-90}"
T_LIST="${T_LIST:-60}"
T_DL="${T_DL:-1500}"
T_FILE="${T_FILE:-180}"
T_ANALYZE="${T_ANALYZE:-900}"
T_SEND="${T_SEND:-900}"

mkdir -p "$DATA" "$OUT"
: >"$RUN/job.log"
echo init >"$RUN/stage"
echo running >"$RUN/status"
# Every line goes to the log (heartbeat/artifact need it); the token is scrubbed on the way.
exec > >(
  if [ -n "${KAGGLE_API_TOKEN:-}" ]; then sed -u "s|${KAGGLE_API_TOKEN}|<redacted>|g"; else cat; fi |
    tee -a "$RUN/job.log"
) 2>&1

now() { date +%s; }
progress() { now >"$RUN/last_progress"; }
stage() { echo "$1" >"$RUN/stage"; progress; echo "STAGE $1"; }
warn() { echo "WARN $*"; }
err() { echo "ERROR $*"; }
have() { command -v "$1" >/dev/null 2>&1; }
fail() {
  [ "$(cat "$RUN/status")" = failed ] && return 0
  echo failed >"$RUN/status"
  echo "STAGE failed ($1; was: $(cat "$RUN/stage"))"
}
die() { err "$*"; fail "$*"; exit 1; }
trap 'fail "line $LINENO"' ERR
progress

# step NAME SECS CMD...  : run with a timeout; log the reason on timeout/failure and return nonzero.
step() {
  local name=$1 secs=$2 rc=0
  shift 2
  timeout --foreground "$secs" "$@" || rc=$?
  if [ "$rc" -eq 124 ]; then err "$name timed out after ${secs}s"; fi
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 124 ]; then err "$name failed (rc=$rc)"; fi
  return "$rc"
}

heartbeat() {
  trap - ERR
  local t0 quiet lp disk mem load mb st
  t0=$(now)
  while :; do
    sleep "$HB_SECS"
    lp=$(cat "$RUN/last_progress" 2>/dev/null || echo "$t0")
    quiet=$(($(now) - lp))
    disk=$(df -P "$RUN" | awk 'NR==2{print $5+0}')
    mem=$(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{printf "%d",(t>0)?100*(t-a)/t:0}' /proc/meminfo)
    load=$(cut -d' ' -f1 /proc/loadavg)
    mb=$(du -sm "$DATA" 2>/dev/null | cut -f1)
    st=$(cat "$RUN/stage" 2>/dev/null)
    echo "hb stage=$st up=$(($(now) - t0))s quiet=${quiet}s load=$load disk=${disk}% mem=${mem}% data=${mb}MiB"
    [ "$quiet" -gt "$QUIET_WARN" ] && warn "no progress for ${quiet}s in stage $st"
    [ "$disk" -gt 90 ] && warn "disk ${disk}% full"
    [ "$mem" -gt 90 ] && warn "memory ${mem}% used"
  done
}
heartbeat &
HB_PID=$!

publish() {
  trap - ERR
  [ -n "${PUBLISHED:-}" ] && return 0
  PUBLISHED=1
  local status stg base code sp
  status=$(cat "$RUN/status" 2>/dev/null || echo failed)
  stg=$(cat "$RUN/stage" 2>/dev/null || echo unknown)
  echo "RP_REPORT_BEGIN"
  python3 - "$status" "$stg" "$OUT/report.json" <<'PY' || echo "{\"status\":\"$status\",\"stage\":\"$stg\"}"
import json, sys
status, stage, path = sys.argv[1:4]
try:
    rep = json.load(open(path))
except Exception:
    rep = None
print(json.dumps({"status": status, "stage": stage, "report": rep}, separators=(",", ":")))
PY
  echo "RP_REPORT_END"
  tar czf "$RUN/artifact.tgz" -C "$RUN" out job.log stage status listing.csv want.tsv dl.failed dl.log 2>/dev/null ||
    tar czf "$RUN/artifact.tgz" -C "$RUN" job.log 2>/dev/null || true
  if have "$RUNPODCTL" && [ -s "$RUN/artifact.tgz" ]; then
    base="gemma-$RANDOM$RANDOM"
    "$RUNPODCTL" send --code "$base" "$RUN/artifact.tgz" >"$RUN/send.log" 2>&1 &
    sp=$!
    code=""
    for _ in $(seq 1 30); do
      code=$(grep -oE "${base}[-0-9]+" "$RUN/send.log" 2>/dev/null | head -1 || true)
      [ -n "$code" ] && break
      sleep 1
    done
    if [ -n "$code" ]; then
      echo "RP_ARTIFACT_CODE=$code"
      timeout "$T_SEND" tail --pid="$sp" -f /dev/null || warn "relay not received within ${T_SEND}s"
    else
      warn "no relay code; the RP_REPORT block above is the result"
    fi
  else
    warn "runpodctl unavailable; the RP_REPORT block above is the result"
  fi
}
on_exit() {
  local rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ]; then echo failed >"$RUN/status"; fi
  if [ "$(cat "$RUN/status")" = running ]; then echo ok >"$RUN/status"; fi
  publish
  echo "DONE status=$(cat "$RUN/status")"
  kill "$HB_PID" 2>/dev/null || true
  sleep 1 # let the log tee flush
  if [ "$(cat "$RUN/status")" = ok ]; then exit 0; else exit 1; fi
}
trap on_exit EXIT

# ---- bootstrap ------------------------------------------------------------------------------
stage bootstrap
echo "host: $(uname -sr) cpus=$(nproc) $(awk '/MemTotal/{printf "ram=%dMiB", $2/1024}' /proc/meminfo) free=$(df -Pm "$RUN" | awk 'NR==2{print $4}')MiB"
have python3 || die "python3 missing"
python3 -c 'import sys; assert sys.version_info >= (3, 9)' || die "python3 >= 3.9 required"
[ -n "${KAGGLE_API_TOKEN:-}" ] || die "KAGGLE_API_TOKEN not set"
have "$RUNPODCTL" || warn "runpodctl missing: results come back only through the RP_REPORT block"
if [ -z "${SKIP_PIP:-}" ]; then
  step "pip install kaggle" "$T_BOOT" python3 -m pip install --quiet --disable-pip-version-check \
    "kaggle==2.2.4" six ${PIP_EXTRA:-} || die "could not install the kaggle CLI"
fi
have "$KAGGLE" || die "kaggle CLI not on PATH after install"
progress

# ---- auth probe: the cheapest possible call, so a bad token or un-accepted rules show in seconds ---
stage auth
rc=0
step "kaggle auth probe" "$T_AUTH" "$KAGGLE" competitions files "$COMP" --page-size 1 >"$RUN/auth.out" 2>&1 || rc=$?
if [ "$rc" -ne 0 ]; then
  tail -n 5 "$RUN/auth.out" | cut -c1-200
  if grep -qiE "401|authenticat|unauthor|expired" "$RUN/auth.out"; then die "token rejected or expired"; fi
  if grep -qiE "403|forbidden|rules|accept" "$RUN/auth.out"; then die "no access: competition rules not accepted?"; fi
  die "kaggle probe failed (rc=$rc)"
fi
echo "auth-ok"
progress

# ---- listing: know exactly what we expect before downloading anything ---------------------------
stage listing
: >"$RUN/listing.csv"
tok=""
for _ in $(seq 1 12); do
  args=(competitions files "$COMP" --page-size 200 -v)
  [ -n "$tok" ] && args+=(--page-token "$tok")
  rc=0
  step "kaggle listing" "$T_LIST" "$KAGGLE" "${args[@]}" >"$RUN/page.out" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || die "listing failed (rc=$rc)"
  grep -E '^[^ ]+,[0-9]+,' "$RUN/page.out" >>"$RUN/listing.csv" || true
  tok=$(sed -n 's/^Next Page Token = //p' "$RUN/page.out" | head -1)
  [ -n "$tok" ] || break
done
awk -F, -v snaps="${WANT_SNAPSHOTS:-0}" -v ids=",${SNAP_IDS:-}," \
  '{ id = $1; sub(/^snapshots\//, "", id); sub(/\.tgz$/, "", id) }
   $1=="tasks.jsonl" || $1 ~ /^graphs\// || $1 ~ /^embeddings\// ||
   (snaps=="1" && $1 ~ /^wheels\//) ||
   (snaps=="1" && $1 ~ /^snapshots\// && (ids==",," || index(ids, "," id ","))) {print $1" "$2}' \
  "$RUN/listing.csv" >"$RUN/want.tsv"
n_g=$(grep -c '^graphs/' "$RUN/want.tsv" || true)
n_e=$(grep -c '^embeddings/' "$RUN/want.tsv" || true)
n_t=$(grep -c '^tasks.jsonl ' "$RUN/want.tsv" || true)
total=$(wc -l <"$RUN/want.tsv")
bytes=$(awk '{s+=$2} END{print s+0}' "$RUN/want.tsv")
mib=$((bytes / 1048576))
echo "expect: tasks.jsonl=$n_t graphs=$n_g embeddings=$n_e total=$total files ${mib}MiB"
[ "$n_t" -eq 1 ] || die "listing has no tasks.jsonl (shape changed?)"
[ "$n_g" -ge "$MIN_FILES" ] && [ "$n_e" -ge "$MIN_FILES" ] || die "listing too small (graphs=$n_g embeddings=$n_e)"
{ [ "$mib" -ge "${MIN_MIB:-300}" ] && [ "$mib" -le "${MAX_MIB:-3000}" ]; } || die "expected size ${mib}MiB outside ${MIN_MIB:-300}-${MAX_MIB:-3000}MiB"
free=$(df -Pm "$RUN" | awk 'NR==2{print $4}')
pct="${DISK_PERCENT:-300}" # free space needed, as a percent of the download (300 = zips plus unpacked)
[ "$free" -ge $((mib * pct / 100)) ] || die "disk: ${free}MiB free, need ${pct}% of ${mib}MiB"
progress

# ---- downloader -----------------------------------------------------------------------------
unzip_py() { python3 -c 'import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$1" "$2"; }
dl_one() {
  local name=$1 size=$2 dest="$DATA/$1" dir tries=0
  dir=$(dirname "$dest")
  mkdir -p "$dir"
  while [ "$tries" -lt 3 ]; do
    tries=$((tries + 1))
    if timeout "$T_FILE" "$KAGGLE" competitions download "$COMP" -f "$name" -p "$dir" -q >>"$RUN/dl.log" 2>&1; then
      if [ ! -f "$dest" ] && [ -f "$dest.zip" ]; then unzip_py "$dest.zip" "$dir" && rm -f "$dest.zip"; fi
      if [ -f "$dest" ] && [ "$(stat -c %s "$dest")" = "$size" ]; then
        echo "$name" >>"$RUN/dl.done"
        sleep "${DL_SLEEP:-0}" # pause between files if the API starts answering 429
        return 0
      fi
    fi
    sleep $((tries * 2))
  done
  echo "$name" >>"$RUN/dl.failed"
  return 1
}
export -f dl_one unzip_py
export RUN DATA COMP KAGGLE T_FILE DL_SLEEP

# ---- smoke: the real download path on 3 files, then a projected total time ----------------------
stage smoke
: >"$RUN/dl.done"
t0=$(now)
for pat in '^tasks.jsonl ' '^graphs/' '^embeddings/'; do
  line=$(grep -m1 -E "$pat" "$RUN/want.tsv")
  # shellcheck disable=SC2086
  dl_one $line || { tail -n 5 "$RUN/dl.log" | cut -c1-200; die "smoke download failed: ${line%% *}"; }
done
dt=$(($(now) - t0))
python3 - "$DATA" <<'PY' || die "smoke files are not what we expected"
import json, sys, zipfile, glob
d = sys.argv[1]
first = open(d + "/tasks.jsonl").readline()
t = json.loads(first)
assert {"instance_id", "base_commit", "patch"} <= set(t), sorted(t)
g = json.load(open(glob.glob(d + "/graphs/*.json")[0]))
assert "nodes" in g, list(g)
assert zipfile.ZipFile(glob.glob(d + "/embeddings/*.npz")[0]).namelist()
print("smoke-ok: tasks.jsonl, one graph and one embedding parse")
PY
proj=$((dt * total / DL_PAR / 3 + 1))
echo "smoke: 3 files in ${dt}s; projected full download about ${proj}s with ${DL_PAR} parallel"
[ "$proj" -le "$T_DL" ] || die "projected download ${proj}s exceeds budget ${T_DL}s"
progress

# ---- download ---------------------------------------------------------------------------------
stop_dl() {
  kill -TERM "$DL_PID" 2>/dev/null || true
  if have pkill; then pkill -TERM -P "$DL_PID" 2>/dev/null || true; fi
}
stage download
: >"$RUN/dl.failed"
awk 'NR==FNR{d[$1]=1; next} !($1 in d)' "$RUN/dl.done" "$RUN/want.tsv" >"$RUN/todo.txt"
xargs -L1 -P "$DL_PAR" bash -c 'dl_one "$@"' _ <"$RUN/todo.txt" &
DL_PID=$!
t0=$(now)
last_done=0
last_change=$t0
todo=$(wc -l <"$RUN/todo.txt")
while kill -0 "$DL_PID" 2>/dev/null; do
  sleep "$DL_POLL"
  done_n=$(wc -l <"$RUN/dl.done")
  el=$(($(now) - t0))
  mb=$(du -sm "$DATA" | cut -f1)
  rate=$(awk -v m="$mb" -v e="$el" 'BEGIN{printf "%.2f", (e>0)?m/e:0}')
  eta=$(awk -v d="$done_n" -v t="$total" -v e="$el" 'BEGIN{printf "%d", (d>0)?e*(t-d)/d:-1}')
  echo "download $done_n/$total files ${mb}MiB rate=${rate}MiB/s elapsed=${el}s eta=${eta}s failed=$(wc -l <"$RUN/dl.failed")"
  if [ "$done_n" -gt "$last_done" ]; then
    last_done=$done_n
    last_change=$(now)
    progress
  elif [ $(($(now) - last_change)) -gt "$STALL_SECS" ]; then
    stop_dl
    die "download stalled: no new file for ${STALL_SECS}s at $done_n/$total"
  fi
  if [ "$el" -gt 120 ] && awk -v r="$rate" -v m="$MIN_RATE_MBS" 'BEGIN{exit !(r<m)}'; then
    warn "download slow: ${rate}MiB/s (< ${MIN_RATE_MBS})"
  fi
  if [ "$el" -gt 180 ] && [ "$eta" -gt 0 ] && [ "$eta" -gt $((T_DL - el)) ]; then
    stop_dl
    die "download projected to finish after the budget (eta ${eta}s, left $((T_DL - el))s)"
  fi
  if [ "$el" -gt "$T_DL" ]; then
    stop_dl
    die "download timed out after ${T_DL}s"
  fi
done
rc=0
wait "$DL_PID" || rc=$?
[ "$(wc -l <"$RUN/dl.failed")" -eq 0 ] || die "$(wc -l <"$RUN/dl.failed") files failed to download (first: $(head -1 "$RUN/dl.failed"))"
got=$(wc -l <"$RUN/dl.done")
[ "$got" -eq "$total" ] || die "downloaded $got of $total files (xargs rc=$rc)"
echo "download complete: $got files, $(du -sm "$DATA" | cut -f1)MiB"
progress

# ---- analyse ---------------------------------------------------------------------------------
stage analyze
step "explore" "$T_ANALYZE" python3 "${EXPLORE_PY:-$HERE/explore.py}" "$DATA" "$OUT" || die "explore.py failed"
python3 - "$OUT/report.json" <<'PY' || true
import json, sys
r = json.load(open(sys.argv[1]))
if "with_graph" not in r:  # not the graph analysis (the GPU eval writes its own report)
    sys.exit(0)
if r["tasks"] < 100:
    print("WARN only", r["tasks"], "tasks parsed")
if r["with_graph"] < 0.9 * r["tasks"]:
    print("WARN graphs found for", r["with_graph"], "of", r["tasks"], "tasks")
if r["tasks_with_mapped_node"] < 0.5 * max(1, r["with_graph"]):
    print("WARN fewer than half of tasks map a gold patch to a graph node:", r["tasks_with_mapped_node"])
PY
stage done
