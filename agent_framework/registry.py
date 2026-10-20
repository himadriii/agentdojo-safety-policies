from agent_framework.policy import FullApprovePolicy, FullEscalatePolicy
from agent_framework.reviewer import MockReviewer
from agent_framework.policies.anomaly import AnomalyPolicy
from agent_framework.llm_reviewer import LLMReviewer

# One line per policy: "cli_name": zero-argument factory.
POLICIES = {
    "anomaly": AnomalyPolicy,
    "full_approve": FullApprovePolicy,
    "full_escalate": FullEscalatePolicy,
}
REVIEWERS = {"mock": MockReviewer, "llm": LLMReviewer}
