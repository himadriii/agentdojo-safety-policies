from agent_framework.policy import FullApprovePolicy, FullEscalatePolicy
from agent_framework.reviewer import MockReviewer
from agent_framework.policies.provenance_gate import ProvenancePolicy


# One line per policy: "cli_name": zero-argument factory.
POLICIES = {
    "full_approve": FullApprovePolicy,
    "full_escalate": FullEscalatePolicy,
    "provenance": ProvenancePolicy,
}
REVIEWERS = {"mock": MockReviewer}
