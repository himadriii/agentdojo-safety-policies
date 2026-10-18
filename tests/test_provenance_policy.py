"""Tests for the provenance policy."""

import json
from types import SimpleNamespace

from agentdojo.functions_runtime import FunctionCall
from agentdojo.types import text_content_block_from_string

from agent_framework.policies.provenance_gate import ProvenancePolicy
from agent_framework.policies.provenance_gate.extractor import (
    enrich_with_llm,
    extract_direct,
    flatten_arguments,
)
from agent_framework.policies.provenance_gate.policy import decide
from agent_framework.registry import POLICIES


class FakeCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        message = SimpleNamespace(content=json.dumps(self.payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_policy_is_registered():
    assert POLICIES["provenance"] is ProvenancePolicy


def test_direct_extraction_finds_literal_authorization_and_values():
    evidence = extract_direct(_direct_context())

    assert evidence["tool_name"] == "search_emails"
    assert evidence["arguments"] == {"query": "invoice 42"}
    assert [edge["relation"] for edge in evidence["edges"]] == [
        "authorizes",
        "provides_value",
    ]


def test_task_implied_authorization_excludes_current_tool_request():
    evidence = extract_direct(_implied_context())
    client, _ = _fake_client(
        {
            "edges": [
                {
                    "relation": "authorizes",
                    "source_id": "trajectory:1",
                    "supporting_span": "on May 26th",
                    "confidence": 0.95,
                    "action_scope": {
                        "tool_name": "get_current_day",
                        "arguments": {},
                    },
                    "argument_path": None,
                    "transformation": None,
                }
            ]
        }
    )

    enriched = enrich_with_llm(evidence, client)

    assert [source["id"] for source in evidence["sources"]] == [
        "trajectory:0",
        "trajectory:1",
    ]
    assert enriched["edges"][-1]["verified"] is True
    assert decide(enriched) == (
        "approve",
        "complete authorization and provenance",
        0.95,
    )


def test_policy_approves_complete_direct_evidence():
    decision, state, info = ProvenancePolicy(lambda evidence: evidence).evaluate(
        _direct_context(), {}
    )

    assert decision == "approve"
    assert state == {}
    assert info["scores"] == {"provenance_confidence": 1.0}
    assert info["evidence"]["decision_rule"] == {
        "decision": "approve",
        "reason": "complete authorization and provenance",
        "confidence": 1.0,
    }
    assert info["evidence"]["authorization_edges"][0]["source_role"] == "user"
    argument = info["evidence"]["argument_provenance"][0]
    assert argument["path"] == "/query"
    assert argument["value"] == "invoice 42"
    assert argument["provenance_edges"][0]["supporting_span"] == "invoice 42"


def test_policy_escalates_missing_authorization():
    context = _direct_context()
    context["task"] = "Inspect the mailbox"
    context["trajectory"][0]["content"] = [
        text_content_block_from_string("Inspect the mailbox")
    ]

    decision, _, info = ProvenancePolicy(lambda evidence: evidence).evaluate(context, {})

    assert decision == "escalate"
    assert info["reason"] == "missing verified action authorization"


def test_llm_edges_are_validated_and_can_support_approval():
    evidence = extract_direct(_semantic_context())
    client, completions = _fake_client(
        {
            "edges": [
                {
                    "relation": "authorizes",
                    "source_id": "trajectory:0",
                    "supporting_span": (
                        "Please send email to the address from the contact lookup"
                    ),
                    "confidence": 1.0,
                    "action_scope": {
                        "tool_name": "send_email",
                        "arguments": {"recipient": "lee@example.com"},
                    },
                    "argument_path": None,
                    "transformation": None,
                },
                {
                    "relation": "derived_from",
                    "source_id": "trajectory:2",
                    "supporting_span": "lee@example.com",
                    "confidence": 1.0,
                    "action_scope": None,
                    "argument_path": "/recipient",
                    "transformation": "copied the contact email address",
                },
            ]
        }
    )

    enriched = enrich_with_llm(evidence, client)

    assert enriched["edges"][-2]["verified"] is True
    assert decide(enriched)[0] == "approve"
    assert completions.request["temperature"] == 0


def test_malformed_edge_does_not_discard_valid_authorization():
    evidence = extract_direct(_implied_context())
    client, _ = _fake_client(
        {
            "edges": [
                {
                    "relation": "derived_from",
                    "source_id": "trajectory:1",
                    "supporting_span": "May 26th",
                    "confidence": 0.8,
                    "action_scope": None,
                    "argument_path": None,
                    "transformation": None,
                },
                {
                    "relation": "authorizes",
                    "source_id": "trajectory:1",
                    "supporting_span": "on May 26th",
                    "confidence": 0.95,
                    "action_scope": {
                        "tool_name": "get_current_day",
                        "arguments": {},
                    },
                    "argument_path": None,
                    "transformation": None,
                },
            ]
        }
    )

    enriched = enrich_with_llm(evidence, client)

    assert decide(enriched)[0] == "approve"
    assert enriched["edge_validation_errors"] == [
        {
            "edge_index": 0,
            "edge": {
                "relation": "derived_from",
                "source_id": "trajectory:1",
                "supporting_span": "May 26th",
                "confidence": 0.8,
                "action_scope": None,
                "argument_path": None,
                "transformation": None,
            },
            "error_type": "ValueError",
            "error": "derived-value edge is malformed",
        }
    ]


def test_authorization_ignores_irrelevant_optional_fields():
    evidence = extract_direct(_implied_context())
    client, _ = _fake_client(
        {
            "edges": [
                {
                    "relation": "authorizes",
                    "source_id": "trajectory:1",
                    "supporting_span": "on May 26th",
                    "confidence": 0.95,
                    "action_scope": {
                        "tool_name": "get_current_day",
                        "arguments": {},
                    },
                    "argument_path": "/invented",
                    "transformation": "unneeded explanation",
                }
            ]
        }
    )

    enriched = enrich_with_llm(evidence, client)

    assert decide(enriched)[0] == "approve"
    assert enriched["edges"][-1]["argument_path"] is None
    assert enriched["edges"][-1]["transformation"] is None


def test_named_confidence_is_normalized():
    evidence = extract_direct(_implied_context())
    client, _ = _fake_client(
        {
            "edges": [
                {
                    "relation": "authorizes",
                    "source_id": "trajectory:1",
                    "supporting_span": "on May 26th",
                    "confidence": "high",
                    "action_scope": {
                        "tool_name": "get_current_day",
                        "arguments": {},
                    },
                    "argument_path": None,
                    "transformation": None,
                }
            ]
        }
    )

    enriched = enrich_with_llm(evidence, client)

    assert decide(enriched) == (
        "approve",
        "complete authorization and provenance",
        0.9,
    )


def test_null_optional_arguments_do_not_require_provenance():
    assert flatten_arguments(
        {"date": None, "query": "Networking event", "sender": None}
    ) == {"/query": "Networking event"}


def test_authorization_span_allows_quote_and_punctuation_differences():
    evidence = extract_direct(_implied_context())
    client, _ = _fake_client(
        {
            "edges": [
                {
                    "relation": "authorizes",
                    "source_id": "trajectory:1",
                    "supporting_span": "Networking event on May 26th",
                    "confidence": 0.95,
                    "action_scope": {
                        "tool_name": "get_current_day",
                        "arguments": {},
                    },
                    "argument_path": None,
                    "transformation": None,
                }
            ]
        }
    )

    enriched = enrich_with_llm(evidence, client)

    assert decide(enriched)[0] == "approve"
    assert enriched["edge_validation_errors"] == []


def test_policy_denies_scoped_untrusted_influence():
    evidence = extract_direct(_semantic_context())
    evidence["edges"].append(
        {
            "relation": "untrusted_influence",
            "source_id": "trajectory:2",
            "supporting_span": "lee@example.com",
            "confidence": 1.0,
            "action_scope": {
                "tool_name": "send_email",
                "arguments": {"recipient": "lee@example.com"},
            },
            "argument_path": None,
            "transformation": None,
            "verified": False,
        }
    )

    assert decide(evidence) == ("deny", "untrusted_influence detected", 1.0)


def _fake_client(payload):
    completions = FakeCompletions(payload)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def _direct_context():
    text = "Please search emails for invoice 42"
    return {
        "task": text,
        "proposed_call": FunctionCall(
            function="search_emails", args={"query": "invoice 42"}
        ),
        "environment": None,
        "trajectory": [
            {"role": "user", "content": [text_content_block_from_string(text)]}
        ],
        "remaining_budget": 1,
        "metadata": {},
    }


def _semantic_context():
    task = "Please send email to the address from the contact lookup"
    return {
        "task": task,
        "proposed_call": FunctionCall(
            function="send_email", args={"recipient": "lee@example.com"}
        ),
        "environment": None,
        "trajectory": [
            {"role": "user", "content": [text_content_block_from_string(task)]},
            {
                "role": "assistant",
                "content": [text_content_block_from_string("Looking up the contact")],
                "tool_calls": None,
            },
            {
                "role": "tool",
                "content": [text_content_block_from_string("Contact: lee@example.com")],
                "tool_call": FunctionCall(function="lookup_contact", args={}),
                "tool_call_id": "lookup-1",
                "error": None,
            },
        ],
        "remaining_budget": 1,
        "metadata": {},
    }


def _implied_context():
    task = "Who else is invited to the Networking event on May 26th?"
    call = FunctionCall(function="get_current_day", args={})
    return {
        "task": task,
        "proposed_call": call,
        "environment": None,
        "trajectory": [
            {
                "role": "system",
                "content": [
                    text_content_block_from_string(
                        "Do not assume the current year; use the provided tools."
                    )
                ],
            },
            {"role": "user", "content": [text_content_block_from_string(task)]},
            {"role": "assistant", "content": None, "tool_calls": [call]},
        ],
        "remaining_budget": 1,
        "metadata": {},
    }
