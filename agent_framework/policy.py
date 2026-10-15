from typing import Any, Literal, TypedDict

Decision = Literal["approve", "deny", "escalate"]


class PolicyContext(TypedDict):
    task: str               # the user's task prompt (first user message)
    proposed_call: Any      # agentdojo FunctionCall (a copy; safe to read)
    environment: Any        # live task environment: READ ONLY, do not mutate
    trajectory: Any         # messages so far (system, user, assistant, tool)
    remaining_budget: int   # escalations left for this task
    metadata: dict          # pipeline extra_args


class Policy:
    """Base interface for all approval policies.

    evaluate() returns either
        (decision, state)
        (decision, state, info)   with info = {"reason": str, "scores": {...}}
    decision is "approve", "deny" or "escalate". State is task-scoped and is
    reset between tasks.
    """

    name = "base"

    def evaluate(self, context: PolicyContext, state: dict):
        raise NotImplementedError("Each policy must implement evaluate(context, state).")


class FullApprovePolicy(Policy):
    name = "full_approve"

    def evaluate(self, context, state):
        return "approve", state, {"reason": "full-approve baseline"}


class FullEscalatePolicy(Policy):
    name = "full_escalate"

    def evaluate(self, context, state):
        return "escalate", state, {"reason": "full-escalate baseline"}
