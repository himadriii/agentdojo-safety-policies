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


class RecordingReuse(PendingReuse):
    def record_external_approval(self, context, state, source):
        state.setdefault("approved", []).append({"function": context["proposed_call"].function, "source": source})
        return state


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
        reuse=RecordingReuse(reuse),
        plan=FixedPolicy(plan),
        provenance=FixedPolicy(provenance, provenance_reason),
    )


def test_p6_reuse_approve_applies_only_when_gates_escalate():
    policy = build("approve", "escalate", "escalate")
    decision, _, info = policy.evaluate(context(), {})
    assert decision == "approve"
    assert info["scores"]["p6_approved"] == 1.0
    assert policy.plan.calls == policy.provenance.calls == 1


def test_p6_reuse_approve_cannot_override_gate_deny():
    decision, _, _ = build("approve", "deny", "deny").evaluate(context(), {})
    assert decision == "deny"


def test_p6_remembered_denial_overrides_gate_approve():
    decision, _, _ = build("deny", "approve", "approve").evaluate(context(), {})
    assert decision == "deny"


def test_gate_approval_is_recorded_in_p6_memory():
    _, st, info = build("escalate", "escalate", "approve").evaluate(context(), {})
    assert st["reuse"]["approved"] == [{"function": "search_emails", "source": "p7"}]
    assert info["evidence"]["recorded_gate_approval"] == "p7"
    _, st, _ = build("escalate", "approve", "escalate").evaluate(context(), {})
    assert st["reuse"]["approved"][0]["source"] == "p4"
    _, st, _ = build("escalate", "escalate", "escalate").evaluate(context(), {})
    assert "approved" not in st["reuse"]
    _, st, _ = build("escalate", "deny", "deny").evaluate(context(), {})
    assert "approved" not in st["reuse"]


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


def test_gates_always_run():
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



def test_real_p6_reuses_gate_approval_for_exact_cover_but_not_drill_down():
    policy = P4P6P7CombinedOrPolicy(
        reuse=ApprovalReusePolicy(), plan=FixedPolicy("escalate"), provenance=FixedPolicy("approve")
    )
    first = FunctionCall(function="get_all_hotels_in_city", args={"city": "Paris"}, id="a")
    ctx = {
        "task": "Find hotels in Paris",
        "proposed_call": first,
        "trajectory": [{"role": "assistant", "tool_calls": [first]}],
        "remaining_budget": 2,
        "metadata": {"decision_history": []},
    }
    decision, state, _ = policy.evaluate(ctx, {})
    assert decision == "approve"
    record = state["reuse"]["approved"][0]
    assert record["source"] == "p7"

    # gates now escalate everything; P6 alone decides
    policy.plan, policy.provenance = FixedPolicy("escalate"), FixedPolicy("escalate")
    again = FunctionCall(function="get_all_hotels_in_city", args={"city": "Paris"}, id="b")
    ctx2 = {**ctx, "proposed_call": again,
            "trajectory": ctx["trajectory"] + [
                {"role": "tool", "tool_call_id": "a", "tool_call": first,
                 "content": [{"type": "text", "content": "Le Marais Boutique, Good Night"}]},
                {"role": "assistant", "tool_calls": [again]}]}
    decision, state, info = policy.evaluate(ctx2, state)
    assert decision == "approve" and info["scores"]["p6_approved"] == 1.0

    drill = FunctionCall(function="get_hotels_prices", args={"hotel_names": ["Le Marais Boutique"]}, id="c")
    ctx3 = {**ctx2, "proposed_call": drill,
            "trajectory": ctx2["trajectory"] + [{"role": "assistant", "tool_calls": [drill]}]}
    decision, _, info = policy.evaluate(ctx3, state)
    assert decision == "escalate" and info["scores"]["p6_approved"] == 0.0
