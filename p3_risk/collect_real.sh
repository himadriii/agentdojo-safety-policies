#!/usr/bin/env bash
# P3: collect real agent trajectories on DEV tasks only (full_approve = no filtering), for
# validating / augmenting the risk model. Held-out test tasks are never run here.
#
# usage: collect_real.sh <attack: none|important_instructions> <env var holding the Groq key> [injection_task ...]
#
# One runner process per task, so a Groq API error (malformed tool call -> 400, request over the
# 8000 tokens/minute limit -> 413) loses only that task instead of the whole sweep. Finished
# tasks are cached by the runner, so the script can simply be re-run to resume.
set -u
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
export GROQ_API_KEY="${!2}"
ATTACK="$1"; KEYVAR="$2"; shift 2
PY=.venv/Scripts/python
USERS=$($PY -c "import json;print(' '.join(json.load(open('p3_risk/data/split.json'))['dev_user_tasks']))")
INJS=("$@"); [ "$ATTACK" = "none" ] && INJS=("")
for u in $USERS; do
  for i in "${INJS[@]}"; do
    extra=(); [ -n "$i" ] && extra=(--injection-tasks "$i")
    $PY -W ignore -m agent_framework.runner --provider groq --policy full_approve --llm openai/gpt-oss-20b \
        --attack "$ATTACK" --user-tasks "$u" "${extra[@]}" --k 0 --outdir results/p3_collect \
        >> "results/p3_collect_$KEYVAR.log" 2>&1 || echo "FAILED $ATTACK $u $i" >> "results/p3_collect_failures.log"
  done
done
echo "DONE $ATTACK $KEYVAR" >> "results/p3_collect_failures.log"
