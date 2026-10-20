"""Approval reuse gate through the real P1ToolsExecutor pipeline (plan U2). No API key, no network."""
from agent_framework.policies.approval_reuse.policy import ApprovalReusePolicy
from agent_framework.policy import Policy
from agent_framework.registry import POLICIES
from agent_framework.reviewer import MockReviewer, Reviewer
from tests.reuse_helpers import EXECUTED, build, call, outcomes, run


def test_repeated_read_reuses_the_reviewer_approval():
    pipeline, executor = build([[call("search_emails", "c1", query="flight")],
                                [call("search_emails", "c2", query="hotel")]], k=1)
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved", "auto_approve"]
    assert EXECUTED == [("search_emails", "flight"), ("search_emails", "hotel")]


def test_repeat_of_a_denied_side_effect_is_denied_without_budget():
    steps = [[call("send_email", "c1", recipients=["mark@evil.com"], body="a")],
             [call("send_email", "c2", recipients=["mark@evil.com"], body="b")]]
    pipeline, executor = build(steps, k=2, reviewer=MockReviewer("deny"))
    run(pipeline)
    assert outcomes(executor) == ["escalate_denied", "auto_deny"]
    assert executor.budget.used == 1
    assert EXECUTED == []


def test_budget_exhaustion_is_not_remembered_as_a_denial():
    steps = [[call("send_email", "c1", recipients=["bob@example.com"], body="a")],
             [call("send_email", "c2", recipients=["bob@example.com"], body="a")]]
    pipeline, executor = build(steps, k=0)
    run(pipeline)
    assert outcomes(executor) == ["budget_exhausted_deny", "budget_exhausted_deny"]
    assert [d["decision"] for d in executor.decisions] == ["escalate", "escalate"]


def test_memory_resets_between_tasks():
    steps = [[call("search_emails", "c1", query="flight")]]
    pipeline, executor = build(steps, k=1)
    run(pipeline)
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved"]   # second task escalated again, not reused
    assert executor.budget.used == 1


def test_parallel_calls_resolve_on_the_next_turn():
    steps = [[call("search_emails", "c1", query="a"), call("send_email", "c2", recipients=["bob@example.com"],
                                                             body="hi")],
             [call("search_emails", "c3", query="b"), call("send_email", "c4", recipients=["bob@example.com"],
                                                             body="hello")]]
    pipeline, executor = build(steps, k=2)
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved", "escalate_approved", "auto_approve", "auto_approve"]
    assert [d["budget_remaining"] for d in executor.decisions[:2]] == [1, 0]


def test_call_without_id_resolves_by_function_and_args():
    pipeline, executor = build([[call("search_emails", None, query="flight")],
                                [call("search_emails", None, query="hotel")]], k=1)
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved", "auto_approve"]


class ByRecipient(Reviewer):
    def review(self, context):
        recipients = context["proposed_call"].args.get("recipients", [])
        return "deny" if "mark@evil.com" in recipients else "approve"


def test_reused_id_does_not_match_an_older_result():
    steps = [[call("send_email", "call_0", recipients=["mark@evil.com"], body="x")],
             [call("send_email", "call_0", recipients=["bob@example.com"], body="x")],
             [call("send_email", "call_2", recipients=["bob@example.com"], body="y")]]
    pipeline, executor = build(steps, k=3, reviewer=ByRecipient())
    run(pipeline)
    assert outcomes(executor) == ["escalate_denied", "escalate_approved", "auto_approve"]


class DenyQueryA(Reviewer):
    def review(self, context):
        return "deny" if context["proposed_call"].args.get("query") == "a" else "approve"


def test_denial_memory_is_checked_before_approval_memory():
    """KTD5: a read approval covers every later search, but an exact repeat of a denied one stays denied."""
    steps = [[call("search_emails", "c1", query="a")],
             [call("search_emails", "c2", query="b")],
             [call("search_emails", "c3", query="a")]]
    pipeline, executor = build(steps, k=3, reviewer=DenyQueryA())
    run(pipeline)
    assert outcomes(executor) == ["escalate_denied", "escalate_approved", "auto_deny"]


def test_tool_runtime_error_still_counts_as_reviewer_approval():
    pipeline, executor = build([[call("flaky_tool", "c1", x="1")], [call("flaky_tool", "c2", x="1")]], k=1)
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved", "auto_approve"]


class Fixed(Policy):
    def __init__(self, decision):
        self.decision = decision

    def evaluate(self, context, state):
        return self.decision, state, {"reason": f"base says {self.decision}", "scores": {"risk": 0.5}}


def test_base_approve_and_deny_pass_through():
    for decision, expected in (("approve", "auto_approve"), ("deny", "auto_deny")):
        pipeline, executor = build([[call("search_emails", "c1", query="a")]],
                                   policy=ApprovalReusePolicy(base=Fixed(decision)))
        run(pipeline)
        assert outcomes(executor) == [expected]
        assert executor.decisions[0]["reason"] == f"base says {decision}"
        assert executor.decisions[0]["scores"]["risk"] == 0.5


class Exploding(Policy):
    def evaluate(self, context, state):
        raise RuntimeError("boom")


def test_base_exception_escalates_instead_of_crashing():
    pipeline, executor = build([[call("search_emails", "c1", query="a")]],
                               policy=ApprovalReusePolicy(base=Exploding()))
    run(pipeline)
    assert executor.decisions[0]["decision"] == "escalate"
    assert "RuntimeError" in executor.decisions[0]["reason"]


class CountingBase(Policy):
    """Two-tuple base that escalates only its second call."""

    def __init__(self):
        self.seen = []

    def evaluate(self, context, state):
        state = {**state, "n": state.get("n", 0) + 1}
        self.seen.append(state["n"])
        return ("escalate" if state["n"] == 2 else "approve"), state


def test_base_state_is_threaded_and_kept_apart_from_reuse_memory():
    base = CountingBase()
    steps = [[call("search_emails", "c1", query="a")],
             [call("search_emails", "c2", query="b")],
             [call("search_emails", "c3", query="c")]]
    pipeline, executor = build(steps, policy=ApprovalReusePolicy(base=base), k=2)
    run(pipeline)
    assert base.seen == [1, 2, 3]
    assert executor.policy_state["base"] == {"n": 3}
    # the base's own approval of c1 is not a reviewer approval, so c2 is still escalated (R3)
    assert outcomes(executor) == ["auto_approve", "escalate_approved", "auto_approve"]


def test_reuse_error_keeps_the_escalation():
    def broken(*args):
        raise ZeroDivisionError

    pipeline, executor = build([[call("search_emails", "c1", query="a")],
                                [call("search_emails", "c2", query="b")]],
                               policy=ApprovalReusePolicy(covers=broken), k=2)
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved", "escalate_approved"]
    assert "reuse skipped (ZeroDivisionError)" in executor.decisions[1]["reason"]


def test_reason_names_the_earlier_call_and_scores_are_floats():
    pipeline, executor = build([[call("search_emails", "c1", query="flight")],
                                [call("search_emails", "c2", query="hotel")]], k=1)
    run(pipeline)
    reused = executor.decisions[1]
    assert "search_emails" in reused["reason"] and "flight" in reused["reason"]
    assert reused["scores"]["reuse_approved"] == 1.0
    assert all(isinstance(v, float) for v in reused["scores"].values())


def test_registered_and_zero_argument():
    assert isinstance(POLICIES["approval_reuse"](), ApprovalReusePolicy)
