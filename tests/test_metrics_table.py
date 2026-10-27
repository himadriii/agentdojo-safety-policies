"""Offline tests for the configurable metrics table."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import metrics_table  # noqa: E402


def sample_row():
    return {
        "policy": "a < b", "k": 2, "suite": "pooled", "reviewer": "llm",
        "n_benign": 2, "tcr_benign": 1.0,
        "n_attack": 4, "tcr_attack": 0.5,
        "n_pooled": 6, "tcr_pooled": 4 / 6,
        "hitl_completed_pooled": 3, "hitl_all_pooled": 5,
        "agent_tokens": 100, "policy_tokens": 20, "reviewer_tokens": 30,
    }


def test_selects_only_requested_metrics_with_benign_first():
    columns = metrics_table.selected_columns(["tcr"])
    keys = [key for key, _ in columns]

    assert keys == ["policy", "k", "suite", "n_benign", "tcr_benign",
                    "n_attack", "tcr_attack", "n_pooled", "tcr_pooled"]
    assert "reviewer" not in keys and "agent_tokens" not in keys


def test_html_contains_only_selected_columns_and_escapes_values(tmp_path):
    columns = metrics_table.selected_columns(["hitl"])
    output = tmp_path / "table.html"

    metrics_table.write_html([sample_row()], columns, output)
    page = output.read_text(encoding="utf-8")

    assert "a &lt; b" in page and "a < b" not in page
    assert "HITL (completed)" in page
    assert "Attack TCR" not in page and "Agent tokens" not in page and "<th>Reviewer</th>" not in page
