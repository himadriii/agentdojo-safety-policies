from functools import partial

from agent_framework.policy import FullApprovePolicy, FullEscalatePolicy
from agent_framework.reviewer import MockReviewer
from agent_framework.llm_reviewer import LLMReviewer

# One line per policy: "cli_name": zero-argument factory.
POLICIES = {
    "full_approve": FullApprovePolicy,
    "full_escalate": FullEscalatePolicy,
}
REVIEWERS = {
    "mock": MockReviewer,
    "mock_deny": partial(MockReviewer, "deny"),
    "llm": LLMReviewer,    
    "local_llm": LLMReviewer,
}
