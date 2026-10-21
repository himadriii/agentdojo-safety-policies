from functools import partial

from agent_framework.policy import FullApprovePolicy, FullEscalatePolicy
from agent_framework.policies.supervised_risk import SupervisedRiskPolicy
from agent_framework.reviewer import MockReviewer
from agent_framework.llm_reviewer import LLMReviewer

# One line per policy: "cli_name": zero-argument factory.
POLICIES = {
    "full_approve": FullApprovePolicy,
    "full_escalate": FullEscalatePolicy,
    "supervised_risk": SupervisedRiskPolicy,
}
REVIEWERS = {
    "mock": MockReviewer,
    "mock_deny": partial(MockReviewer, "deny"),
    "llm": LLMReviewer,    
    "local_llm": LLMReviewer,
}
