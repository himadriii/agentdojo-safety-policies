import json
import logging
import re
from ast import literal_eval
from collections.abc import Sequence

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.llms.google_llm import EMPTY_FUNCTION_NAME
from agentdojo.agent_pipeline.tool_execution import (
    ToolsExecutor,
    is_string_list,
    tool_result_to_str,
)
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionsRuntime
from agentdojo.logging import Logger
from agentdojo.types import (
    ChatMessage,
    ChatToolResultMessage,
    get_text_content_as_str,
    text_content_block_from_string,
)

from agent_framework.budget import EscalationBudget
from agent_framework.policy import FullEscalatePolicy
from agent_framework.reviewer import MockReviewer, build_reviewer_context
from agent_framework.usage import TRACKER

log = logging.getLogger(__name__)


def describe_tool_effects(tool) -> dict:
    """Infer conservative effects from a runtime tool's public contract."""

    name = str(getattr(tool, "name", ""))
    description = str(getattr(tool, "description", "") or "")
    text = f"{name.replace('_', ' ')} {description}".casefold()

    deletes = bool(re.search(r"\b(delete|deletes|deleted|cancel|cancels|cancellation)\b", text))
    communicates = bool(
        re.match(r"^(?:send|share)[ _]", name.casefold())
        or re.search(r"\b(send|sends|share|shares|shared)\b", description.casefold())
        or re.search(
            r"\bemail(?:s|ed|ing)?\s+(?:the\s+)?(?:new\s+)?participants?\b",
            description.casefold(),
        )
    )
    changes_state = bool(
        deletes
        or communicates
        or re.search(
            r"\b(create|creates|append|adds?|reschedule|reschedules|"
            r"update|updates|write|writes|mark|marks|marked)\b",
            text,
        )
    )
    reads = bool(
        re.search(r"\b(get|returns?|retrieve|search|searches|find|finds|list|read)\b", text)
    )

    effects = []
    if reads:
        effects.append("read")
    if changes_state:
        effects.append("state_change")
    if communicates:
        effects.append("communication")
    if deletes:
        effects.append("deletion")
    if not effects:
        effects.append("unknown")

    return {
        "tool_name": name,
        "description": description,
        "effects": effects,
        "non_mutating_read": effects == ["read"],
        "source": "runtime_tool_contract",
    }

# Goes in BOTH content and error: every provider converter sends `error`
# (and ignores `content`) when error is set.
DENIAL_MESSAGE = (
    "PermissionDenied: this tool call was blocked by the approval policy and was "
    "NOT executed. Do not retry the same call; continue the task another way or "
    "tell the user it could not be completed."
)


