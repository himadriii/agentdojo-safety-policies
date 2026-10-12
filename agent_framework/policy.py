from typing import Any, Literal, TypedDict

Decision = Literal["approve","deny","escalate"]

# sample_context = {
#     "proposed_call":{
#         "function":"search_emails",
#         "agrs":{"query":"flight"},
#     },
#     "environment":{},
#     "trajectory":[],
#     "remaining_budget":2,
#     "metadata":{"task_id":"sample_task"},
# }

# sample_state = {}

class PolicyContext(TypedDict):
    task: Any
    proposed_call: Any
    environment: Any
    trajectory: Any
    remaining_budget: Any
    metadata: dict


class Policy:
    """ Base polocy interface for all approval policies."""

    def evaluate(
        self, 
        context: PolicyContext, 
        state: dict,
    ) -> tuple[Decision, dict]:

        """
        Evaluate a proposed tool call.

        Agrs:
            context: Information available when deciding.
            state: Policy-specific state for the current task.
        
        Returns: 
            decision: "approve", "deny", or "escalate"
            and the updated policy state
        """
        # tool_name = context["proposed_call"].function
        # For this test, every tool call requires escalation
        # decision = "deny"
        # return decision, state

        raise NotImplementedError(
            "Each policy must implement evaluate(context, state)."
        )

class FullApprovePolicy:
    def evaluate(self, context, state):
        return "approve", state


class FullEscalatePolicy:
    def evaluate(self, context, state):
        return "escalate", state

