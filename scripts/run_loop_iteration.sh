#!/usr/bin/env bash
# Run ONE model-search loop iteration, sleep-proof and detached.
#
# Steps (model_loop_spec.md §3 iteration contract):
#   1. Verify the frozen split parquets still match loop_split_manifest.txt
#      (ABORT on drift — the whole point of the frozen test is that it can't move).
#   2. Resolve the next candidate: lowest id in analysis/loop_candidates.tsv with
#      NO row in exports/run_log.csv (run_log is the loop's memory).
#   3. Require analysis/fit_candidate_<ID>.R to exist (the Ralph loop agent
#      authors it per §4 BEFORE calling this launcher).
#   4. Launch it under scripts/sleepproof_run.sh (caffeinate -s + nohup + disown).
#   5. Verify liveness: R process burning CPU, sleep assertion held, log advances
#      past iteration 50 (where earlier fits died). Only then report "running".
#
# Usage:
#   scripts/run_loop_iteration.sh            # resolve + launch the next candidate
#   scripts/run_loop_iteration.sh --dry-run  # resolve + verify plumbing, fit nothing
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAND="$ROOT/analysis/loop_candidates.tsv"
RUNLOG="$ROOT/exports/run_log.csv"
MANIFEST="$ROOT/exports/loop_split_manifest.txt"
TRAIN="$ROOT/exports/loop_train.parquet"
TEST="$ROOT/exports/loop_test.parquet"

DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1

# ── 1. Frozen-split integrity ────────────────────────────────────────────────
[[ -f "$MANIFEST" ]] || { echo "ABORT: manifest missing ($MANIFEST). Run scripts/materialize_loop_split.py first." >&2; exit 4; }
for pq in "$TRAIN" "$TEST"; do
  [[ -f "$pq" ]] || { echo "ABORT: frozen parquet missing: $pq" >&2; exit 4; }
done
check_hash() {  # $1 = parquet path, $2 = basename to find in manifest
  local want have
  want=$(grep -A1 "^${2} " "$MANIFEST" | grep -oE 'sha256=[0-9a-f]+' | cut -d= -f2)
  have=$(shasum -a 256 "$1" | cut -d' ' -f1)
  [[ "$want" == "$have" ]] || { echo "ABORT: $2 hash drift — frozen split changed. want=$want have=$have" >&2; exit 5; }
}
check_hash "$TRAIN" "loop_train.parquet"
check_hash "$TEST"  "loop_test.parquet"
echo "[ok] frozen split hashes verified against manifest"

