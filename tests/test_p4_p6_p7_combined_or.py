from agentdojo.functions_runtime import FunctionCall

from agent_framework.policies.approval_reuse.policy import ApprovalReusePolicy
from agent_framework.policies.p4_p6_p7_combined_or import P4P6P7CombinedOrPolicy
from agent_framework.policy import Policy
from agent_framework.registry import POLICIES


class FixedPolicy(Policy):
    def __init__(self, decision, reason=None):
        self.decision = decision
        self.reason = reason or decision
        self.calls = 0

    def evaluate(self, context, state):
        self.calls += 1
        return self.decision, {**state, "calls": self.calls}, {"reason": self.reason}


class PendingReuse(FixedPolicy):
    def evaluate(self, context, state):
        decision, state, info = super().evaluate(context, state)
        if decision == "escalate":
            call = context["proposed_call"]
            state["pending"] = [
                *(state.get("pending") or []),
                {
                    "id": call.id,
                    "function": call.function,
                    "args": dict(call.args),
                    "index": len(context["trajectory"]),
                },
            ]
        return decision, state, info


def context():
    call = FunctionCall(function="search_emails", args={"query": "flight"}, id="c1")
    return {
        "task": "Search emails for flight",
        "proposed_call": call,
        "trajectory": [{"role": "assistant", "tool_calls": [call]}],
        "remaining_budget": 2,
        "metadata": {"decision_history": []},
    }


def build(reuse, plan, provenance, provenance_reason=None):
    return P4P6P7CombinedOrPolicy(
        reuse=PendingReuse(reuse),
        plan=FixedPolicy(plan),
        provenance=FixedPolicy(provenance, provenance_reason),
    )


def test_reused_p6_decisions_short_circuit_p4_and_p7():
    for reused in ("approve", "deny"):
        policy = build(reused, "approve", "approve")
        decision, _, info = policy.evaluate(context(), {})
        assert decision == reused
        assert policy.plan.calls == 0
        assert policy.provenance.calls == 0
        assert info["evidence"]["components"]["p6"]["decision"] == reused


def test_real_p6_remembered_denial_is_final():
    plan = FixedPolicy("approve")
    provenance = FixedPolicy("approve")
    policy = P4P6P7CombinedOrPolicy(
        reuse=ApprovalReusePolicy(), plan=plan, provenance=provenance
    )
    state = {
        "reuse": {
            "base": {},
            "pending": [],
            "approved": [],
            "denied": [
                {
                    "id": "old",
                    "function": "search_emails",
                    "args": {"query": "flight"},
                    "budget": 2,
                    "index": 0,
                }
            ],
        }
    }
    decision, _, _ = policy.evaluate(context(), state)
    assert decision == "deny"
    assert plan.calls == provenance.calls == 0


def test_p6_escalation_runs_both_source_gates():
    policy = build("escalate", "approve", "deny")
    decision, _, _ = policy.evaluate(context(), {})
    assert decision == "approve"
    assert policy.plan.calls == policy.provenance.calls == 1


def test_reason_aware_or_truth_table_without_attack_denial():
    expected = {
        ("approve", "approve"): "approve",
        ("approve", "escalate"): "approve",
        ("approve", "deny"): "approve",
        ("escalate", "approve"): "approve",
        ("escalate", "escalate"): "escalate",
        ("escalate", "deny"): "escalate",
        ("deny", "approve"): "approve",
        ("deny", "escalate"): "escalate",
        ("deny", "deny"): "deny",
    }
    for pair, final in expected.items():
        decision, _, _ = build("escalate", *pair).evaluate(context(), {})
        assert decision == final


def test_p7_untrusted_influence_denial_vetoes_p4_approval():
    decision, _, _ = build(
        "escalate", "approve", "deny", "untrusted_influence detected"
    ).evaluate(context(), {})
    assert decision == "deny"


def test_pending_reuse_record_survives_only_when_reviewer_will_run():
    _, approved_state, _ = build("escalate", "approve", "deny").evaluate(context(), {})
    assert approved_state["reuse"]["pending"] == []

    _, denied_state, _ = build("escalate", "deny", "deny").evaluate(context(), {})
    assert denied_state["reuse"]["pending"] == []

    _, mixed_state, _ = build("escalate", "deny", "escalate").evaluate(context(), {})
    assert len(mixed_state["reuse"]["pending"]) == 1

    _, escalated_state, _ = build("escalate", "escalate", "escalate").evaluate(context(), {})
    assert len(escalated_state["reuse"]["pending"]) == 1


def test_registered_with_zero_argument_factory():
    assert isinstance(POLICIES["p4_p6_p7_combined_or"](), P4P6P7CombinedOrPolicy)
