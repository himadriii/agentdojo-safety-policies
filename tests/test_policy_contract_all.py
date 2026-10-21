"""Contract tests applied to EVERY registered policy. No API calls."""
import copy
import time

import pytest
from agentdojo.functions_runtime import FunctionCall
from agentdojo.types import text_content_block_from_string as T

from agent_framework.registry import POLICIES
from agent_framework.tool_meta import get_tool_meta

DECISIONS = {"approve", "deny", "escalate"}


def make_ctx(task, call, history=()):
    traj = [{"role": "user", "content": [T(task)]}]
    for c, out in history:
        traj += [{"role": "assistant", "content": [T("")], "tool_calls": [c]},
                 {"role": "tool", "content": [T(out)], "tool_call_id": "t", "tool_call": c, "error": None}]
    traj.append({"role": "assistant", "content": [T("")], "tool_calls": [call]})
    # return {"task": task, "proposed_call": call, "environment": None, "trajectory": traj,
    #         "remaining_budget": 2,
    #         "metadata": {"step": len(history), "decision_history": [], "tool": get_tool_meta(call.function)}}
    return {"task": task, "proposed_call": call, "environment": None, "trajectory": traj,
            "remaining_budget": 2,
            "metadata": {"step": len(history), "decision_history": [], "tool": get_tool_meta(call.function)},
            "tools": {}}


def unpack(out):
    assert len(out) in (2, 3), "evaluate must return (decision, state) or (decision, state, info)"
    return out[0], out[1], (out[2] if len(out) == 3 else {})


CALL = FunctionCall(function="send_email", args={"recipients": ["a@b.com"], "subject": "s", "body": "b"})


@pytest.fixture(params=sorted(POLICIES))
def policy(request):
    try:
        return POLICIES[request.param]()
    except RuntimeError as e:          # e.g. a policy that needs an API key
        pytest.skip(f"cannot construct {request.param}: {e}")


def test_output_shape(policy):
    d, state, info = unpack(policy.evaluate(make_ctx("Email a@b.com hello", CALL), {}))
    assert d in DECISIONS and isinstance(state, dict)
    if "reason" in info:
        assert isinstance(info["reason"], str)
    assert all(isinstance(v, (int, float)) for v in (info.get("scores") or {}).values())


def test_does_not_mutate_inputs(policy):
    ctx = make_ctx("Find my files", CALL, [(FunctionCall(function="get_current_day", args={}), "2024-05-15")])
    before = copy.deepcopy(ctx)
    policy.evaluate(ctx, {})
    assert ctx["proposed_call"] == before["proposed_call"]
    assert ctx["trajectory"] == before["trajectory"]
    assert ctx["metadata"] == before["metadata"]


@pytest.mark.parametrize("task,call", [
    ("", CALL),
    ("task", FunctionCall(function="send_email", args={})),
    ("task", FunctionCall(function="totally_unknown_tool", args={"x": None})),
    ("héllo 你好 🚀", FunctionCall(function="send_email", args={"body": "é" * 5000})),
    ("x " * 5000, CALL),
])
def test_survives_odd_inputs(policy, task, call):
    assert unpack(policy.evaluate(make_ctx(task, call), {}))[0] in DECISIONS


@pytest.mark.parametrize("call", [
    FunctionCall(function="send_money", args={"recipient": "DE89...", "amount": 100}),
    FunctionCall(function="get_balance", args={}),
    FunctionCall(function="reserve_hotel", args={"hotel": "X"}),
    FunctionCall(function="send_direct_message", args={"recipient": "bob", "body": "hi"}),
])
def test_works_on_other_suites_tools(policy, call):
    """Held-out is cross-suite: a policy must not crash or hard-code workspace tool names."""
    assert unpack(policy.evaluate(make_ctx("Do my banking chores.", call), {}))[0] in DECISIONS


def test_decision_independent_of_call_history(policy):
    """Catches hidden instance state leaking between tasks (task state belongs in `state`)."""
    a = make_ctx("Email a@b.com hello", CALL)
    b = make_ctx("Delete file 7", FunctionCall(function="delete_file", args={"file_id": "9"}))
    first = unpack(policy.evaluate(a, {}))[0]
    for _ in range(3):
        policy.evaluate(b, {})
    assert unpack(policy.evaluate(a, {}))[0] == first


def test_state_is_not_shared_across_fresh_tasks(policy):
    s1 = unpack(policy.evaluate(make_ctx("Email a@b.com hello", CALL), {}))[1]
    s1["junk"] = 1
    s2 = unpack(policy.evaluate(make_ctx("Email a@b.com hello", CALL), {}))[1]
    assert "junk" not in s2


def test_latency_is_reasonable(policy):
    t = time.time()
    policy.evaluate(make_ctx("Email a@b.com hello", CALL), {})
    assert time.time() - t < 60

def test_works_without_optional_tools_key(policy):
    """Policies should read context.get("tools", {}) and not require it."""
    ctx = make_ctx("Email a@b.com hello", CALL)
    ctx.pop("tools")
    assert unpack(policy.evaluate(ctx, {}))[0] in DECISIONS

def test_does_not_mutate_tools(policy):
    ctx = make_ctx("Find my files", CALL)
    ctx["tools"] = {"send_email": {"description": "d", "parameters": {}}}
    before = copy.deepcopy(ctx["tools"])
    policy.evaluate(ctx, {})
    assert ctx["tools"] == before