# ── 2. Resolve next un-run candidate ─────────────────────────────────────────
next_id=""; next_script=""
while IFS=$'\t' read -r id script _; do
  [[ "$id" =~ ^#|^$ ]] && continue
  if grep -q "$id" "$RUNLOG" 2>/dev/null; then continue; fi   # already has a run_log row
  next_id="$id"; next_script="$script"; break
done < "$CAND"

if [[ -z "$next_id" ]]; then
  echo "QUEUE EXHAUSTED — every candidate in $(basename "$CAND") has a run_log row. STOP."
  exit 0
fi
echo "[next] candidate=$next_id  script=analysis/$next_script"

FITR="$ROOT/analysis/$next_script"
TS=$(date +%Y%m%d_%H%M%S)
LOG="$ROOT/logs/fit_${next_id}_${TS}.log"

# ── dry-run: prove the sleep-proof plumbing, report script readiness, fit nothing
if [[ $DRY -eq 1 ]]; then
  echo "[dry-run] verifying sleep-proof plumbing with a smoke job..."
  "$ROOT/scripts/sleepproof_run.sh" "$ROOT/logs/_loop_preflight_smoke.log" sleep 15 >/tmp/_smoke.out
  smoke_pid=$(grep -oE 'PID=[0-9]+' /tmp/_smoke.out | cut -d= -f2)
  # Check immediately (no delay) while the 15s smoke is certainly still alive.
  assert_ok=0; pid_ok=0
  # Capture then substring-match — avoids `grep -q | pipefail` SIGPIPE flakiness.
  assertions="$(pmset -g assertions)"
  [[ "$assertions" == *PreventSystemSleep* ]] && assert_ok=1
  kill -0 "$smoke_pid" 2>/dev/null && pid_ok=1
  if [[ $assert_ok -eq 1 && $pid_ok -eq 1 ]]; then
    echo "[dry-run][ok] sleep assertion held + smoke job detached (pid $smoke_pid)"
    kill "$smoke_pid" 2>/dev/null || true   # tidy up the smoke job
  else
    echo "[dry-run][FAIL] plumbing check failed (assert=$assert_ok pid_alive=$pid_ok)" >&2; exit 6
  fi
  if [[ -f "$FITR" ]]; then
    echo "[dry-run][ok] next candidate $next_id ready: analysis/$next_script exists"
  else
    echo "[dry-run][pending] analysis/$next_script not authored yet — loop agent copies"
    echo "                   analysis/fit_candidate_TEMPLATE.R and applies the $next_id formula (§4)"
  fi
  echo "[dry-run] would launch: (cd analysis) sleepproof_run.sh $LOG Rscript $next_script"
  exit 0
fi

# ── 3. Require the candidate's fit script (real launch) ──────────────────────
if [[ ! -f "$FITR" ]]; then
  echo "BLOCKED: $FITR does not exist yet."
  echo "  The loop agent must author it from analysis/fit_candidate_TEMPLATE.R: apply the"
  echo "  $next_id formula (model_loop_spec.md §4), keep file_refit=\"always\", read"
  echo "  loop_train.parquet, evaluate on loop_test.parquet, log via run_tracker.R."
  exit 3
fi

# ── 4. Real launch: Rscript must run from analysis/ (relative paths). Capture
# the detached PID so liveness can sample the process tree's CPU-time.
launch_out="$("$ROOT/scripts/sleepproof_run.sh" "$LOG" \
                bash -c "cd '$ROOT/analysis' && exec Rscript '$next_script'")"
echo "$launch_out"
ROOT_PID="$(echo "$launch_out" | grep -oE 'PID=[0-9]+' | head -1 | cut -d= -f2)"

# ── 5. Verify liveness via CPU-TIME DELTA (robust to stdout buffering) ────────
# Stan/brms progress logs are block-buffered even under a pty, so "iter > 50 in
# the log" can lag a healthy fit by an hour. A *suspended* process (the way
# earlier fits died — system sleep) freezes CPU-time; a live one accumulates it.
# So: confirm the assertion is held AND the process tree's CPU-time climbs.
descendants() { local p="$1" k; echo "$p"; for k in $(pgrep -P "$p" 2>/dev/null || true); do descendants "$k"; done; }
tree_cpu_secs() {
  local csv; csv="$(descendants "$1" | paste -sd, -)"
  ps -o time= -p "$csv" 2>/dev/null | awk -F: '
    {s=0; if(NF==3)s=$1*3600+$2*60+$3; else if(NF==2)s=$1*60+$2; else s=$1; tot+=s} END{printf "%.1f", tot}'
}
sleep 45   # let Stan compile + start sampling
c1="$(tree_cpu_secs "$ROOT_PID")"
sleep 30
c2="$(tree_cpu_secs "$ROOT_PID")"
assertions="$(pmset -g assertions)"; held=0; [[ "$assertions" == *PreventSystemSleep* ]] && held=1
delta="$(awk -v a="$c1" -v b="$c2" 'BEGIN{printf "%.1f", b-a}')"
iter_seen="$(grep -oE "Iteration: +[0-9]+ / 2000" "$LOG" 2>/dev/null | tail -1 || true)"

echo "[verify] CPU-time ${c1}s -> ${c2}s (Δ ${delta}s over 30s)  assertion_held=$held  log:'${iter_seen}'"
if [[ $held -eq 1 ]] && awk -v d="$delta" 'BEGIN{exit !(d>5)}'; then
  echo "[ok] $next_id genuinely progressing (CPU-time climbing, sleep assertion held)"
  exit 0
fi
if ! kill -0 "$ROOT_PID" 2>/dev/null; then
  echo "FAIL: $next_id process exited during verification" >&2; tail -8 "$LOG" >&2; exit 1
fi
echo "WARN: $next_id CPU-time not climbing (Δ ${delta}s) — possible stall, inspect $LOG" >&2; exit 2
