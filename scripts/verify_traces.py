"""Invariant checks on trace JSONs. Usage: python scripts/verify_traces.py results/verify"""
import glob, json, re, sys

REQUIRED = {"tool", "args", "decision", "outcome", "executed", "reviewer_called", "reviewer_reason",
            "budget_remaining", "reason", "scores", "policy_error", "policy_latency_s"}
EXECUTED = {"auto_approve", "escalate_approved"}
bad, checked = [], 0

for f in glob.glob(f"{sys.argv[1]}/**/*.json", recursive=True):
    d = json.load(open(f))
    decisions = d.get("approval_decisions")
    if decisions is None:
        continue
    checked += 1
    m = re.search(r"-k(\d+)-", f)
    k = int(m.group(1)) if m else None
    prev = None

    def fail(msg):
        bad.append(f"{f.split('verify/')[-1]}: {msg}")

    for i, x in enumerate(decisions):
        if REQUIRED - set(x):
            fail(f"call {i} missing fields {sorted(REQUIRED - set(x))}")
            continue
        if x["executed"] != (x["outcome"] in EXECUTED):
            fail(f"call {i}: executed={x['executed']} but outcome={x['outcome']}")
        if x["outcome"] == "budget_exhausted_deny" and x["budget_remaining"] != 0:
            fail(f"call {i}: budget_exhausted_deny with budget left")
        # if x["reviewer_called"] and not x["reviewer_reason"]:
        #     fail(f"call {i}: reviewer called but no reviewer_reason logged")
        if "-llm" in f and x["reviewer_called"] and not x["reviewer_reason"]:
            fail(f"call {i}: LLM reviewer called but no reviewer_reason logged")
        if prev is not None and x["budget_remaining"] > prev:
            fail(f"call {i}: budget increased within a task")
        if x["policy_error"]:
            fail(f"call {i}: policy_error {x['policy_error']}")
        prev = x["budget_remaining"]
    if k is not None and sum(x.get("reviewer_called", False) for x in decisions) > k:
        fail(f"more reviewer calls than k={k}")
    usage = d.get("token_usage", {})
    if "agent" not in usage or usage["agent"]["calls"] == 0:
        fail("no agent token usage recorded")
    if "llm" in f and any(x.get("reviewer_called") for x in decisions) and usage.get("reviewer", {}).get("calls", 0) == 0:
        fail("LLM reviewer used but no reviewer tokens recorded")

if not checked:
    bad.append('no traces checked; check the results directory')
print(f"checked {checked} traces, {len(bad)} problems")
print("\n".join(bad))
sys.exit(1 if bad else 0)
