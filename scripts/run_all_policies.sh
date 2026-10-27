#!/usr/bin/env bash
# Smoke-test every registered policy, then do the dev run of every policy on one shared environment.
# Usage:  bash scripts/run_all_policies.sh [smoke|dev|heldout|all]        (default: all)
#   smoke   : offline contract tests, then 1 trace per policy (slack user_task_1 x injection_task_1, k=2)
#   dev     : every policy on the dev split, all suites, all k values
#   heldout : every policy on the held-out (test) split. FINAL RUN ONLY: needs FINAL_RUN=1, run once per frozen
#             policy and reviewer, never used for tuning. Results go to results/heldout/$OWNER.
#   all     : smoke first; the dev run starts only if every smoke check passed (never includes heldout)
#   FINAL_RUN=1 bash scripts/run_all_policies.sh heldout
# Same settings as scripts/team_settings.sh (reviewer llm, attack important_instructions, benchmark v1.2,
# provider and model settings from .env, no REVIEWER_*/PROVENANCE_* overrides). Optional environment variables:
#   KS="0 1 2 3 5 8 10 15"   k values for the dev run (full_approve only ever runs k=0: it never escalates)
#   SUITES="banking slack travel"
#   POLICIES="..."           subset / order of policies (default: all registered)
#   OWNER=ALL                results go to results/<dev|heldout|smoke>/$OWNER (git-ignored)
#   LLM=openai/gpt-oss-20b   agent model (the reviewer follows it)
#   PROVIDER=lmstudio        one-off override of LLM_PROVIDER from .env
#   PYTHON=python             Python executable (useful when Bash is running under WSL)
# Re-running is safe: finished runs are cached by pipeline name and skipped. A failing policy does not stop the
# loop; failures are listed at the end and the script exits non-zero.
set -uo pipefail
cd "$(dirname "$0")/.."
MODE=${1:-all}
KS=${KS:-"0 1 2 3 5 8 10 15"}
SUITES=${SUITES:-"workspace banking slack travel"}
OWNER=${OWNER:-ALL}
LLM=${LLM:-openai/gpt-oss-20b}
PYTHON=${PYTHON:-python}
POLICIES=${POLICIES:-"full_approve full_escalate anomaly supervised_risk supervised_risk_urlguard approval_reuse similarity_reuse plan_consistency provenance p4_p6_p7_combined_or"}

# Every policy must be judged by the same reviewer: drop any stale REVIEWER_* / PROVENANCE_* shell variables.
for v in $(compgen -v | grep -E '^(REVIEWER|PROVENANCE)_' || true); do unset "$v"; done

mkdir -p logs
STAMP=$(date +%Y%m%d_%H%M%S)
FAILED=()
RUNNER=("$PYTHON" -m agent_framework.runner ${PROVIDER:+--provider "$PROVIDER"} --llm "$LLM" --reviewer llm --attack important_instructions)
[ "${BENIGN:-1}" = "1" ] && RUNNER+=(--with-benign)   # CHANGE (benign TCR): also run the same user tasks with no attack; BENIGN=0 to skip

smoke() {
  echo "=== SMOKE ==="
  echo "--- offline contract tests (every registered policy)"
  if "$PYTHON" -m pytest tests/test_policy_contract_all.py tests/test_executor_contract.py -q > "logs/smoke_contract_${STAMP}.log" 2>&1; then
    echo "OK   contract tests"
  else
    echo "FAIL contract tests -> logs/smoke_contract_${STAMP}.log"; FAILED+=("smoke:contract-tests")
  fi
  for P in $POLICIES; do
    echo "--- smoke $P"
    "${RUNNER[@]}" --policy "$P" --suite slack --user-tasks user_task_1 --injection-tasks injection_task_1 \
      --k 2 --outdir "results/smoke/$OWNER" --force > "logs/smoke_${P}_${STAMP}.log" 2>&1
    rc=$?
    n=$(find "results/smoke/$OWNER" -path "*-${P}-*" -name 'injection_task_1.json' 2>/dev/null | wc -l | tr -d ' ')
    if [ $rc -eq 0 ] && [ "$n" -ge 1 ]; then echo "OK   $P"; else echo "FAIL $P (exit=$rc, traces=$n) -> logs/smoke_${P}_${STAMP}.log"; FAILED+=("smoke:$P"); fi
  done
}

run_split() {   # $1 = dev | heldout
  local SPLIT=$1
  echo "=== $(echo "$SPLIT" | tr a-z A-Z): policies=[$POLICIES] k=[$KS] suites=[$SUITES] owner=$OWNER ==="
  for P in $POLICIES; do
    K="$KS"; [ "$P" = "full_approve" ] && K="0"
    echo "--- $SPLIT $P (k: $K)"
    for SUITE in $SUITES; do
      "${RUNNER[@]}" --policy "$P" --split-file "splits/${SUITE}_v1.2.json" --split "$SPLIT" \
        --k $K --outdir "results/$SPLIT/$OWNER" 2>&1 | tee -a "logs/${SPLIT}_${P}_${STAMP}.log"
      if [ "${PIPESTATUS[0]}" -ne 0 ]; then echo "FAIL $P / $SUITE"; FAILED+=("$SPLIT:$P:$SUITE"); fi
    done
  done
}

case "$MODE" in
  smoke) smoke ;;
  dev)   run_split dev ;;
  heldout)
    if [ "${FINAL_RUN:-}" != "1" ]; then
      echo "heldout is for the final frozen run only (all policies AND the reviewer frozen, run once)." >&2
      echo "Confirm with:  FINAL_RUN=1 bash scripts/run_all_policies.sh heldout" >&2; exit 2
    fi
    run_split heldout ;;
  all)   smoke
         if [ ${#FAILED[@]} -gt 0 ]; then echo "Smoke failures: ${FAILED[*]}"; echo "Fix them, or drop them with POLICIES=\"...\", then rerun."; exit 1; fi
         run_split dev ;;
  *) echo "usage: $0 [smoke|dev|heldout|all]" >&2; exit 2 ;;
esac

if [ ${#FAILED[@]} -gt 0 ]; then echo "FAILED: ${FAILED[*]}"; exit 1; fi
SPLIT_DONE=dev; [ "$MODE" = "heldout" ] && SPLIT_DONE=heldout
echo "DONE. Check with: python scripts/check_summaries.py results/$SPLIT_DONE/$OWNER"
