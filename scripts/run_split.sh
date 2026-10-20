#!/usr/bin/env bash
# usage: bash scripts/run_split.sh <policy> <dev|heldout> "<k values>" <outdir>
set -euo pipefail
source scripts/team_settings.sh
POLICY=$1; SPLIT=$2; KS=$3; OUT=$4
for F in splits/banking_v1.2.json splits/slack_v1.2.json splits/travel_v1.2.json; do
  python -m agent_framework.runner --provider "$PROVIDER" --policy "$POLICY" --llm "$AGENT_MODEL" \
    --reviewer "$REVIEWER" --reviewer-model "$REVIEWER_MODEL" --attack "$ATTACK" \
    --split-file "$F" --split "$SPLIT" --k $KS --outdir "$OUT"
done
