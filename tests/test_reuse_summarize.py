"""Live-run summarizer (plan U9). Hand-written runner fixtures; no model."""
import json

from p6_reuse import summarize


def _write_run(root, pipeline, policy, k, attack, rows, decisions, tokens=None):
    run = root / pipeline
    for key in rows:
        user_task, inj = key.split("|")
        trace = run / "slack" / user_task / attack / f"{inj if inj != 'None' else 'none'}.json"
        trace.parent.mkdir(parents=True, exist_ok=True)
        trace.write_text(json.dumps({"approval_decisions": decisions, "reviewer_unparseable": 1}))
    summary = {"policy": policy, "reviewer": "local_llm", "llm": "m", "k": k, "suite": "slack", "attack": attack,
               "n": len(rows), "tcr": sum(r["completed_safely"] for r in rows.values()) / len(rows),
               "hitl_load_completed": 1, "hitl_load_all": 2, "tasks_with_errors": 0,
               "token_usage": tokens or {}, "rows": rows}
    (run / f"summary_slack_{attack}.json").write_text(json.dumps(summary))


def test_summarize_builds_one_row_per_run_with_separate_attack_columns(tmp_path):
    reuse = [{"outcome": "escalate_denied", "reviewer_called": True, "reviewer_reason": "REVIEWER_PARSE_FAILURE",
              "scores": {"gate_ms": 1.0}},
             {"outcome": "auto_approve", "reviewer_called": False, "scores": {"reuse_approved": 1.0, "gate_ms": 3.0}},
             {"outcome": "auto_approve", "reviewer_called": False,
              "scores": {"reuse_approved": 1.0, "reuse_drilldown": 1.0, "gate_ms": 4.0}},
             {"outcome": "auto_deny", "reviewer_called": False, "scores": {"reuse_denied": 1.0, "gate_ms": 2.0}}]
    attacked = {"user_task_1|injection_task_1": {"utility": True, "attack_succeeded": False, "completed_safely": True}}
    clean = {"user_task_1|None": {"utility": True, "attack_succeeded": False, "completed_safely": True}}
    _write_run(tmp_path, "m-approval_reuse-local_llm-k2", "approval_reuse", 2, "important_instructions",
               attacked, reuse, {"policy": {"input_tokens": 0, "output_tokens": 0}})
    _write_run(tmp_path, "m-full_escalate-local_llm-k2", "full_escalate", 2, "none", clean, [])
    rows = summarize.collect(tmp_path)
    assert len(rows) == 2
    reuse_row = next(r for r in rows if r["policy"] == "approval_reuse")
    assert reuse_row["reviews_saved_approval"] == 2 and reuse_row["reviews_saved_drilldown"] == 1
    assert reuse_row["reviews_saved_denial"] == 1
    assert reuse_row["mean_gate_ms"] == 2.5
    # one from the legacy trace key, one from the P1 reviewer's REVIEWER_PARSE_FAILURE reason
    assert reuse_row["live_attack_success"] == 0.0 and reuse_row["reviewer_unparseable"] == 2
    clean_row = next(r for r in rows if r["policy"] == "full_escalate")
    assert clean_row["live_attack_success"] is None
    assert "replay_attack_success" not in reuse_row
    assert summarize.main(["--outdir", str(tmp_path)]) == 0
    assert (tmp_path / "p6_summary.md").read_text().count("| approval_reuse |") == 1
