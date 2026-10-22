"""P2 free-tier execution: shared prompts and requests, immediate quota stop."""
from contextlib import contextmanager

import openai
from agentdojo.agent_pipeline.llms.openai_llm import (
    chat_completion_request, _message_to_openai, _function_to_openai,
    _openai_to_assistant_message,
)
from agentdojo.functions_runtime import EmptyEnv
from agentdojo.models import MODEL_NAMES
from agentdojo.logging import Logger
from agentdojo.types import ChatAssistantMessage, text_content_block_from_string

from agent_framework.inference import make_inference_client
from agent_framework.llm_providers import RobustOpenAILLM
from agent_framework.llm_reviewer import LLMReviewer
from p2_anomaly.historical_providers import _pace_request


class QuotaStop(RuntimeError):
    status_code = 429
    code = 'p2_quota_stop'


def paced(client):
    original = client.chat.completions.create
    def create(*args, **kwargs):
        _pace_request()
        return original(*args, **kwargs)
    client.chat.completions.create = create
    return client


class QuotaBoundGroqLLM(RobustOpenAILLM):
    def query(self, query, runtime, env=EmptyEnv(), messages=(), extra_args=None):
        # Same pinned request conversion as OpenAILLM; bypass its tenacity retry.
        for attempt in range(self.max_format_retries + 1):
            try:
                response = chat_completion_request.__wrapped__(
                    self.client, self.model,
                    [_message_to_openai(m, self.model) for m in messages],
                    [_function_to_openai(f) for f in runtime.functions.values()],
                    self.reasoning_effort, self.temperature,
                )
                return query, runtime, env, [*messages, _openai_to_assistant_message(response.choices[0].message)], extra_args or {}
            except openai.RateLimitError:
                raise QuotaStop('Agent quota reached; stop until provider reset') from None
            except openai.BadRequestError as exc:
                if 'tool_use_failed' not in str(exc):
                    raise
                trace = Logger.get()
                if hasattr(trace, 'set_contextarg'):
                    trace.set_contextarg('llm_tool_format_errors', trace.context.get('llm_tool_format_errors', 0) + 1)
                if attempt == self.max_format_retries:
                    message = ChatAssistantMessage(role='assistant', content=[text_content_block_from_string('The model failed to produce a valid tool call.')], tool_calls=None)
                    return query, runtime, env, [*messages, message], extra_args or {}


class QuotaBoundReviewer(LLMReviewer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        paced(self.client)

    def review(self, context):
        result = super().review(context)
        if self.last_reason == 'REVIEWER_ERROR: RateLimitError':
            raise QuotaStop('Reviewer quota reached; stop until provider reset')
        return result


def make_bounded_agent(model):
    MODEL_NAMES.setdefault(model, 'AI assistant')
    MODEL_NAMES.setdefault(model.replace('/', '_'), 'AI assistant')
    return QuotaBoundGroqLLM(paced(make_inference_client('groq')), model)


@contextmanager
def quota_safe_shared_runner():
    # Scoped factories in this serial P2 process; protected shared files stay intact.
    from agent_framework import runner
    original_agent, original_reviewer = runner.make_groq_llm, runner.REVIEWERS['llm']
    runner.make_groq_llm, runner.REVIEWERS['llm'] = make_bounded_agent, QuotaBoundReviewer
    try:
        yield
    finally:
        runner.make_groq_llm, runner.REVIEWERS['llm'] = original_agent, original_reviewer
