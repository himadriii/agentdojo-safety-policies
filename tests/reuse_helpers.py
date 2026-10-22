"""Shared pipeline fixtures for the P6 gate tests: scripted agent steps, test tools, executor wiring."""
from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.basic_elements import InitQuery, SystemMessage
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop
from agentdojo.functions_runtime import EmptyEnv, FunctionCall, FunctionsRuntime, make_function
from agentdojo.types import ChatAssistantMessage, text_content_block_from_string

from agent_framework.budget import EscalationBudget
from agent_framework.policies.approval_reuse.policy import ApprovalReusePolicy
from agent_framework.reviewer import MockReviewer
from agent_framework.tools_executor import P1ToolsExecutor, ResetTaskState

EXECUTED = []


def search_emails(query: str) -> str:
    """Search emails.

    :param query: The search query.
    """
    EXECUTED.append(("search_emails", query))
    return f"Found 1 email matching '{query}'"


def send_email(recipients: list[str], body: str) -> str:
    """Send an email.

    :param recipients: The recipients.
    :param body: The body.
    """
    EXECUTED.append(("send_email", tuple(recipients)))
    return "sent"


def flaky_tool(x: str) -> str:
    """A tool that always fails.

    :param x: Anything.
    """
    EXECUTED.append(("flaky_tool", x))
    raise ValueError("backend down")


def get_all_hotels_in_city(city: str) -> str:
    """Get all hotels in the given city.

    :param city: The city.
    """
    EXECUTED.append(("get_all_hotels_in_city", city))
    return "Le Marais Boutique, Good Night"


def get_hotels_prices(hotel_names: list[str]) -> str:
    """Get the prices of the given hotels.

    :param hotel_names: The hotels.
    """
    EXECUTED.append(("get_hotels_prices", tuple(hotel_names)))
    return "Le Marais Boutique: 180, Good Night: 120, Annex Hotel: 90"


def get_hotels_address(hotel_name: str) -> str:
    """Get the address of the given hotel.

    :param hotel_name: The hotel.
    """
    EXECUTED.append(("get_hotels_address", hotel_name))
    return "1 Rue de Rivoli"


def list_files() -> str:
    """List all files in the drive."""
    EXECUTED.append(("list_files", None))
    return "report.docx"


class Steps(BasePipelineElement):
    """Emits one assistant message per step; each step is a list of FunctionCalls."""

    def __init__(self, steps):
        self.steps = steps

    def query(self, query, runtime, env=EmptyEnv(), messages=(), extra_args={}):
        step = sum(1 for m in messages if m["role"] == "assistant")
        calls = self.steps[step] if step < len(self.steps) else None
        msg = ChatAssistantMessage(role="assistant", content=[text_content_block_from_string("ok")],
                                   tool_calls=calls)
        return query, runtime, env, [*messages, msg], extra_args


def call(function, call_id=None, **args):
    return FunctionCall(function=function, args=args, id=call_id)


def build(steps, policy=None, k=2, reviewer=None):
    EXECUTED.clear()
    executor = P1ToolsExecutor(policy=policy or ApprovalReusePolicy(),
                               reviewer=reviewer or MockReviewer(), budget=EscalationBudget(limit=k))
    llm = Steps(steps)
    pipeline = AgentPipeline([ResetTaskState(executor), SystemMessage("test agent"), InitQuery(),
                              llm, ToolsExecutionLoop([executor, llm])])
    return pipeline, executor


def run(pipeline, task="Find my flight emails and email bob@example.com."):
    runtime = FunctionsRuntime([make_function(f) for f in (search_emails, send_email, flaky_tool,
                                                           get_all_hotels_in_city, get_hotels_prices,
                                                           get_hotels_address, list_files)])
    pipeline.query(task, runtime, EmptyEnv(), [], {})


def outcomes(executor):
    return [d["outcome"] for d in executor.decisions]
