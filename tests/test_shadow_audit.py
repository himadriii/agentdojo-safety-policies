"""The shadow audit logs what the reviewer would say about reuse approvals without changing the run."""
from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop

from agent_framework.budget import EscalationBudget
from agent_framework.policies.approval_reuse.policy import ApprovalReusePolicy
from agent_framework.reviewer import MockReviewer
from agent_framework.tools_executor import ResetTaskState
from p6_reuse.shadow import ShadowAuditExecutor
from tests.reuse_helpers import EXECUTED, Steps, call, outcomes, run


class Scripted(MockReviewer):
    """Replies with the queued verdicts in order, then approves."""

    def __init__(self, verdicts):
        super().__init__()
        self.verdicts = list(verdicts)

    def review(self, context):
        self.calls += 1
        return self.verdicts.pop(0) if self.verdicts else "approve"


def build_shadow(steps, reviewer, k=1):
    EXECUTED.clear()
    executor = ShadowAuditExecutor(policy=ApprovalReusePolicy(), reviewer=reviewer, budget=EscalationBudget(limit=k))
    llm = Steps(steps)
    pipeline = AgentPipeline([ResetTaskState(executor), SystemMessage("test agent"), InitQuery(),
                              llm, ToolsExecutionLoop([executor, llm])])
    return pipeline, executor


def test_reuse_approval_is_shadow_reviewed_but_not_enforced():
    reviewer = Scripted(["approve", "deny"])   # real review approves, the shadow review would deny
    pipeline, executor = build_shadow(
        [[call("search_emails", query="flight")], [call("search_emails", query="hotel")]], reviewer)
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved", "auto_approve"]
    assert EXECUTED == [("search_emails", "flight"), ("search_emails", "hotel")]   # shadow verdict not enforced
    assert [e["shadow_verdict"] for e in executor.shadow_log] == ["deny"]
    assert executor.shadow_log[0]["tool"] == "search_emails"
    assert executor.budget.remaining == 0   # one real escalation; the shadow review spent nothing
    assert reviewer.calls == 2


def test_only_reuse_approvals_are_audited():
    pipeline, executor = build_shadow([[call("search_emails", query="a")]], Scripted(["approve"]))
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved"]
    assert executor.shadow_log == []


def test_shadow_log_resets_between_tasks():
    pipeline, executor = build_shadow(
        [[call("search_emails", query="a")], [call("search_emails", query="b")]], Scripted(["approve", "approve"]))
    run(pipeline)
    assert len(executor.shadow_log) == 1
    executor.reset_for_new_task()
    assert executor.shadow_log == []


def test_failing_shadow_review_does_not_change_the_run():
    class Boom(Scripted):
        def review(self, context):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("server down")
            return "approve"

    pipeline, executor = build_shadow(
        [[call("search_emails", query="a")], [call("search_emails", query="b")]], Boom([]))
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved", "auto_approve"]
    assert executor.shadow_log[0]["shadow_verdict"] == "error"
