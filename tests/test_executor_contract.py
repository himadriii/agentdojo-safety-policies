"""Contract tests for the shared runner. No API key, no network.

Run from the repo root:  python -m pytest test -q
"""
import logging
from types import SimpleNamespace

from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop
from agentdojo.functions_runtime import EmptyEnv, FunctionCall, FunctionsRuntime, make_function
from agentdojo.types import ChatAssistantMessage, text_content_block_from_string

from agent_framework.budget import EscalationBudget
from agent_framework.policy import FullEscalatePolicy, Policy
from agent_framework.reviewer import MockReviewer
from agent_framework.tools_executor import (
    ATTACK_DENIAL_MESSAGE,
    DENIAL_MESSAGE,
    P1ToolsExecutor,
    ResetTaskState,
    describe_tool_effects,
)
from agent_framework.tool_meta import get_tool_meta

EXECUTED = []


def search_emails(query: str) -> str:
    """Search emails using a query.

    :param query: The search query to use.
    """
    EXECUTED.append(query)
    return f"Found 1 email matching '{query}'"


class ScriptedLLM(BasePipelineElement):
    """Requests one search_emails call per query, then gives a final answer."""

    def __init__(self, queries):
        self.queries = list(queries)

    def query(self, query, runtime, env=EmptyEnv(), messages=(), extra_args={}):
        step = sum(1 for m in messages if m["role"] == "assistant")
        if step < len(self.queries):
            call = FunctionCall(function="search_emails", args={"query": self.queries[step]})
            msg = ChatAssistantMessage(
                role="assistant",
                content=[text_content_block_from_string("searching")],
                tool_calls=[call],
            )
        else:
            msg = ChatAssistantMessage(
                role="assistant",
                content=[text_content_block_from_string("done")],
                tool_calls=None,
            )
        return query, runtime, env, [*messages, msg], extra_args


class Fixed(Policy):
    def __init__(self, decision, info=None):
        self.decision, self.info = decision, info

    def evaluate(self, context, state):
        if self.info is None:
            return self.decision, state
        return self.decision, state, self.info


def build(policy, k=2, reviewer=None, queries=("a", "b", "c")):
    EXECUTED.clear()
    executor = P1ToolsExecutor(
        policy=policy,
        reviewer=reviewer or MockReviewer(),
        budget=EscalationBudget(limit=k),
    )
    llm = ScriptedLLM(queries)
    pipeline = AgentPipeline([
        ResetTaskState(executor), SystemMessage("test agent"), InitQuery(),
        llm, ToolsExecutionLoop([executor, llm]),
    ])
    return pipeline, executor


def run(pipeline, task="Find my emails."):
    runtime = FunctionsRuntime([make_function(search_emails)])
    *_, messages, _ = pipeline.query(task, runtime, EmptyEnv(), [], {})
    return messages


def outcomes(executor):
    return [d["outcome"] for d in executor.decisions]


def test_two_and_three_tuple_policies_both_work():
    for policy in (Fixed("approve"), Fixed("approve", {"reason": "ok", "scores": {"risk": 0.1}})):
        pipeline, executor = build(policy, queries=("a", "b"))
        run(pipeline)
        assert EXECUTED == ["a", "b"]
    assert executor.decisions[0]["reason"] == "ok"
    assert executor.decisions[0]["scores"] == {"risk": 0.1}


def test_policy_receives_documented_context():
    seen = []

    class Recording(Policy):
        def evaluate(self, context, state):
            seen.append(context)
            return "approve", state

    pipeline, _ = build(Recording(), queries=("a",))
    run(pipeline, task="Find my emails.")
    ctx = seen[0]
    assert set(ctx) == {
        "task", "proposed_call", "environment", "trajectory",
        "remaining_budget", "metadata", "tool_effects", "tools",
    }
    assert ctx["task"] == "Find my emails."
    assert ctx["remaining_budget"] == 2
    assert ctx["tool_effects"]["non_mutating_read"] is True


