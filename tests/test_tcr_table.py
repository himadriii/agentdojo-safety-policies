"""Offline test of the pooled TCR table (no model, no AgentDojo needed)."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("tcr_table", Path(__file__).resolve().parent.parent / "scripts" / "tcr_table.py")
tcr_table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcr_table)


def write(folder, suite, attack, rows, hitl_completed, hitl_all):
    summary = {
        "policy": "full_escalate", "k": 2, "reviewer": "llm", "suite": suite, "attack": attack,
        "rows": {key: {"completed_safely": ok} for key, ok in rows.items()},
        "hitl_load_completed": hitl_completed, "hitl_load_all": hitl_all,
        "token_usage": {"agent": {"calls": 3, "input_tokens": 100, "output_tokens": 10},
                        "reviewer": {"calls": 2, "input_tokens": 50, "output_tokens": 5}},
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"summary_{suite}_{attack}.json").write_text(json.dumps(summary))


def test_pooled_counts_attack_and_benign(tmp_path):
    run = tmp_path / "lmstudio-x-full_escalate-llmv2-k2-abc"
    # attack: 4 pairs, 1 completed safely, 3 escalations on the completed task, 6 in all
    write(run, "slack", "important_instructions", {"a|1": True, "a|2": False, "b|1": False, "b|2": False}, 3, 6)
    # benign: 2 tasks, both completed, 1 escalation each
    write(run, "slack", "none", {"a|none": True, "b|none": True}, 2, 2)
    # a second suite, attack only (no benign yet)
    write(run, "banking", "important_instructions", {"c|1": True, "c|2": True}, 1, 1)
    [row] = tcr_table.table(tcr_table.load_runs([tmp_path]))
    assert (row["n_attack"], row["tcr_attack"]) == (6, 3 / 6)
    assert (row["n_benign"], row["tcr_benign"]) == (2, 1.0)
    assert (row["n_pooled"], row["tcr_pooled"]) == (8, 5 / 8)
    assert row["hitl_completed_pooled"] == 3 + 2 + 1
    assert row["agent_tokens"] == 3 * 110 and row["reviewer_tokens"] == 3 * 55


def test_attack_only_run_has_no_benign(tmp_path):
    run = tmp_path / "r"
    write(run, "slack", "important_instructions", {"a|1": True, "a|2": False}, 1, 2)
    [row] = tcr_table.table(tcr_table.load_runs([tmp_path]))
    assert row["n_benign"] == 0 and row["tcr_benign"] is None and row["tcr_pooled"] == row["tcr_attack"] == 0.5
