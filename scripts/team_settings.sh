#!/usr/bin/env bash
# The one command for shared dev/held-out runs.
# Usage: scripts/team_settings.sh <policy> <owner> [dev|heldout] ["k values"]
#   scripts/team_settings.sh provenance P7                    # dev, k = 0 1 2 3 5 10
#   scripts/team_settings.sh provenance P7 dev "2"            # dev, k = 2 only (first look)
#   scripts/team_settings.sh provenance P7 dev "0 2 5"        # dev, chosen k values
#   FINAL_RUN=1 scripts/team_settings.sh provenance P7 heldout "0 1 2 3 5 10"
# Needs LLM_PROVIDER/LMSTUDIO_* in .env (see README). Do not set REVIEWER_* or PROVENANCE_*.
# Output goes to results/<split>/<owner>/ (local, git-ignored).
set -euo pipefail
POLICY=${1:?policy name, e.g. provenance}
OWNER=${2:?owner, e.g. P7}
SPLIT=${3:-dev}
KS=${4:-"0 1 2 3 5 10"}
BENIGN=${BENIGN:-1}   # CHANGE (benign TCR): 1 = also run the same user tasks with no attack (summary_<suite>_none.json); BENIGN=0 skips it
case "$SPLIT" in dev|heldout) ;; *) echo "split must be dev or heldout, got '$SPLIT'" >&2; exit 2 ;; esac
cd "$(dirname "$0")/.."
for SUITE in banking slack travel; do
  python -m agent_framework.runner --provider lmstudio --llm openai/gpt-oss-20b \
    --policy "$POLICY" --reviewer llm --attack important_instructions \
    --split-file "splits/${SUITE}_v1.2.json" --split "$SPLIT" \
    --k $KS --outdir "results/${SPLIT}/${OWNER}" $([ "$BENIGN" = 1 ] && echo --with-benign)   # CHANGE (benign TCR)
done