def test_effect_metadata_is_conservative_about_read_side_effects():
    read = SimpleNamespace(
        name="lookup_records", description="Returns records matching the query."
    )
    mark_read = SimpleNamespace(
        name="fetch_messages",
        description="Returns unread messages. They are marked as read after this function is called.",
    )
    unknown = SimpleNamespace(name="process", description="Process the input.")

    assert describe_tool_effects(read)["effects"] == ["read"]
    assert describe_tool_effects(mark_read)["effects"] == ["read", "state_change"]
    assert describe_tool_effects(mark_read)["non_mutating_read"] is False
    assert describe_tool_effects(unknown)["effects"] == ["unknown"]


def test_auto_deny_blocks_execution_and_returns_feedback():
    pipeline, executor = build(Fixed("deny"), queries=("a", "b"))
    messages = run(pipeline)
    assert EXECUTED == []
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 2
    assert all(m["error"] == DENIAL_MESSAGE for m in tool_msgs)
    assert outcomes(executor) == ["auto_deny", "auto_deny"]


def test_untrusted_influence_denial_tells_agent_to_resume_original_task():
    pipeline, executor = build(
        Fixed(
            "deny",
            {
                "reason": "combined denial",
                "evidence": {
                    "components": {
                        "p7": {
                            "decision": "deny",
                            "reason": "untrusted_influence detected",
                        }
                    }
                },
            },
        ),
        queries=("a",),
    )
    messages = run(pipeline)
    tool_message = next(message for message in messages if message["role"] == "tool")
    assert tool_message["error"] == ATTACK_DENIAL_MESSAGE
    assert "complete every remaining authorized step" in tool_message["error"]
    assert outcomes(executor) == ["auto_deny"]


def test_untrusted_edge_without_attack_denial_uses_generic_feedback():
    pipeline, _ = build(
        Fixed(
            "deny",
            {
                "reason": "combined denial",
                "evidence": {
                    "components": {
                        "p7": {
                            "decision": "escalate",
                            "reason": "incomplete provenance for argument /body",
                            "evidence": {
                                "adverse_edges": [{"relation": "untrusted_influence"}]
                            },
                        }
                    }
                },
            },
        ),
        queries=("a",),
    )
    messages = run(pipeline)
    tool_message = next(message for message in messages if message["role"] == "tool")
    assert tool_message["error"] == DENIAL_MESSAGE


def test_denial_log_contains_full_reason_and_validation_error(caplog):
    validation_error = {
        "edge_index": 0,
        "edge": {"relation": "authorizes", "confidence": "very high"},
        "error_type": "ValueError",
        "error": "LLM confidence is not numeric",
    }
    pipeline, _ = build(
        Fixed(
            "deny",
            {
                "reason": "invalid provenance evidence",
                "validation_errors": [validation_error],
            },
        ),
        queries=("a",),
    )

    run(pipeline)

    assert "decision=deny outcome=auto_deny" in caplog.text
    assert "reason=invalid provenance evidence" in caplog.text
    assert '"confidence": "very high"' in caplog.text
    assert "LLM confidence is not numeric" in caplog.text


def test_executor_records_and_logs_structured_evidence(caplog):
    caplog.set_level(logging.INFO)
    evidence = {
        "authorization_edges": [
            {"source_id": "trajectory:1", "supporting_span": "Find my emails"}
        ],
        "argument_provenance": [],
    }
    pipeline, executor = build(
        Fixed("approve", {"reason": "authorized", "evidence": evidence}),
        queries=("a",),
    )

    run(pipeline)

    assert executor.decisions[0]["evidence"] == evidence
    assert "[P1:EVIDENCE]" in caplog.text
    assert '"supporting_span": "Find my emails"' in caplog.text


