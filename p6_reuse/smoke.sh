#!/usr/bin/env bash
# P6 smoke test against a running LM Studio server.
#
# usage: bash p6_reuse/smoke.sh <model-id> [k]
#
# Start the LM Studio server first (Developer tab, or `lms server start --port 1234`) and load the model;
# LMSTUDIO_BASE_URL overrides the default http://127.0.0.1:1234/v1.
#
# Runs one clean Slack task and one attacked Slack pair with the approval_reuse gate and P1's shared
# LLM reviewer (`--reviewer llm`). Exits non-zero when the server or model is unavailable, when no tool
# call executed, or when every reviewer reply failed to parse (run_live.sh aborts on that).
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${1:?usage: smoke.sh <model-id> [k]}"
K="${2:-2}"
PY="${PYTHON:-.venv/bin/python}"
OUT="${SMOKE_OUTDIR:-results/p6_smoke}"
export LMSTUDIO_BASE_URL="${LMSTUDIO_BASE_URL:-http://127.0.0.1:1234/v1}"

models=$(curl -sf "$LMSTUDIO_BASE_URL/models") || { echo "LM Studio is not reachable at $LMSTUDIO_BASE_URL"; exit 2; }
"$PY" - "$MODEL" "$models" <<'PY' || exit 3
import json, sys
model, payload = sys.argv[1], json.loads(sys.argv[2])
entries = payload.get("data", [])
ids = [m.get("id") for m in entries]
print("served models:", ", ".join(map(str, ids)))
match = next((m for m in entries if m.get("id") == model), None)
if match is None:
    print(f"model {model!r} is not served"); sys.exit(1)
ctx = next((match[k] for k in ("context_length", "max_context_length", "ctx_size") if k in match), "unknown")
print(f"served context for {model}: {ctx}")
PY

run() {
  "$PY" -W ignore -m agent_framework.runner --provider lmstudio --llm "$MODEL" --policy approval_reuse \
    --reviewer llm --suite slack --k "$K" --outdir "$OUT" "$@"
}
run --attack none --user-tasks user_task_1
run --attack important_instructions --user-tasks user_task_1 --injection-tasks injection_task_1

# Only this run's pipeline directories; named as in runner.build_pipeline ({provider}-{model}-{policy}-
# {reviewer}-k{k}-{config hash}). OUT may hold other models' runs.
"$PY" - "$OUT" "lmstudio-${MODEL//\//_}-approval_reuse-llm" "-k$K-" <<'PY'
import collections, json, pathlib, sys
out, prefix, k_tag = sys.argv[1:4]
dirs = [d for d in pathlib.Path(out).iterdir() if d.name.startswith(prefix) and k_tag in d.name]
traces = [json.loads(p.read_text()) for d in dirs for p in d.glob("slack/user_task_1/*/*.json")]
if not traces:
    print(f"SMOKE FAIL: no traces under {out} for {prefix}*{k_tag}*"); sys.exit(4)
outcomes = collections.Counter(d["outcome"] for t in traces for d in t.get("approval_decisions", []))
executed = sum(d["executed"] for t in traces for d in t.get("approval_decisions", []))
reviews = sum(d["reviewer_called"] for t in traces for d in t.get("approval_decisions", []))
# P1's reviewer records a parse failure or server error as reviewer_reason REVIEWER_PARSE_FAILURE / REVIEWER_ERROR...
unparseable = sum(str(d.get("reviewer_reason") or "").startswith("REVIEWER_")
                  for t in traces for d in t.get("approval_decisions", []))
errors = [t["error"] for t in traces if t.get("error")]
print("decision outcomes:", dict(outcomes))
print(f"executed calls: {executed}  reviewer calls: {reviews}  unparseable reviewer replies: {unparseable}")
if errors:
    print("task errors:", errors)
if executed == 0:
    print("SMOKE FAIL: no tool call executed"); sys.exit(4)
if reviews and unparseable >= reviews:
    print("SMOKE FAIL: every reviewer reply was unparseable"); sys.exit(5)
print("SMOKE OK")
PY
