"""P6: approval reuse gate.

Wraps a base policy (full-escalate by default). When the base escalates, the gate
checks what the reviewer already decided earlier in this task:
    a call repeating a reviewer-denied call      -> deny, no budget spent
    a call covered by a reviewer approval        -> approve, no budget spent
    otherwise                                    -> escalate, and remember it
The runner does not report reviewer verdicts to policies, so the gate reads them off
the trajectory: the tool result for a call it escalated either carries the runner's
denial message (denied) or not (executed after approval). Escalations made with no
budget left were denied by the runner, not the reviewer, and are dropped.

All memory lives in the task-scoped `state`; nothing carries across tasks.
"""
import json
import time

from agent_framework.policies.approval_reuse.matching import covers_approval, matches_denial
from agent_framework.policy import FullEscalatePolicy, Policy
from agent_framework.tools_executor import DENIAL_MESSAGE


def _unpack(result):
    if len(result) == 3:
        return result
    decision, state = result
    return decision, state, {}


def _describe(record):
    return f"{record['function']}({json.dumps(record['args'], default=str, sort_keys=True)})"


class ApprovalReusePolicy(Policy):
    name = "approval_reuse"

    def __init__(self, base=None, covers=covers_approval, remember_denials=True):
        self.base = base if base is not None else FullEscalatePolicy()
        self.covers = covers
        self.remember_denials = remember_denials

    def evaluate(self, context, state):
        start = time.perf_counter()
        state = {
            "base": state.get("base", {}),
            "pending": list(state.get("pending", [])),
            "approved": list(state.get("approved", [])),
            "denied": list(state.get("denied", [])),
        }
        try:
            decision, state["base"], info = _unpack(self.base.evaluate(context, state["base"]))
            info = dict(info or {})
        except Exception as exc:
            return "escalate", state, {"reason": f"base policy failed ({type(exc).__name__}: {exc})"}

        try:
            self._resolve_pending(context["trajectory"], state)
            if decision == "escalate":
                decision, info = self._reuse(context, state, info)
        except Exception as exc:  # reuse must never crash a task run
            info["reason"] = f"{info.get('reason') or 'base decision'}; reuse skipped ({type(exc).__name__})"

        scores = dict(info.get("scores") or {})
        scores.setdefault("reuse_approved", 0.0)
        scores.setdefault("reuse_denied", 0.0)
        scores["gate_ms"] = (time.perf_counter() - start) * 1000.0
        info["scores"] = scores
        return decision, state, info

    def _reuse(self, context, state, info):
        call = context["proposed_call"]
        args = dict(call.args)
        if self.remember_denials:
            for record in state["denied"]:
                if record["function"] == call.function and matches_denial(call.function, args, record["args"]):
                    info["reason"] = f"repeats a call the reviewer denied earlier in this task: {_describe(record)}"
                    info.setdefault("scores", {})["reuse_denied"] = 1.0
                    return "deny", info
        for record in state["approved"]:
            if record["function"] == call.function and self.covers(call.function, args, record["args"],
                                                                   context["task"]):
                info["reason"] = f"covered by a reviewer approval earlier in this task: {_describe(record)}"
                info.setdefault("scores", {})["reuse_approved"] = 1.0
                return "approve", info
        state["pending"].append({
            "id": call.id,
            "function": call.function,
            "args": args,
            "budget": context["remaining_budget"],
            "index": len(context["trajectory"]),
        })
        info.setdefault("reason", "no earlier reviewer decision covers this call")
        return "escalate", info

    @staticmethod
    def _resolve_pending(trajectory, state):
        used = set()
        still_pending = []
        for record in state["pending"]:
            result = None
            for i in range(record["index"], len(trajectory)):
                message = trajectory[i]
                if i in used or message["role"] != "tool":
                    continue
                tool_call = message.get("tool_call")
                if record["id"] is not None:
                    hit = message.get("tool_call_id") == record["id"]
                else:
                    hit = (tool_call is not None and tool_call.function == record["function"]
                           and dict(tool_call.args) == record["args"])
                if hit:
                    used.add(i)
                    result = message
                    break
            if result is None:
                still_pending.append(record)
            elif record["budget"] <= 0:
                continue  # the runner denied it for budget; the reviewer never saw it
            elif result.get("error") == DENIAL_MESSAGE:
                state["denied"].append(record)
            else:
                state["approved"].append(record)
        state["pending"] = still_pending