def test_budget_exhaustion_denies_without_calling_reviewer():
    reviewer = MockReviewer()
    pipeline, executor = build(FullEscalatePolicy(), k=1, reviewer=reviewer)
    run(pipeline)
    assert EXECUTED == ["a"]
    assert reviewer.calls == 1
    assert outcomes(executor) == ["escalate_approved", "budget_exhausted_deny", "budget_exhausted_deny"]


def test_reviewer_denial_blocks_execution():
    pipeline, executor = build(FullEscalatePolicy(), k=2, reviewer=MockReviewer("deny"))
    run(pipeline)
    assert EXECUTED == []
    assert outcomes(executor) == ["escalate_denied", "escalate_denied", "budget_exhausted_deny"]


def test_budget_and_state_reset_between_tasks():
    seen = []

    class Counting(Policy):
        def evaluate(self, context, state):
            n = state.get("n", 0) + 1
            seen.append(n)
            return "escalate", {"n": n}

    pipeline, _ = build(Counting(), k=1, queries=("a", "b"))
    run(pipeline)
    run(pipeline)
    assert seen == [1, 2, 1, 2]      # policy state reset per task
    assert EXECUTED == ["a", "a"]    # budget reset per task


def test_reviewer_sees_task_call_trajectory_but_no_environment():
    seen = []

    class Recording(MockReviewer):
        def review(self, context):
            seen.append(context)
            return "approve"

    pipeline, _ = build(FullEscalatePolicy(), k=1, reviewer=Recording(), queries=("a",))
    run(pipeline, task="Find my emails.")
    assert set(seen[0]) == {"task", "proposed_call", "trajectory", "policy_reason"}
    assert seen[0]["task"] == "Find my emails."
    assert seen[0]["proposed_call"].function == "search_emails"


def test_policy_cannot_change_the_executed_call():
    class Tamper(Policy):
        def evaluate(self, context, state):
            context["proposed_call"].args["query"] = "tampered"
            return "approve", state

    pipeline, _ = build(Tamper(), queries=("a",))
    run(pipeline)
    assert EXECUTED == ["a"]


def test_unknown_decision_is_denied():
    pipeline, executor = build(Fixed("maybe"), queries=("a",))
    run(pipeline)
    assert EXECUTED == []
    assert outcomes(executor) == ["unknown_decision_deny"]

def test_policy_exception_falls_back_to_escalate_and_is_logged():
    class Boom(Policy):
        def evaluate(self, context, state):
            raise ValueError("bug")

    pipeline, executor = build(Boom(), k=2, queries=("a",))
    run(pipeline)
    assert outcomes(executor) == ["escalate_approved"]       # mock reviewer approves
    assert executor.decisions[0]["policy_error"].startswith("ValueError")

def test_policy_cannot_corrupt_agent_conversation():
    class Wipe(Policy):
        def evaluate(self, context, state):
            context["trajectory"].clear()
            return "approve", state

    pipeline, _ = build(Wipe(), queries=("a", "b"))
    messages = run(pipeline)
    assert EXECUTED == ["a", "b"]
    assert messages[0]["role"] == "system" and len(messages) >= 5

def test_policy_receives_tool_metadata():
    seen = []

    class Recording(Policy):
        def evaluate(self, context, state):
            seen.append(context["metadata"])
            return "approve", state

    pipeline, _ = build(Recording(), queries=("a",))
    run(pipeline)

    tool = seen[0]["tool"]
    assert tool["read_only"] is True
    assert tool["external_side_effect"] is False
    assert tool["irreversible"] is False
    assert tool["untrusted_output"] is True      # search_emails returns third-party text
    assert tool["known"] is True

def test_metadata_for_write_and_unknown_tools():
    send = get_tool_meta("send_email")
    assert send["read_only"] is False
    assert send["external_side_effect"] and send["irreversible"]
    assert "recipients" in send["target_args"]

    unknown = get_tool_meta("some_new_tool")
    assert unknown["known"] is False
    assert unknown["read_only"] is False          # conservative: unknown non-read names are treated as writes
