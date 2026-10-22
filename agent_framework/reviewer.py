import copy


def build_reviewer_context(task, proposed_call, trajectory, policy_reason=None,
                           evidence=None, tool_description=None):
    """What a human reviewer could plausibly see: the task, the proposed call and
    the visible trajectory. No environment object, no benchmark labels.

    evidence: optional structured evidence a policy computed (same schema as
    agent_framework.evidence.build_evidence). If None, the reviewer builds its own.
    tool_description: the tool's schema description (trusted, comes from the tool definition).
    """
    return {
        "task": task,
        "proposed_call": proposed_call.model_copy(deep=True),
        "trajectory": copy.deepcopy(list(trajectory)),
        "policy_reason": policy_reason,
        "evidence": copy.deepcopy(evidence) if evidence else None,
        "tool_description": tool_description,
    }


class Reviewer:
    name = "base"

    def review(self, context) -> str:
        """Return "approve" or "deny"."""
        raise NotImplementedError


class MockReviewer(Reviewer):
    name = "mock"

    def __init__(self, decision: str = "approve"):
        self.decision = decision
        self.calls = 0

    def review(self, context):
        self.calls += 1
        print(f"[REVIEWER] #{self.calls}: {context['proposed_call'].function} -> {self.decision}")
        return self.decision
