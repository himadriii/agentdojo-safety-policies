from agent_framework.policy import FullApprovePolicy, FullEscalatePolicy
from agent_framework.reviewer import MockReviewer

# One line per policy: "cli_name": zero-argument factory.
POLICIES = {
    "full_approve": FullApprovePolicy,
    "full_escalate": FullEscalatePolicy,
}
REVIEWERS = {"mock": MockReviewer}
