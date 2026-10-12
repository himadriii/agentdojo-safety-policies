from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.tool_execution import ToolsExecutionLoop
from agent_framework.tools_executor import P1ToolsExecutor
from agentdojo.agent_pipeline.basic_elements import (
    SystemMessage,
    InitQuery
)
from agentdojo.functions_runtime import (
    FunctionCall,
    FunctionsRuntime,
    EmptyEnv,
    make_function,
)
from agentdojo.types import (
    ChatAssistantMessage,
    ChatMessage,
    text_content_block_from_string,
)
from agent_framework.budget import EscalationBudget
from agent_framework.policy import FullApprovePolicy, FullEscalatePolicy
from agent_framework.reviewer import MockReviewer

tool_execution_count = 0

def search_emails(query: str) -> str:
    """
    Search emails using a query.
    
    :param query: The search query to use.
    """
    global tool_execution_count
    tool_execution_count += 1
    print(f"\n[TEST TOOL] search_emails called with query='{query}'")
    return f"Found 1 email matching '{query}'"

# class FixedPolicy:
#     """Returns a predefined policy decision."""
#     def __init__(self,decision):
#         self.decision = decision

#     def evaluate(self,context,state):
#         return self.decision, state

# class FixedReviewer:
#     """Returns a predefined reviewer decision and counts calls."""

#     def __init__(self, decision):
#         self.decision = decision
#         self.calls = 0

#     def review(self, context):
#         self.calls += 1
#         print(
#             f"[TEST REVIEWER] Called "
#             f"(call #{self.calls}); decision={self.decision}"
#         )
#         return self.decision   

class MockLLM(BasePipelineElement):

    def __init__(self, num_tool_calls=3):
        self.calls = 0
        self.num_tool_calls = num_tool_calls

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env=EmptyEnv(),
        messages: list[ChatMessage] = [],
        extra_args: dict = {},
    ):
        self.calls +=1
        print(f"\n [MOCK LLM] Call #{self.calls}")

        if self.calls <= self.num_tool_calls:

            search_queries = [
                "flight",
                "hotel",
                "booking confirmation"
            ]
            search_query = search_queries[self.calls - 1]

            tool_call = FunctionCall(
                function="search_emails",
                args={"query":search_query},
            )

            assistant_message = ChatAssistantMessage(
                role="assistant",
                content=[
                    text_content_block_from_string(
                        f"Searching for {search_query}"
                    )
                ],
                tool_calls=[tool_call]
            )

            print(
                "[MOCK LLM] Producing tool call: "
                f"#{self.calls}: search_emails(query='{search_query}')"   
            )

        else:
            assistant_message = ChatAssistantMessage(
                role="assistant",
                content=[
                    text_content_block_from_string(
                        "Finished searching for the requested emails"
                    )
                ],
                tool_calls=None
            )
            print("[MOCK LLM] Producing final answer")

        new_messages = [
            *messages,
            assistant_message
        ]

        return (
            query, 
            runtime, 
            env, 
            new_messages,
            extra_args
        )

def run_test_case(policy, budget=None, num_tool_calls=3):
    global tool_execution_count
    tool_execution_count = 0

    # reviewer = FixedReviewer(reviewer_decision)
    if budget is None:
        budget = EscalationBudget(limit=2)

    reviewer = MockReviewer()
    mock_llm = MockLLM(num_tool_calls=num_tool_calls)

    test_function = make_function(search_emails)
    runtime = FunctionsRuntime(functions=[test_function])

    executor = P1ToolsExecutor(
        policy=policy,
        reviewer=reviewer,
        budget=budget
    )

    tools_loop = ToolsExecutionLoop([executor, mock_llm])

    pipeline = AgentPipeline(
        [
            SystemMessage("You are a test agent"),
            InitQuery(),
            mock_llm,
            tools_loop
        ]
    )

    query, runtime, env, messages, extra_args = pipeline.query(
        query="Find my my flight and hotel emails.",
        runtime=runtime,
        env=EmptyEnv(),
        messages=[],
        extra_args={},
    )
    return tool_execution_count,reviewer.calls, budget, messages

def test_full_approve():
    executions, reviewer_calls, budget, _ = run_test_case(
        policy=FullApprovePolicy(),
        budget=EscalationBudget(limit=2),
        num_tool_calls=3
    )

    assert executions == 3, f"Expected 1 execution, got {executions}"
    assert reviewer_calls == 0, f"Expected 0 reviewer calls, got {reviewer_calls}"
    assert budget.used == 0, f"Expected 0 escalations used, got {budget.used}"

    print("PASS: FullApprovePolicy")
    print(f"Tool executions: {executions}")
    print(f"Reviewer calls: {reviewer_calls}")
    print(f"Budget remaining: {budget.remaining}")


def test_full_escalate():
    executions, reviewer_calls, budget, _ = run_test_case(
        policy=FullEscalatePolicy(),
        budget=EscalationBudget(limit=2),
        num_tool_calls=3,
    )

    assert executions == 2, f"Expected 1 execution, got {executions}"
    assert reviewer_calls == 2, f"Expected 1 reviewer call, got {reviewer_calls}"
    assert budget.used == 2, f"Expected 1 escalation used, got {budget.used}"
    assert budget.remaining == 0, f"Expected 0 remaining budget, got {budget.remaining}"

    print("PASS: FullEscalatePolicy")
    print(f"Tool executions: {executions}")
    print(f"Reviewer calls: {reviewer_calls}")
    print(f"Budget remaining: {budget.remaining}")


if __name__ == "__main__":
    # test_full_approve()
    print()
    test_full_escalate()

