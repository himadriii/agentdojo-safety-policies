
from collections.abc import Sequence

from agentdojo.agent_pipeline.tool_execution import (
    ToolsExecutor,
    is_string_list,
)
from agentdojo.agent_pipeline.llms.google_llm import EMPTY_FUNCTION_NAME
from agentdojo.functions_runtime import (
    EmptyEnv,
    Env,
    FunctionsRuntime,
)
from agentdojo.types import (
    ChatMessage,
    ChatToolResultMessage,
    text_content_block_from_string,
)

from agent_framework.budget import EscalationBudget
from agent_framework.policy import Policy
from agent_framework.reviewer import MockReviewer


class P1ToolsExecutor(ToolsExecutor):
    def __init__(
        self,
        policy=None,
        reviewer=None,
        budget=None,
    ):
        super().__init__()
        self.policy = policy if policy is not None else Policy()
        self.reviewer = reviewer if reviewer is not None else MockReviewer()
        self.budget = budget if budget is not None else EscalationBudget(limit=2)
        self.policy_state = {}

    def reset_for_new_task(self):
        """Reset task-scoped state and escalation budget."""
        self.budget.reset()
        self.policy_state = {}

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

        results = []

        for tool_call in tool_calls:
            tool_name = tool_call.function

            # Preserve AgentDojo's basic tool-call validation.
            if tool_name == EMPTY_FUNCTION_NAME:
                results.append(
                    self._result(
                        tool_call,
                        "",
                        "Empty function name provided.",
                    )
                )
                continue

            if tool_name not in runtime.functions:
                results.append(
                    self._result(
                        tool_call,
                        "",
                        f"Invalid tool {tool_name} provided.",
                    )
                )
                continue

            # Preserve AgentDojo's conversion of list-like arguments.
            for key, value in tool_call.args.items():
                if isinstance(value, str) and is_string_list(value):
                    from ast import literal_eval
                    tool_call.args[key] = literal_eval(value)

            context = {
                "proposed_call": tool_call,
                "environment": env,
                "trajectory": messages,
                "remaining_budget": self.budget.remaining,
                "metadata": extra_args,
            }

            decision, self.policy_state = self.policy.evaluate(context, self.policy_state)

            if decision == "approve":
                approved = True

            elif decision == "deny":
                approved = False

            elif decision == "escalate":
                if not self.budget.consume():
                    approved = False
                    print("[P1] Escalation budget exhausted; denying call.")
                else:
                    print(f"[P1] Budget after consumption: {self.budget.remaining}/{self.budget.limit}")
                    reviewer_decision = self.reviewer.review(context)
                    approved = reviewer_decision == "approve"

            else:
                approved = False
                print(f"[P1] Unknown policy decision {decision!r}; denying call.")

            if approved:
                print(f"[P1] APPROVED: {tool_name}")

                result, error = runtime.run_function(
                    env,
                    tool_name,
                    tool_call.args,
                )

                formatted_result = self.output_formatter(result)

                results.append(
                    self._result(tool_call, formatted_result, error)
                )
            else:
                print(f"[P1] DENIED: {tool_name}")

                results.append(
                    self._result(
                        tool_call,
                        "Tool call denied by the P1 approval policy.",
                        "PermissionDenied",
                    )
                )

        return query, runtime, env, [*messages, *results], extra_args

    @staticmethod
    def _result(tool_call, content, error):
        return ChatToolResultMessage(
            role="tool",
            content=[text_content_block_from_string(content)],
            tool_call_id=tool_call.id,
            tool_call=tool_call,
            error=error,
        )
