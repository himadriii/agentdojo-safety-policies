#!/usr/bin/env bash
# P6 live leak audit: large budget, real reviewer, shadow review of every reuse approval.
#
# usage: bash p6_reuse/run_audit.sh [k]            (default k=10, so the budget never starves a task)
#
# Same model, reviewer and held-out split as run_live.sh, served by LM Studio. A large k removes the
# budget starvation that hid attack outcomes in the k=1..3 grid. --shadow-audit asks the reviewer what
# it would say about each call the gate approves from memory (logged, never enforced, no budget spent).
# Runner calls are cached per pipeline name, so re-running the script resumes where it stopped.
set -u
cd "$(dirname "$0")/.."

K="${1:-10}"
MODEL="${MODEL:-openai/gpt-oss-20b}"
PY="${PYTHON:-.venv/bin/python}"
OUT="${OUTDIR:-results/p6_live_audit}"
BASE_URL="${LMSTUDIO_BASE_URL:-http://127.0.0.1:1234/v1}"
export LMSTUDIO_BASE_URL="$BASE_URL"
mkdir -p "$OUT"

log() { echo "$(date '+%F %T') $*" | tee -a "$OUT/progress.txt"; }

split() {  # suite field
  "$PY" -c "import json,sys; print(' '.join(json.load(open('p6_reuse/data/split.json'))['suites'][sys.argv[1]][sys.argv[2]]))" "$@"
}

curl -sf "$BASE_URL/models" | grep -q "$MODEL" || { log "ABORT: $MODEL is not served at $BASE_URL"; exit 2; }

FAILED=0
for suite in slack travel workspace; do
  users=$(split "$suite" user_tasks); injections=$(split "$suite" injection_tasks)
  for attack in important_instructions none; do
    for policy in approval_reuse similarity_reuse full_escalate; do
      extra=()
      [ "$attack" != none ] && extra=(--injection-tasks $injections)
      log "START $suite $policy k=$K $attack"
      # ${extra[@]+...}: an empty array under `set -u` aborts on macOS's bash 3.2
      if "$PY" -W ignore -m agent_framework.runner --provider lmstudio --llm "$MODEL" --policy "$policy" \
          --reviewer llm --suite "$suite" --attack "$attack" --user-tasks $users \
          ${extra[@]+"${extra[@]}"} --k "$K" --shadow-audit --outdir "$OUT" >> "$OUT/log.txt" 2>&1; then
        log "DONE  $suite $policy k=$K $attack"
      else
        log "FAILED $suite $policy k=$K $attack (see $OUT/log.txt)"; FAILED=$((FAILED + 1))
      fi
    done
  done
done
[ "$FAILED" -gt 0 ] && { log "FINISHED WITH $FAILED FAILED STAGE(S); rerun to resume them"; exit 1; }
log "ALL STAGES DONE"
