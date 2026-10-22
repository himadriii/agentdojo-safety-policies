"""OpenAI-compatible providers that AgentDojo's get_llm does not know about (Groq)."""
import json
import logging
import os
import re
import time
import uuid

import openai
from openai.types.chat import ChatCompletion

from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.models import MODEL_NAMES
from agentdojo.functions_runtime import EmptyEnv
from agentdojo.logging import Logger
from agentdojo.types import ChatAssistantMessage, text_content_block_from_string

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
log = logging.getLogger(__name__)

CHANNEL_SUFFIX = re.compile(
    r"^(?P<name>.+)<\|channel\|>(?:analysis|commentary|final)$"
)

class RobustOpenAILLM(OpenAILLM):
    """Resamples Groq 'tool_use_failed' (malformed tool call) instead of aborting the run."""
    max_format_retries = 3

    def query(self, query, runtime, env=EmptyEnv(), messages=(), extra_args={}):
        for attempt in range(self.max_format_retries + 1):
            try:
                return super().query(query, runtime, env, messages, extra_args)
            except openai.BadRequestError as e:
                if "tool_use_failed" not in str(e):
                    raise
                trace = Logger.get()
                if hasattr(trace, "set_contextarg"):
                    n = trace.context.get("llm_tool_format_errors", 0) + 1
                    trace.set_contextarg("llm_tool_format_errors", n)
                if attempt == self.max_format_retries:
                    msg = ChatAssistantMessage(
                        role="assistant",
                        content=[text_content_block_from_string("The model failed to produce a valid tool call.")],
                        tool_calls=None)
                    return query, runtime, env, [*messages, msg], extra_args

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
        try:
            return original(*args, **kwargs)
        except openai.BadRequestError as error:
            recovered = _recover_leaked_channel_tool_call(
                getattr(error, "body", None),
                kwargs.get("tools", []),
                kwargs.get("model", "unknown"),
            )
            if recovered is None:
                raise
            log.warning(
                "Recovered Groq tool_use_failed response after removing a leaked "
                "channel suffix from tool=%s",
                recovered.choices[0].message.tool_calls[0].function.name,
            )
            return recovered

    completions.create = create
    return client


def _recover_leaked_channel_tool_call(body, tools, model):
    """Recover only Groq's known ``<|channel|>...`` tool-name corruption.

    The repaired name must exactly match a tool supplied in this request. All
    other 400 responses are re-raised by the caller.
    """

    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    if not isinstance(error, dict) or error.get("code") != "tool_use_failed":
        return None

    failed = error.get("failed_generation")
    try:
        generated = json.loads(failed) if isinstance(failed, str) else failed
    except json.JSONDecodeError:
        return None
    if not isinstance(generated, dict):
        return None

    generated_name = generated.get("name")
    match = CHANNEL_SUFFIX.fullmatch(generated_name or "")
    if match is None:
        return None
    repaired_name = match.group("name")

    allowed_names = {
        tool.get("function", {}).get("name")
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
    }
    if repaired_name not in allowed_names:
        return None

    arguments = generated.get("arguments", {})
    if not isinstance(arguments, (dict, list)):
        return None

    return ChatCompletion.model_validate(
        {
            "id": f"groq-recovered-{uuid.uuid4().hex}",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "index": 0,
                    "logprobs": None,
                    "message": {
                        "content": None,
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": f"call_recovered_{uuid.uuid4().hex}",
                                "type": "function",
                                "function": {
                                    "name": repaired_name,
                                    "arguments": json.dumps(arguments),
                                },
                            }
                        ],
                    },
                }
            ],
            "created": int(time.time()),
            "model": model,
            "object": "chat.completion",
        }
    )


def make_groq_llm(model: str) -> OpenAILLM:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set (put it in .env in the repo root).")
    max_retries = int(os.getenv("GROQ_MAX_RETRIES", "8"))
    client = openai.OpenAI(
        api_key=key, base_url=GROQ_BASE_URL, max_retries=max_retries
    )
    _make_groq_compatible(client)
    # Attacks look the model up by name inside pipeline.name (which has "/" replaced by "_").
    MODEL_NAMES.setdefault(model, "AI assistant")
    MODEL_NAMES.setdefault(model.replace("/", "_"), "AI assistant")
    return RobustOpenAILLM(client, model)
