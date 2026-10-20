import logging
import copy
import time
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
from agent_framework.tool_meta import get_tool_meta

log = logging.getLogger(__name__)

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
        self._reviewer_reason = None
        self._tool_schemas = {}

    def reset_for_new_task(self):
        """Reset task-scoped state: escalation budget, policy state, logs, token counts."""
        self.budget.reset()
        self.policy_state = {}
        self.decisions = []
        TRACKER.reset()

    def _tools_view(self, runtime):
        """name -> {description, parameters}. Computed once per tool and cached."""
        for name, fn in runtime.functions.items():
            if name not in self._tool_schemas:
                self._tool_schemas[name] = {
                    "description": fn.description,
                    "parameters": fn.parameters.model_json_schema(),
                }
        return copy.deepcopy(self._tool_schemas)   # a policy can't mutate the cache

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
                "proposed_call": tool_call.model_copy(deep=True),
                "environment": env,                              # read-only by contract
                "trajectory": copy.deepcopy(list(messages)),     # a policy can't corrupt the agent's conversation
                "remaining_budget": self.budget.remaining,
                "metadata": {"step": len(self.decisions),        # fresh dict per call
                             "decision_history": copy.deepcopy(self.decisions),
                             "tool": get_tool_meta(tool_name)},
                "tools": self._tools_view(runtime),
            }

            policy_error = None
            t0 = time.perf_counter()
            try:
                decision, self.policy_state, info = self._unpack(
                    self.policy.evaluate(context, self.policy_state))
            except Exception as exc:       # one buggy policy must not kill a whole benchmark run
                log.exception("[P1] policy raised; falling back to escalate")
                decision, info = "escalate", {"reason": "POLICY_ERROR", "scores": {}}
                policy_error = f"{type(exc).__name__}: {exc}"[:300]
            latency = time.perf_counter() - t0

            outcome, approved, reviewer_called = self._resolve(decision, context, info)

            self.decisions.append({
                "tool": tool_name,
                "args": dict(tool_call.args),
                "decision": decision,
                "outcome": outcome,
                "executed": approved,
                "reviewer_called": reviewer_called,
                "reviewer_reason": self._reviewer_reason if reviewer_called else None,
                "budget_remaining": self.budget.remaining,
                "reason": info.get("reason"),
                "scores": info.get("scores"),
                "policy_error": policy_error,
                "policy_latency_s": round(latency, 4),
            })

            trace_logger = Logger.get()
            if hasattr(trace_logger, "set_contextarg"):  # NullLogger has no such method
                trace_logger.set_contextarg("approval_decisions", self.decisions)

            log.info("[P1] %s: %s (%s)", "APPROVED" if approved else "DENIED", tool_name, outcome)

            if approved:
                result, error = runtime.run_function(env, tool_name, tool_call.args)
                results.append(self._result(tool_call, self.output_formatter(result), error))
            else:
                results.append(self._result(tool_call, DENIAL_MESSAGE, DENIAL_MESSAGE))

        return query, runtime, env, [*messages, *results], extra_args

    # ---- helpers -------------------------------------------------------

    def _resolve(self, decision, context, info):
        """Returns (outcome, approved, reviewer_called)."""
        self._reviewer_reason = None
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
            self._reviewer_reason = getattr(self.reviewer, "last_reason", None)
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
