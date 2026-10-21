import pytest
from agentdojo.task_suite.load_suites import get_suites

from agent_framework.tool_meta import TOOL_META, get_tool_meta

SUITES = get_suites("v1.2")


@pytest.mark.parametrize("suite_name", sorted(SUITES))
def test_every_tool_in_suite_is_labeled(suite_name):
    names = {t.name for t in SUITES[suite_name].tools}
    assert names - set(TOOL_META) == set(), f"add these {suite_name} tools to TOOL_META"


def test_no_stale_entries():
    all_names = {t.name for s in SUITES.values() for t in s.tools}
    assert set(TOOL_META) - all_names == set()


@pytest.mark.parametrize("name", sorted(TOOL_META))
def test_labels_are_consistent(name):
    m = TOOL_META[name]
    if m.read_only:
        assert not m.external_side_effect and not m.irreversible and not m.target_args == ("x",)
    else:
        assert m.target_args or name in {"get_current_day"}   # every write names what it affects
        assert not m.sensitive_output


def test_target_args_exist_in_the_real_tool_signatures():
    """Catches wrong argument names (these were labeled from memory)."""
    bad = []
    for suite in SUITES.values():
        for tool in suite.tools:
            meta = TOOL_META.get(tool.name)
            if meta is None:
                continue
            params = set(tool.parameters.model_fields)
            bad += [(tool.name, a) for a in meta.target_args if a not in params]
    assert not bad, f"target_args not found in tool parameters: {sorted(set(bad))}"


def test_unknown_tools_fall_back_conservatively():
    r = get_tool_meta("get_something_new")
    assert r["read_only"] and not r["known"]
    w = get_tool_meta("transfer_something")
    assert not w["read_only"] and w["external_side_effect"] and w["irreversible"] and not w["known"]
