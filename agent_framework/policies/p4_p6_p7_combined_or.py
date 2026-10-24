"""Combined P6 -> (P4 OR P7) approval policy.

P6 gets the first chance to reuse an earlier reviewer decision.  A remembered
approval or denial is final.  When P6 has no matching memory and escalates,
the unchanged P4 plan-consistency and P7 provenance gates are evaluated and
combined with a reason-aware three-valued OR:

* a P7 denial for untrusted influence -> deny
* otherwise any approve -> approve
* both deny -> deny
* otherwise -> escalate

Only an escalation that reaches the executor may become reviewer-backed P6
memory.  Calls resolved automatically by P4/P7 are removed from P6's pending
list so their execution is not mistaken for reviewer approval on a later turn.
"""

from copy import deepcopy

from agent_framework.policies.approval_reuse.policy import ApprovalReusePolicy
from agent_framework.policies.plan_consistency import PlanConsistencyPolicy
from agent_framework.policies.provenance_gate import ProvenancePolicy
from agent_framework.policy import Policy


def _unpack(result):
    if len(result) == 3:
        return result
    decision, state = result
    return decision, state, {}


class P4P6P7CombinedOrPolicy(Policy):
    """Reuse reviewer decisions, then combine P4 and P7 permissively."""

    name = "p4_p6_p7_combined_or"

    def __init__(self, reuse=None, plan=None, provenance=None):
        self.reuse = reuse if reuse is not None else ApprovalReusePolicy()
        self.plan = plan if plan is not None else PlanConsistencyPolicy()
        self.provenance = provenance if provenance is not None else ProvenancePolicy()

    def evaluate(self, context, state):
        state = {
            "reuse": deepcopy(state.get("reuse", {})),
            "plan": deepcopy(state.get("plan", {})),
            "provenance": deepcopy(state.get("provenance", {})),
        }

        reuse_decision, state["reuse"], reuse_info = self._evaluate_component(
            "P6 approval reuse", self.reuse, context, state["reuse"]
        )
        if reuse_decision in {"approve", "deny"}:
            return reuse_decision, state, self._info(
                f"P6 reused an earlier reviewer {reuse_decision} decision.",
                reuse_decision,
                None,
                None,
                reuse_info,
                None,
                None,
            )

        plan_decision, state["plan"], plan_info = self._evaluate_component(
            "P4 plan consistency", self.plan, context, state["plan"]
        )
        provenance_decision, state["provenance"], provenance_info = self._evaluate_component(
            "P7 provenance", self.provenance, context, state["provenance"]
        )
        final_decision = self._permissive_or(
            plan_decision, provenance_decision, provenance_info
        )

        # P6 appended the current call as pending when it escalated.  It must
        # remain pending only when the executor will actually call a reviewer.
        if final_decision != "escalate":
            self._discard_current_pending(context, state["reuse"])

        reason = (
            f"P6 returned {reuse_decision}; permissive OR of P4={plan_decision} "
            f"and P7={provenance_decision} returned {final_decision}."
        )
        return final_decision, state, self._info(
            reason,
            reuse_decision,
            plan_decision,
            provenance_decision,
            reuse_info,
            plan_info,
            provenance_info,
        )

    @staticmethod
    def _evaluate_component(label, policy, context, state):
        try:
            return _unpack(policy.evaluate(context, state))
        except Exception as exc:
            return "escalate", state, {
                "reason": f"{label} failed ({type(exc).__name__}: {exc})",
                "component_error": True,
            }

    @staticmethod
    def _permissive_or(left, right, provenance_info=None):
        if (
            right == "deny"
            and (provenance_info or {}).get("reason") == "untrusted_influence detected"
        ):
            return "deny"
        if "approve" in (left, right):
            return "approve"
        if left == right == "deny":
            return "deny"
        return "escalate"

    @staticmethod
    def _discard_current_pending(context, reuse_state):
        call = context["proposed_call"]
        pending = reuse_state.get("pending", [])
        for index in range(len(pending) - 1, -1, -1):
            record = pending[index]
            if (
                record.get("id") == call.id
                and record.get("function") == call.function
                and record.get("args") == dict(call.args)
                and record.get("index") == len(context.get("trajectory", []))
            ):
                pending.pop(index)
                break

    @staticmethod
    def _info(reason, reuse_decision, plan_decision, provenance_decision,
              reuse_info, plan_info, provenance_info):
        components = {
            "p6": {"decision": reuse_decision, **(reuse_info or {})},
        }
        if plan_decision is not None:
            components["p4"] = {"decision": plan_decision, **(plan_info or {})}
        if provenance_decision is not None:
            components["p7"] = {"decision": provenance_decision, **(provenance_info or {})}
        return {
            "reason": reason,
            "scores": {
                "p6_approved": float(reuse_decision == "approve"),
                "p4_approved": float(plan_decision == "approve"),
                "p7_approved": float(provenance_decision == "approve"),
            },
            "evidence": {
                "combination": "p6_reuse_then_p4_or_p7",
                "components": components,
            },
        }
