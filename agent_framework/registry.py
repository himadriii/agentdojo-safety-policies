from functools import partial

from agent_framework.policy import FullApprovePolicy, FullEscalatePolicy
from agent_framework.policies.supervised_risk import SupervisedRiskPolicy
from agent_framework.policies.approval_reuse.policy import ApprovalReusePolicy
from agent_framework.policies.approval_reuse.similarity import SimilarityReusePolicy
from agent_framework.policies.plan_consistency import PlanConsistencyPolicy
from agent_framework.policies.p4_p6_p7_combined_or import P4P6P7CombinedOrPolicy
from agent_framework.reviewer import MockReviewer
from agent_framework.policies.provenance_gate import ProvenancePolicy
from agent_framework.llm_reviewer import LLMReviewer
from agent_framework.policies.anomaly import AnomalyPolicy

# One line per policy: "cli_name": zero-argument factory.
POLICIES = {
    "anomaly": AnomalyPolicy,
    "full_approve": FullApprovePolicy,
    "full_escalate": FullEscalatePolicy,
    "supervised_risk": SupervisedRiskPolicy,
    "approval_reuse": ApprovalReusePolicy,
    "similarity_reuse": SimilarityReusePolicy,
    "plan_consistency": PlanConsistencyPolicy,
    "provenance": ProvenancePolicy,
    "p4_p6_p7_combined_or": P4P6P7CombinedOrPolicy,
}
REVIEWERS = {
    "mock": MockReviewer,
    "mock_deny": partial(MockReviewer, "deny"),
    "llm": LLMReviewer,
    "local_llm": LLMReviewer,
}
