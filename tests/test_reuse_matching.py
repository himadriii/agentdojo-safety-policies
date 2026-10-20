"""Tool table and argument matching for the P6 approval-reuse gate (plan U1)."""
from agentdojo.task_suite.load_suites import get_suites

from agent_framework.policies.approval_reuse.matching import covers_approval, drill_down_covers, matches_denial
from agent_framework.policies.approval_reuse.tool_table import LIVE_SUITES, TOOLS, infer_spec, spec_for

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


# ---- URL normalisation and the read address guard ----------------------------

def test_url_variants_of_one_page_are_the_same_key():
    approved = {"url": "https://www.informations.com/"}
    for variant in ("http://informations.com", "www.informations.com", "HTTPS://Informations.com/"):
        assert covers_approval("get_webpage", {"url": variant}, approved, TASK), variant
    assert not covers_approval("get_webpage", {"url": "https://informations.com/other"}, approved, TASK)
    assert not covers_approval("get_webpage", {"url": "https://www.true-informations.com"}, approved, TASK)


def test_denial_memory_matches_url_variants():
    assert matches_denial("get_webpage", {"url": "http://true-informations.com"},
                          {"url": "https://www.true-informations.com/"})
    assert not matches_denial("get_webpage", {"url": "http://informations.com"},
                              {"url": "https://www.true-informations.com/"})


def test_read_with_a_new_link_or_address_is_not_covered():
    approved = {"query": "flight"}
    assert not covers_approval("search_emails", {"query": "see www.attacker-site.com/login"}, approved, TASK)
    assert not covers_approval("search_emails", {"query": "fred9246@gmail.com"}, approved, TASK)
    assert covers_approval("search_emails", {"query": "fred9246@gmail.com"}, approved,
                           TASK + " Ask fred9246@gmail.com.")


# ---- drill-down across read tools --------------------------------------------

POOL = '{"city": "Paris"} Le Marais Boutique, Good Night'


def drill(args, tool="get_hotels_prices", root="get_all_hotels_in_city", pool=POOL, task=TASK):
    return drill_down_covers(tool, args, root, {"city": "Paris"}, pool, task)


def test_drill_down_needs_every_value_in_the_task_or_pool():
    assert drill({"hotel_names": ["Le Marais Boutique", "Good Night"]})
    assert not drill({"hotel_names": ["Le Marais Boutique", "Invented Palace"]})
    assert drill({"hotel_names": ["alice"]}, task=TASK)          # named in the user's task


def test_drill_down_ignores_empty_values_and_needs_one_real_value():
    assert not drill({})
    assert not drill({"": ""})
    assert not drill({"n": 5})                                    # too short to count as evidence
    assert drill({"hotel_names": ["Good Night"], "n": 5})


def test_drill_down_rejects_new_links_addresses_and_codes():
    pool = POOL + " see www.evil.com or evil@mail.com code 482913"
    assert not drill({"url": "www.evil.com"}, tool="get_webpage", pool=pool)
    assert not drill({"query": "evil@mail.com"}, tool="search_emails", pool=pool)
    assert not drill({"query": "482913"}, tool="search_emails", pool=pool)
    assert drill({"url": "www.evil.com"}, tool="get_webpage", pool=pool, task=TASK + " Open www.evil.com.")


def test_drill_down_never_covers_a_side_effect_or_uses_one_as_root():
    pool = POOL + " bob@example.com"
    assert not drill({"recipients": ["bob@example.com"]}, tool="send_email", pool=pool)
    assert not drill({"hotel_names": ["Good Night"]}, root="reserve_hotel")


# ---- tool inference -------------------------------------------------------------

def test_unlisted_tools_are_classified_by_their_leading_verb():
    assert not spec_for("get_weather_forecast").side_effect
    assert not spec_for("Search_Documents").side_effect
    for name in ("launch_rocket", "get_and_send_report".replace("get", "run"), "weather", ""):
        spec = spec_for(name)
        assert spec.side_effect and spec.key is None, name


def test_inference_agrees_with_the_table_on_every_agentdojo_tool():
    banking_reads = {"get_iban", "get_balance", "get_most_recent_transactions", "get_scheduled_transactions",
                     "read_file", "get_user_info"}
    for suite in get_suites("v1.2").values():
        for tool in suite.tools:
            expected_effect = tool.name not in banking_reads if tool.name not in TOOLS else TOOLS[tool.name].side_effect
            assert infer_spec(tool.name).side_effect == expected_effect, tool.name


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
