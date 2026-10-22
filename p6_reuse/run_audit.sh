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
mkdir -p "$OUT"

log() { echo "$(date '+%F %T') $*" | tee -a "$OUT/progress.txt"; }

split() {  # suite field
  "$PY" -c "import json,sys; print(' '.join(json.load(open('p6_reuse/data/split.json'))['suites'][sys.argv[1]][sys.argv[2]]))" "$@"
}

# The endpoint, key and timeouts come from .env (the runner reads it too), so check the model through the same path.
"$PY" -c "from agent_framework.runner_config import load_runner_env; load_runner_env(); \
from agent_framework.inference import check_local_models; check_local_models(['$MODEL'])" 2>>"$OUT/log.txt" \
  || { log "ABORT: $MODEL is not reachable through the LM Studio endpoint in .env (see $OUT/log.txt)"; exit 2; }

FAILED=0
for suite in ${SUITES:-slack travel workspace}; do
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