class P1ToolsExecutor(ToolsExecutor):
    def __init__(self, policy=None, reviewer=None, budget=None, tool_output_formatter=tool_result_to_str):
        super().__init__(tool_output_formatter)
        self.policy = policy if policy is not None else FullEscalatePolicy()
        self.reviewer = reviewer if reviewer is not None else MockReviewer()
        self.budget = budget if budget is not None else EscalationBudget(limit=2)
        self.policy_state = {}
        self.decisions = []

    def reset_for_new_task(self):
        """Reset task-scoped state: escalation budget, policy state, logs, token counts."""
        self.budget.reset()
        self.policy_state = {}
        self.decisions = []
        TRACKER.reset()

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: Sequence[ChatMessage] = (),
        extra_args: dict = {},
    ):
        if not messages:
            return query, runtime, env, messages, extra_args

        last_message = messages[-1]
        if last_message["role"] != "assistant":
            return query, runtime, env, messages, extra_args

        tool_calls = last_message["tool_calls"]
        if not tool_calls:
            return query, runtime, env, messages, extra_args

        task_text = self._task_text(messages)
        results = []

        for tool_call in tool_calls:
            tool_name = tool_call.function

            # Preserve AgentDojo's basic tool-call validation.
            if tool_name == EMPTY_FUNCTION_NAME:
                results.append(self._result(
                    tool_call, "", "Empty function name provided. Provide a valid function name."))
                continue
            if tool_name not in runtime.functions:
                results.append(self._result(tool_call, "", f"Invalid tool {tool_name} provided."))
                continue

            # Preserve AgentDojo's conversion of list-like string arguments.
            for key, value in tool_call.args.items():
                if isinstance(value, str) and is_string_list(value):
                    tool_call.args[key] = literal_eval(value)

            context = {
                "task": task_text,
                "proposed_call": tool_call.model_copy(deep=True),  # policies can't mutate the real call
                "environment": env,
                "trajectory": messages,
                "remaining_budget": self.budget.remaining,
                "metadata": extra_args,
                "tool_effects": describe_tool_effects(runtime.functions[tool_name]),
            }

            decision, self.policy_state, info = self._unpack(
                self.policy.evaluate(context, self.policy_state)
            )
            outcome, approved, reviewer_called = self._resolve(decision, context, info)

            self.decisions.append({
                "tool": tool_name,
                "args": dict(tool_call.args),
                "decision": decision,
                "outcome": outcome,
                "executed": approved,
                "reviewer_called": reviewer_called,
                "budget_remaining": self.budget.remaining,
                "reason": info.get("reason"),
                "scores": info.get("scores"),
                "validation_errors": info.get("validation_errors"),
                "evidence": info.get("evidence"),
            })
            trace_logger = Logger.get()
            if hasattr(trace_logger, "set_contextarg"):  # NullLogger has no such method
                trace_logger.set_contextarg("approval_decisions", self.decisions)

            log_method = log.info if approved else log.warning
            log_method(
                "[P1] %s tool=%s args=%s decision=%s outcome=%s "
                "budget_remaining=%s reason=%s%s",
                "APPROVED" if approved else "DENIED",
                tool_name,
                json.dumps(tool_call.args, ensure_ascii=False),
                decision,
                outcome,
                self.budget.remaining,
                info.get("reason") or "<no reason provided>",
                (
                    " validation_errors="
                    + json.dumps(info["validation_errors"], ensure_ascii=False)
                    if info.get("validation_errors")
                    else ""
                ),
            )
            if info.get("evidence") is not None:
                log.info(
                    "[P1:EVIDENCE] tool=%s %s",
                    tool_name,
                    json.dumps(info["evidence"], ensure_ascii=False),
                )

            if approved:
                result, error = runtime.run_function(env, tool_name, tool_call.args)
                results.append(self._result(tool_call, self.output_formatter(result), error))
            else:
                results.append(self._result(tool_call, DENIAL_MESSAGE, DENIAL_MESSAGE))

        return query, runtime, env, [*messages, *results], extra_args

    # ---- helpers -------------------------------------------------------

    def _resolve(self, decision, context, info):
        """Returns (outcome, approved, reviewer_called)."""
        if decision == "approve":
            return "auto_approve", True, False
        if decision == "deny":
            return "auto_deny", False, False
        if decision == "escalate":
            if not self.budget.consume():
                return "budget_exhausted_deny", False, False
            reviewer_context = build_reviewer_context(
                context["task"], context["proposed_call"], context["trajectory"], info.get("reason")
            )
            approved = self.reviewer.review(reviewer_context) == "approve"
            return ("escalate_approved" if approved else "escalate_denied"), approved, True
        log.warning("[P1] Unknown policy decision %r; denying call.", decision)
        return "unknown_decision_deny", False, False

    @staticmethod
    def _unpack(result):
        if len(result) == 3:
            decision, state, info = result
        else:
            (decision, state), info = result, {}
        return decision, state, (info or {})

    @staticmethod
    def _task_text(messages):
        first_user = next((m for m in messages if m["role"] == "user"), None)
        return get_text_content_as_str(first_user["content"]) if first_user else ""

    @staticmethod
    def _result(tool_call, content, error):
        return ChatToolResultMessage(
            role="tool",
            content=[text_content_block_from_string(content)],
            tool_call_id=tool_call.id,
            tool_call=tool_call,
            error=error,
        )


class ResetTaskState(BasePipelineElement):
    """First pipeline element: resets budget, policy state and token counts per task
    (AgentDojo may call the pipeline more than once per task)."""

    def __init__(self, executor: P1ToolsExecutor):
        self.executor = executor

    def query(self, query, runtime, env=EmptyEnv(), messages=(), extra_args={}):
        self.executor.reset_for_new_task()
        return query, runtime, env, messages, extra_args
