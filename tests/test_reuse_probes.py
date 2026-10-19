"""Offline reuse probe set (plan U6). No model, no network."""
import json
from functools import lru_cache

from agent_framework.policies.approval_reuse.tool_table import TOOLS
from p6_reuse import probes

MUTATIONS = {"key", "amount_up", "amount_down", "free_text", "injected_link", "injected_code"}


@lru_cache(maxsize=1)
def generated():
    return tuple(probes.generate_probes())


def test_every_suite_generates_each_mutation_its_tools_support_and_union_covers_all():
    by_suite = {}
    for p in generated():
        by_suite.setdefault(p["suite"], set()).add(p["mutation"].split(":")[0])
    for suite in ("slack", "workspace", "travel"):
        assert {"key", "free_text", "injected_link", "injected_code"} <= by_suite[suite], suite
    assert {"amount_up", "amount_down"} <= by_suite["banking"]
    assert set().union(*by_suite.values()) == MUTATIONS


def test_every_side_effect_key_argument_is_mutated():
    mutated = {(p["tool"], p["mutation"].split(":", 1)[1]) for p in generated() if p["mutation"].startswith("key:")}
    for tool, spec in TOOLS.items():
        if spec.side_effect:
            for arg in spec.key:
                assert (tool, arg) in mutated, f"{tool}.{arg} never mutated"


def test_p6_predicate_has_zero_violations():
    summary = probes.score(generated())
    assert summary["approval_reuse"]["violations"] == 0


def test_similarity_predicate_overgeneralizes_on_injected_links():
    summary = probes.score(generated())
    assert summary["similarity_reuse"]["by_mutation"]["injected_link"]["violations"] >= 1


def test_free_text_only_changes_are_covered_by_p6():
    rows = probes.score_rows(generated())
    free = [r for r in rows if r["mutation"] == "free_text"]
    assert free and all(r["approval_reuse"] for r in free)


def test_cli_writes_outputs_and_fails_on_a_violation(tmp_path):
    assert probes.main(["--outdir", str(tmp_path)]) == 0
    assert (tmp_path / "probes.csv").exists()
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["approval_reuse"]["violations"] == 0

    def always_covered(tool, new_args, approved_args, task):
        return True

    assert probes.main(["--outdir", str(tmp_path)], p6_predicate=always_covered) == 1
