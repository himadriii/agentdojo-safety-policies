"""Offline tests for provider compatibility shims."""

from types import SimpleNamespace

import httpx2
import openai

from agent_framework.llm_providers import (
    _make_groq_compatible,
    _recover_leaked_channel_tool_call,
)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_calendar_events",
            "parameters": {"type": "object"},
        },
    }
]


def test_recovers_groq_channel_suffix_for_requested_tool():
    body = {
        "message": "Tool call validation failed",
        "type": "invalid_request_error",
        "code": "tool_use_failed",
        "failed_generation": (
            '{"name":"search_calendar_events<|channel|>commentary",'
            '"arguments":{"query":"Networking event","date":"2024-05-26"}}'
        ),
    }

    completion = _recover_leaked_channel_tool_call(body, TOOLS, "test-model")

    call = completion.choices[0].message.tool_calls[0]
    assert call.function.name == "search_calendar_events"
    assert call.function.arguments == (
        '{"query": "Networking event", "date": "2024-05-26"}'
    )


def test_does_not_recover_unrequested_tool():
    body = {
        "code": "tool_use_failed",
        "failed_generation": (
            '{"name":"delete_everything<|channel|>commentary","arguments":{}}'
        ),
    }

    assert _recover_leaked_channel_tool_call(body, TOOLS, "test-model") is None


def test_does_not_hide_unrelated_bad_request():
    body = {
        "code": "invalid_request",
        "failed_generation": (
            '{"name":"search_calendar_events<|channel|>commentary",'
            '"arguments":{}}'
        ),
    }

    assert _recover_leaked_channel_tool_call(body, TOOLS, "test-model") is None


def test_groq_wrapper_recovers_bad_request_without_network():
    body = {
        "code": "tool_use_failed",
        "failed_generation": (
            '{"name":"search_calendar_events<|channel|>commentary",'
            '"arguments":{"query":"Networking event"}}'
        ),
    }

    class FakeCompletions:
        def create(self, **kwargs):
            response = httpx2.Response(
                400,
                request=httpx2.Request("POST", "https://example.invalid"),
            )
            raise openai.BadRequestError("bad tool call", response=response, body=body)

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    _make_groq_compatible(client)

    completion = client.chat.completions.create(
        model="test-model", messages=[], tools=TOOLS
    )

    assert (
        completion.choices[0].message.tool_calls[0].function.name
        == "search_calendar_events"
    )
