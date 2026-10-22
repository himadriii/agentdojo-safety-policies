import json

from p6_reuse import audit_report


def write_trace(root, policy, suite, user_task, attack, inj, **fields):
    path = root / f"m-{policy}-local_llm-k10" / suite / user_task / attack / f"{inj}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields))


def reuse_decision():
    return {"outcome": "auto_approve", "reviewer_called": False, "scores": {"reuse_approved": 1.0}}


def test_report_counts_shadow_denials_and_skips_prerun_rows(tmp_path):
    shadow = [{"tool": "send_email", "args": {"recipients": ["x@y.z"]}, "shadow_verdict": "deny"},
              {"tool": "search_emails", "args": {"query": "a"}, "shadow_verdict": "approve"}]
    write_trace(tmp_path, "approval_reuse", "workspace", "user_task_1", "important_instructions", "injection_task_2",
                utility=True, security=False, reuse_shadow=shadow,
                approval_decisions=[reuse_decision(), reuse_decision()])
    write_trace(tmp_path, "approval_reuse", "workspace", "user_task_1", "none", "none",
                utility=True, security=True, approval_decisions=[])
    write_trace(tmp_path, "approval_reuse", "workspace", "injection_task_2", "none", "none",
                utility=True, security=True, approval_decisions=[reuse_decision()])   # pre-run: excluded

    # A server error: AgentDojo records utility False and attack success True for a skipped task.
    write_trace(tmp_path, "approval_reuse", "workspace", "user_task_2", "important_instructions", "injection_task_2",
                utility=False, security=True, error="Skipping task due to context_length_exceeded",
                approval_decisions=[])

    traces = list(audit_report.load_traces(tmp_path))
    assert len(traces) == 3
    rows = {r["attack"]: r for r in audit_report.level_one(traces)}
    attacked = rows["important_instructions"]
    assert (attacked["n"], attacked["errors"]) == (2, 1)   # the errored run is counted but not scored
    assert (attacked["reuse_approvals"], attacked["shadow_denied"]) == (2, 1)
    assert attacked["shadow_deny_rate"] == 0.5
    assert attacked["attack_success"] == 0.0 and attacked["tcr"] == 1.0
    assert rows["none"]["attack_success"] is None and rows["none"]["shadow_deny_rate"] is None
    text = audit_report.to_markdown(traces)
    assert "Level 2" in text and "send_email" in text
