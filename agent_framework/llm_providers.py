"""OpenAI-compatible providers that AgentDojo's get_llm does not know about (Groq)."""
import os
import time

import openai

from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.models import MODEL_NAMES
from agentdojo.functions_runtime import EmptyEnv

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_LAST_REQUEST = None


def _pace_request():
    """Space agent/reviewer calls in this serial process; quota errors still stop it."""
    global _LAST_REQUEST
    interval = float(os.getenv('GROQ_REQUEST_INTERVAL_SECONDS', '0'))
    if not 0 <= interval <= 30:
        raise ValueError('request interval must be between 0 and 30 seconds')
    if _LAST_REQUEST is not None:
        delay = interval - (time.monotonic() - _LAST_REQUEST)
        if delay > 0:
            time.sleep(delay)
    _LAST_REQUEST = time.monotonic()


class NoRetryGroqLLM(OpenAILLM):
    """Pinned AgentDojo conversion, without its additional tenacity retries.

    Used for quota-bounded experiments. A provider error ends the current batch.
    """

    def query(self, query, runtime, env=EmptyEnv(), messages=(), extra_args=None):
        from agentdojo.agent_pipeline.llms.openai_llm import (
            _message_to_openai, _function_to_openai, _openai_to_assistant_message,
        )
        kwargs = {
            'model': self.model,
            'messages': [_message_to_openai(m, self.model) for m in messages],
            # Match the pinned AgentDojo OpenAILLM exactly: a zero value is
            # omitted by its `temperature or NOT_GIVEN` conversion.
            'temperature': self.temperature or openai.NOT_GIVEN,
            'max_completion_tokens': int(os.getenv('GROQ_MAX_OUTPUT_TOKENS', '2048')),
        }
        tools = [_function_to_openai(f) for f in runtime.functions.values()]
        if tools:
            kwargs.update(tools=tools, tool_choice='auto')
        response = self.client.chat.completions.create(**kwargs)
        if response.choices[0].finish_reason == 'length':
            raise RuntimeError('agent output token cap reached; incomplete generation')
        output = _openai_to_assistant_message(response.choices[0].message)
        return query, runtime, env, [*messages, output], extra_args or {}


def _flatten(content):
    """['text part', ...] -> 'text'. None -> ''."""
    if content is None:
        return ""
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return content


def _make_groq_compatible(client):
    completions = client.chat.completions
    original = completions.create

    def create(*args, **kwargs):
        fixed = []
        for m in kwargs.get("messages", []):
            m = dict(m)
            if m.get("role") == "developer":
                m["role"] = "system"
            if "content" in m:
                m["content"] = _flatten(m["content"])
            fixed.append(m)
        kwargs["messages"] = fixed
        _pace_request()
        return original(*args, **kwargs)

    completions.create = create
    return client


def make_groq_llm(model: str) -> OpenAILLM:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set (put it in .env in the repo root).")
    client = openai.OpenAI(api_key=key, base_url=GROQ_BASE_URL,
                           max_retries=int(os.getenv('GROQ_MAX_RETRIES', '8')), timeout=45)
    _make_groq_compatible(client)
    # Attacks look the model up by name inside pipeline.name (which has "/" replaced by "_").
    MODEL_NAMES.setdefault(model, "AI assistant")
    MODEL_NAMES.setdefault(model.replace("/", "_"), "AI assistant")
    return (NoRetryGroqLLM if os.getenv('GROQ_STOP_ON_QUOTA') == '1' else OpenAILLM)(client, model)
