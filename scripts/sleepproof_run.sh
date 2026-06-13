#!/usr/bin/env bash
# Sleep-proof, detached launcher for long-running jobs (brms fits, loop
# iterations). Holds a SYSTEM-sleep assertion for the job's whole lifetime and
# detaches it from the controlling terminal so closing the session / SSH (a
# SIGHUP) cannot kill it.
#
# Why caffeinate -s (not -i): -i only blocks *idle* sleep; a closed lid still
# sleeps. -s holds PreventSystemSleep — survives a closed lid — and is valid
# while on AC power. (On battery, macOS ignores -s; keep the machine on AC.)
#
# Usage:
#   scripts/sleepproof_run.sh <logfile> <command> [args...]
# Example:
#   scripts/sleepproof_run.sh logs/fit_c0.log Rscript fit_m3.R
#
# Prints the detached PID. The job keeps running after this script returns.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <logfile> <command> [args...]" >&2
  exit 2
fi

LOGFILE="$1"; shift
mkdir -p "$(dirname "$LOGFILE")"

# Power sanity: warn loudly if not on AC (caffeinate -s is a no-op on battery).
# Capture-then-match (not `grep -q`) to avoid SIGPIPE/pipefail false negatives.
PS_OUT="$(pmset -g ps || true)"
if [[ "$PS_OUT" != *"AC Power"* ]]; then
  echo "WARNING: not on AC power — 'caffeinate -s' will NOT hold. Plug in first." >&2
fi

# nohup + & + disown: fully detached from this shell's job table and immune to
# SIGHUP. caffeinate -s wraps the command, so the assertion lives exactly as
# long as the command does (caffeinate exits when its child exits).
nohup caffeinate -s "$@" > "$LOGFILE" 2>&1 &
PID=$!
disown "$PID" 2>/dev/null || true

echo "launched PID=$PID  log=$LOGFILE"
echo "  command: caffeinate -s $*"
