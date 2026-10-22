#!/usr/bin/env bash
# P6 dev run on the shared dev split: agent on LM Studio (ngrok URL + key from .env), reviewer on Groq gpt-oss-120b.
# Same runner arguments as scripts/run_split.sh, but the provider split lives here so shared scripts stay untouched.
#
# usage: bash p6_reuse/run_dev.sh [policy] ["k values"] [outdir]
set -euo pipefail
cd "$(dirname "$0")/.."
POLICY="${1:-approval_reuse}"; KS="${2:-2}"; OUT="${3:-results/dev/P6}"
PY="${PYTHON:-.venv/bin/python}"

export REVIEWER_PROVIDER=groq
REVIEWER_MODEL=openai/gpt-oss-120b
ATTACK=important_instructions

for F in splits/banking_v1.2.json splits/slack_v1.2.json splits/travel_v1.2.json; do
  # shellcheck disable=SC2086
  "$PY" -W ignore -m agent_framework.runner --provider lmstudio --policy "$POLICY" \
    --reviewer llm --reviewer-model "$REVIEWER_MODEL" --attack "$ATTACK" \
    --split-file "$F" --split dev --k $KS --outdir "$OUT"
done
"$PY" scripts/verify_traces.py "$OUT"
