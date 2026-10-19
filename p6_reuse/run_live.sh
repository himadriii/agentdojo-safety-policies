#!/usr/bin/env bash
# P6 final live runs on a local MLX-Serve server (plan KTD10, KTD11).
#
# usage: MODEL=<served gpt-oss-20b id> bash p6_reuse/run_live.sh [user-tasks-per-suite]
#
# Stage 0 smoke-tests MODEL and aborts the grid if no tool call executes or the reviewer never
# parses. Stages then run in order of importance; each runner call is cached by AgentDojo per
# pipeline name, so re-running the script resumes where it stopped.
set -u
cd "$(dirname "$0")/.."

MODEL="${MODEL:?set MODEL to the served model id, e.g. gpt-oss-20b-MXFP4-Q8}"
N="${1:-4}"
PY="${PYTHON:-.venv/bin/python}"
OUT="${OUTDIR:-results/p6_live}"
export MLX_BASE_URL="${MLX_BASE_URL:-http://127.0.0.1:11234/v1}"
mkdir -p "$OUT"

log() { echo "$(date '+%F %T') $*" | tee -a "$OUT/progress.txt"; }

split() {  # suite field [limit]
  "$PY" -c "import json,sys; s=json.load(open('p6_reuse/data/split.json'))['suites'][sys.argv[1]][sys.argv[2]]; \
print(' '.join(s[:int(sys.argv[3])] if len(sys.argv) > 3 else s))" "$@"
}

stage() {  # suite policy k attack
  local suite=$1 policy=$2 k=$3 attack=$4 users extra=()
  users=$(split "$suite" user_tasks "$N")
  [ "$attack" != none ] && extra=(--injection-tasks $(split "$suite" injection_tasks))
  log "START $suite $policy k=$k $attack"
  # shellcheck disable=SC2086
  if "$PY" -W ignore -m agent_framework.runner --provider mlx --llm "$MODEL" --policy "$policy" \
      --reviewer local_llm --suite "$suite" --attack "$attack" --user-tasks $users "${extra[@]}" \
      --k "$k" --outdir "$OUT" >> "$OUT/log.txt" 2>&1; then
    log "DONE  $suite $policy k=$k $attack"
  else
    log "FAILED $suite $policy k=$k $attack (see $OUT/log.txt)"
  fi
}

suite_grid() {  # suite
  for attack in important_instructions none; do
    stage "$1" approval_reuse 2 "$attack"
    stage "$1" full_escalate 2 "$attack"
    stage "$1" full_approve 0 "$attack"
  done
  for k in 1 3; do
    for attack in important_instructions none; do
      stage "$1" approval_reuse "$k" "$attack"
      stage "$1" full_escalate "$k" "$attack"
    done
  done
  for attack in important_instructions none; do
    stage "$1" similarity_reuse 2 "$attack"   # comparison: similarity reuse without key arguments
  done
}

log "stage 0: smoke test on $MODEL"
SMOKE_OUTDIR="$OUT/smoke" bash p6_reuse/smoke.sh "$MODEL" 2 >> "$OUT/log.txt" 2>&1 \
  || { log "ABORT: smoke test failed (see $OUT/log.txt)"; exit 1; }

for suite in slack travel workspace; do
  suite_grid "$suite"
done
log "ALL STAGES DONE"
