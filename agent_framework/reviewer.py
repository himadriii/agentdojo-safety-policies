import copy


def build_reviewer_context(task, proposed_call, trajectory, policy_reason=None):
    """What a human reviewer could plausibly see: the task, the proposed call and
    the visible trajectory. No environment object, no benchmark labels."""
    return {
        "task": task,
        "proposed_call": proposed_call.model_copy(deep=True),
        "trajectory": copy.deepcopy(list(trajectory)),
        "policy_reason": policy_reason,
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
