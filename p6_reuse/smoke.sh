#!/usr/bin/env bash
# P6 smoke test against a running MLX-Serve server.
#
# usage: bash p6_reuse/smoke.sh <model-id> [k]
#
# Start the server first, for example:
#   /Applications/MLX-Serve.app/Contents/MacOS/mlx-serve serve --host 127.0.0.1 --ctx-size 32768 \
#       --model-dir ~/.mlx-serve/models --model-dir ~/.lmstudio/models
#
# Runs one clean Slack task and one attacked Slack pair with the approval_reuse gate and the
# local_llm reviewer. Exits non-zero when the server or model is unavailable, when no tool call
# executed, or when every reviewer reply was unparseable (run_live.sh aborts on that).
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${1:?usage: smoke.sh <model-id> [k]}"
K="${2:-2}"
PY="${PYTHON:-.venv/bin/python}"
OUT="${SMOKE_OUTDIR:-results/p6_smoke}"
export MLX_BASE_URL="${MLX_BASE_URL:-http://127.0.0.1:11234/v1}"

models=$(curl -sf "$MLX_BASE_URL/models") || { echo "MLX-Serve is not reachable at $MLX_BASE_URL"; exit 2; }
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
  "$PY" -W ignore -m agent_framework.runner --provider mlx --llm "$MODEL" --policy approval_reuse \
    --reviewer local_llm --suite slack --k "$K" --outdir "$OUT" "$@"
}
run --attack none --user-tasks user_task_1
run --attack important_instructions --user-tasks user_task_1 --injection-tasks injection_task_1

# Only this run's pipeline directory; named as in runner.build_pipeline. OUT may hold other models' runs.
PIPE="${MODEL//\//_}-approval_reuse-local_llm-k$K"
"$PY" - "$OUT/$PIPE" <<'PY'
import collections, json, pathlib, sys
traces = [json.loads(p.read_text()) for p in pathlib.Path(sys.argv[1]).glob("slack/user_task_1/*/*.json")]
outcomes = collections.Counter(d["outcome"] for t in traces for d in t.get("approval_decisions", []))
executed = sum(d["executed"] for t in traces for d in t.get("approval_decisions", []))
reviews = sum(d["reviewer_called"] for t in traces for d in t.get("approval_decisions", []))
unparseable = sum(t.get("reviewer_unparseable", 0) for t in traces)
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
