#!/usr/bin/env bash
# P3: FINAL standalone runs on the HELD-OUT tasks (12 user tasks x 4 injection tasks in split.json),
# through the shared runner with the frozen model. Run only after the model is frozen.
#
# usage: final_runs.sh <shard 0..N-1> <N shards> <env var holding the Groq key>
# Each shard takes every N-th held-out user task, so shards can run in parallel with separate keys.
#
# Stages are ordered by importance, so the most valuable results exist first if the Groq daily
# token cap (200k tokens/day/org on the free tier) stops the sweep. One runner process per user
# task; on an API error the script waits 10 minutes and retries that task (up to 72 times, 12 hours). Finished tasks are cached: re-run the script to resume.
set -u
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export GROQ_API_KEY="${!3}"
SHARD="$1"; NSH="$2"
PY=.venv/Scripts/python
OUT=results/p3_final
mkdir -p "$OUT"
USERS=$($PY -c "import json;u=json.load(open('p3_risk/data/split.json'))['test_user_tasks'];print(' '.join(t for i,t in enumerate(u) if i % $NSH == $SHARD))")
# Only injection task 2 can run on Groq's free tier. Held-out tasks 7, 9 and 10 make the agent read whole
# inboxes / all files, and a single request then exceeds the 8000 tokens/minute limit (HTTP 413). AgentDojo
# first runs each selected injection task as a plain user task, so that crash happens before any attack
# pair starts. Set INJS to include them on a tier with higher limits.
INJS="${INJS:-injection_task_2}"

run() {  # policy attack k
  for u in $USERS; do
    extra=(); [ "$2" != "none" ] && extra=(--injection-tasks $INJS)
    # On a Groq quota error (429, daily token cap) wait and retry the same task instead of skipping it.
    # Finished tasks are cached by the runner, so a retry only repeats the unfinished pairs.
    for attempt in $(seq 1 ${MAX_ATTEMPTS:-72}); do
      if $PY -W ignore -m agent_framework.runner --provider groq --policy "$1" --llm openai/gpt-oss-20b \
          --attack "$2" --user-tasks "$u" "${extra[@]}" --k "$3" --outdir "$OUT" \
          > "$OUT/last_attempt.txt" 2>&1; then
        cat "$OUT/last_attempt.txt" >> "$OUT/log_shard$SHARD.txt"
        break
      fi
      cat "$OUT/last_attempt.txt" >> "$OUT/log_shard$SHARD.txt"
      # HTTP 413 = one request is over Groq's 8000 tokens/minute limit. It is deterministic, so
      # retrying cannot help: record the task as unrunnable on this tier and move on.
      if grep -q "Error code: 413" "$OUT/last_attempt.txt"; then
        echo "$(date +%H:%M) SKIPPED (413 request too large): $1 $2 k=$3 $u" >> "$OUT/failures.txt"
        break
      fi
      echo "$(date +%H:%M) retry $attempt: $1 $2 k=$3 $u" >> "$OUT/failures.txt"
      sleep 600
    done
  done
  echo "$(date +%H:%M) STAGE DONE $1 $2 k=$3 (shard $SHARD)" >> "$OUT/progress.txt"
}

run supervised_risk important_instructions 2
run full_approve    important_instructions 0
run supervised_risk none                   2
run full_approve    none                   0
run supervised_risk important_instructions 0
run supervised_risk important_instructions 5
echo "ALL STAGES DONE (shard $SHARD)" >> "$OUT/progress.txt"
