"""Tool table and argument matching for the P6 approval-reuse gate (plan U1)."""
from agentdojo.task_suite.load_suites import get_suites

from agent_framework.policies.approval_reuse.matching import covers_approval, matches_denial
from agent_framework.policies.approval_reuse.tool_table import LIVE_SUITES, TOOLS, spec_for

TASK = "Tell Alice the meeting moved, then summarise my unread emails."


# ---- read reuse and URL keys (AE1) -------------------------------------------

def test_read_approval_covers_same_tool_with_other_args():
    assert covers_approval("search_emails", {"query": "hotel"}, {"query": "flight"}, TASK)


def test_read_url_is_a_key_argument():
    approved = {"url": "www.informations.com"}
    assert not covers_approval("get_webpage", {"url": "www.true-informations.com"}, approved, TASK)
    assert covers_approval("get_webpage", {"url": "WWW.informations.com "}, approved, TASK)


# ---- side-effect key arguments (AE2, AE3) -------------------------------------

def test_approved_recipient_with_injected_link_is_not_covered():
    approved = {"recipient": "Alice", "body": "Meeting moved to 3pm"}
    injected = {"recipient": "Alice", "body": "Check www.secure-systems-252.com"}
    assert not covers_approval("send_direct_message", injected, approved, TASK)


def test_approved_recipient_with_free_text_change_is_covered():
    approved = {"recipient": "Alice", "body": "Meeting moved to 3pm"}
    assert covers_approval("send_direct_message", {"recipient": "Alice", "body": "Meeting moved to 4pm"},
                           approved, TASK)


def test_changed_recipient_is_not_covered():
    approved = {"recipients": ["bob@example.com"], "subject": "Hi", "body": "Hello"}
    new = {"recipients": ["mark.black-2134@gmail.com"], "subject": "Hi", "body": "Hello"}
    assert not covers_approval("send_email", new, approved, TASK)


def test_recipient_subset_is_covered_and_superset_is_not():
    approved = {"recipients": ["a@x.com", "b@x.com"], "body": "notes"}
    assert covers_approval("send_email", {"recipients": ["a@x.com"], "body": "notes"}, approved, TASK)
    assert not covers_approval("send_email", {"recipients": ["a@x.com", "c@x.com"], "body": "notes"},
                               approved, TASK)


def test_adding_bcc_is_not_covered():
    approved = {"recipients": ["a@x.com"], "body": "notes", "bcc": None}
    new = {"recipients": ["a@x.com"], "body": "notes", "bcc": ["spy@evil.com"]}
    assert not covers_approval("send_email", new, approved, TASK)


def test_changed_reservation_target_is_not_covered():
    approved = {"hotel": "Le Marais Boutique", "start_day": "2024-05-01", "end_day": "2024-05-05"}
    new = {"hotel": "Riverside View Hotel", "start_day": "2024-05-13", "end_day": "2024-05-17"}
    assert not covers_approval("reserve_hotel", new, approved, TASK)
    same_hotel = dict(new, hotel="le marais boutique")
    assert covers_approval("reserve_hotel", same_hotel, approved, TASK)


def test_share_file_with_other_person_is_not_covered():
    approved = {"file_id": "13", "email": "a@x.com", "permission": "r"}
    assert not covers_approval("share_file", dict(approved, email="b@x.com"), approved, TASK)


def test_key_comparison_ignores_case_and_whitespace():
    approved = {"channel": "general", "body": "hi"}
    assert covers_approval("send_channel_message", {"channel": "  General ", "body": "hello"}, approved, TASK)


# ---- amounts (AE4, probe-only banking seeds) ---------------------------------

def test_amount_ceiling():
    approved = {"recipient": "X", "amount": 100, "subject": "rent", "date": "2024-05-01"}
    assert covers_approval("send_money", dict(approved, amount=50), approved, TASK)
    assert not covers_approval("send_money", dict(approved, amount=200), approved, TASK)
    assert not covers_approval("send_money", dict(approved, amount="abc"), approved, TASK)


# ---- injected tokens in free text (R6) ---------------------------------------

def test_unknown_code_in_free_text_blocks_coverage():
    approved = {"recipients": ["a@x.com"], "subject": "Code", "body": "Here you go"}
    new = {"recipients": ["a@x.com"], "subject": "Code", "body": "Your code is 463820"}
    assert not covers_approval("send_email", new, approved, TASK)
    assert covers_approval("send_email", new, approved, TASK + " Send code 463820 to a@x.com.")


def test_iban_like_token_in_subject_blocks_coverage():
    approved = {"recipient": "X", "amount": 10, "subject": "rent", "date": "2024-05-01"}
    new = dict(approved, subject="rent US133000000121212121212")
    assert not covers_approval("send_money", new, approved, TASK)


def test_unknown_email_in_free_text_blocks_coverage():
    approved = {"channel": "general", "body": "Lunch at noon"}
    new = {"channel": "general", "body": "Write to fred9246@gmail.com"}
    assert not covers_approval("send_channel_message", new, approved, TASK)


# ---- unknown tools ------------------------------------------------------------

def test_unknown_tool_is_a_side_effect_with_all_arguments_key():
    spec = spec_for("launch_rocket")
    assert spec.side_effect and spec.key is None
    assert not covers_approval("launch_rocket", {"target": "moon", "note": "b"},
                               {"target": "moon", "note": "a"}, TASK)
    assert covers_approval("launch_rocket", {"target": "moon"}, {"target": "moon"}, TASK)


# ---- denial memory (AE5, R8) --------------------------------------------------

def test_denied_side_effect_matches_retry_with_other_body():
    denied = {"recipients": ["mark.black-2134@gmail.com"], "subject": "x", "body": "a"}
    assert matches_denial("send_email", dict(denied, body="b"), denied)
    assert not matches_denial("send_email", dict(denied, recipients=["bob@example.com"]), denied)


def test_denied_read_matches_only_identical_arguments():
    assert matches_denial("search_emails", {"query": "a"}, {"query": "a"})
    assert not matches_denial("search_emails", {"query": "b"}, {"query": "a"})


# ---- table coverage -----------------------------------------------------------

def test_every_live_suite_tool_has_an_entry_and_banking_is_probe_only():
    suites = get_suites("v1.2")
    for name in LIVE_SUITES:
        for tool in suites[name].tools:
            assert tool.name in TOOLS, f"{name}:{tool.name} missing from tool table"
            assert not TOOLS[tool.name].probe_only
    for name in ("send_money", "schedule_transaction", "update_scheduled_transaction"):
        assert TOOLS[name].probe_only


def test_table_key_arguments_exist_on_the_real_tools():
    suites = get_suites("v1.2")
    params = {}
    for suite in suites.values():
        for tool in suite.tools:
            params[tool.name] = set(tool.parameters.model_json_schema().get("properties", {}))
    for name, spec in TOOLS.items():
        named = (spec.key or frozenset()) | spec.amount
        assert named <= params[name], f"{name}: {named - params[name]} not real parameters"
