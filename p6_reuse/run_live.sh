#!/usr/bin/env bash
# P6 final live runs on a local MLX-Serve server (plan KTD10, KTD11).
#
# usage: MODEL=<served gpt-oss-20b id> bash p6_reuse/run_live.sh [user-tasks-per-suite]
#        DRY_RUN=1 MODEL=x bash p6_reuse/run_live.sh     # list the stages without running anything
#
# Grid: k = 1, 2, 5 for approval_reuse and full_escalate, full_approve at k=0, similarity_reuse at k=2, on every
# held-out user task (default 12, the largest suite) with and without the attack. approval_reuse is the current
# gate, drill-down included. Results are cached per pipeline name, so OUTDIR is stamped with the policy
# revision and the script refuses to mix runs from different revisions.
#
# Stage 0 smoke-tests MODEL and aborts the grid if no tool call executes or the reviewer never
# parses. Stages then run in order of importance; each runner call is cached by AgentDojo per
# pipeline name, so re-running the script resumes where it stopped.
set -u
cd "$(dirname "$0")/.."

MODEL="${MODEL:?set MODEL to the served model id, e.g. gpt-oss-20b-MXFP4-Q8}"
N="${1:-12}"
case "$N" in ''|*[!0-9]*|0) echo "user-tasks-per-suite must be a positive integer, got '$N'"; exit 2 ;; esac
PY="${PYTHON:-.venv/bin/python}"
OUT="${OUTDIR:-results/p6_live_g2}"
export MLX_BASE_URL="${MLX_BASE_URL:-http://127.0.0.1:11234/v1}"
mkdir -p "$OUT"

log() { echo "$(date '+%F %T') $*" | tee -a "$OUT/progress.txt"; }

# The gate under test must be the one with drill-down reuse, and OUT must not hold runs of another revision.
"$PY" -c "from agent_framework.registry import POLICIES; assert POLICIES['approval_reuse']().drill_down" \
  || { echo "approval_reuse has no drill-down reuse: wrong checkout?"; exit 2; }
REV="$(git rev-parse --short HEAD) policy-diff:$(git diff HEAD -- agent_framework/policies/approval_reuse \
  agent_framework/policy.py agent_framework/tools_executor.py | shasum | cut -c1-10)"
if [ -f "$OUT/policy_rev.txt" ] && [ "$(cat "$OUT/policy_rev.txt")" != "$REV" ]; then
  echo "$OUT holds runs from policy revision '$(cat "$OUT/policy_rev.txt")', not '$REV'. Use a new OUTDIR."; exit 2
fi
echo "$REV" > "$OUT/policy_rev.txt"

split() {  # suite field [limit]
  "$PY" -c "import json,sys; s=json.load(open('p6_reuse/data/split.json'))['suites'][sys.argv[1]][sys.argv[2]]; \
print(' '.join(s[:int(sys.argv[3])] if len(sys.argv) > 3 else s))" "$@"
}

FAILED=0

fail() {  # message
  log "FAILED $*"
  FAILED=$((FAILED + 1))
}

stage() {  # suite policy k attack
  local suite=$1 policy=$2 k=$3 attack=$4 users injections extra=()
  # An empty task list makes the runner run every task in the suite, so refuse it.
  users=$(split "$suite" user_tasks "$N") && [ -n "$users" ] \
    || { fail "$suite $policy k=$k $attack (no user tasks from p6_reuse/data/split.json)"; return; }
  if [ "$attack" != none ]; then
    injections=$(split "$suite" injection_tasks) && [ -n "$injections" ] \
      || { fail "$suite $policy k=$k $attack (no injection tasks from p6_reuse/data/split.json)"; return; }
    # shellcheck disable=SC2206
    extra=(--injection-tasks $injections)
  fi
  log "START $suite $policy k=$k $attack"
  [ -n "${DRY_RUN:-}" ] && { log "DRY_RUN: $suite $policy k=$k $attack users=[$users] injections=[${injections:-}]"; return; }
  # shellcheck disable=SC2086
  # ${extra[@]+...}: an empty array under `set -u` aborts on macOS's bash 3.2
  if "$PY" -W ignore -m agent_framework.runner --provider mlx --llm "$MODEL" --policy "$policy" \
      --reviewer local_llm --suite "$suite" --attack "$attack" --user-tasks $users ${extra[@]+"${extra[@]}"} \
      --k "$k" --outdir "$OUT" >> "$OUT/log.txt" 2>&1; then
    log "DONE  $suite $policy k=$k $attack"
  else
    fail "$suite $policy k=$k $attack (see $OUT/log.txt)"
  fi
}

suite_grid() {  # suite
  for attack in important_instructions none; do
    stage "$1" approval_reuse 2 "$attack"
    stage "$1" full_escalate 2 "$attack"
    stage "$1" full_approve 0 "$attack"
  done
  for k in 1 5; do
    for attack in important_instructions none; do
      stage "$1" approval_reuse "$k" "$attack"
      stage "$1" full_escalate "$k" "$attack"
    done
  done
  for attack in important_instructions none; do
    stage "$1" similarity_reuse 2 "$attack"   # comparison: similarity reuse without key arguments
  done
}

log "policy revision $REV"
if [ -z "${DRY_RUN:-}" ]; then
  log "stage 0: smoke test on $MODEL"
  SMOKE_OUTDIR="$OUT/smoke" bash p6_reuse/smoke.sh "$MODEL" 2 >> "$OUT/log.txt" 2>&1 \
    || { log "ABORT: smoke test failed (see $OUT/log.txt)"; exit 1; }
fi

for suite in slack travel workspace; do
  suite_grid "$suite"
done
if [ "$FAILED" -gt 0 ]; then
  log "GRID FINISHED WITH $FAILED FAILED STAGE(S); rerun to resume them"
  exit 1
fi
log "ALL STAGES DONE"
