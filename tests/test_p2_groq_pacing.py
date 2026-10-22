from unittest.mock import patch

from p2_anomaly.optimize import error_status
from p2_anomaly.hosted20 import HostedStop
import openai
import httpx
from openai.resources.chat.completions import Completions


def test_groq_agent_and_reviewer_share_pacing_and_output_cap():
    with patch.object(Completions, 'create', return_value='response') as request, \
         patch('p2_anomaly.optimize.time.monotonic', side_effect=[100, 110, 165]), \
         patch('p2_anomaly.optimize.time.sleep') as sleep:
        with error_status(groq=True):
            assert Completions.create(object(), model='openai/gpt-oss-20b') == 'response'
            Completions.create(object(), model='openai/gpt-oss-20b', max_tokens=1024)
        sleep.assert_called_once_with(55)
        assert request.call_args_list[0].kwargs['max_tokens'] == 4096
        assert request.call_args_list[0].kwargs['temperature'] == 0
        assert request.call_args_list[1].kwargs['max_tokens'] == 1024


def test_quota_error_is_recorded_without_retry():
    error = openai.RateLimitError('quota', response=httpx.Response(429,
        request=httpx.Request('POST', 'https://api.groq.com/openai/v1/chat/completions')), body=None)
    with patch.object(Completions, 'create', side_effect=error) as request:
        with error_status(groq=True) as state:
            try:
                Completions.create(object(), model='openai/gpt-oss-20b')
            except openai.RateLimitError:
                pass
            else:
                raise AssertionError('Quota errors must stop the run')
        assert state['status'] == 429
        assert request.call_count == 1


def test_success_clears_recovered_http_error_status():
    import pytest
    error=openai.BadRequestError('format',response=httpx.Response(400,
        request=httpx.Request('POST','https://api.groq.com/openai/v1/chat/completions')),body={'code':'tool_use_failed'})
    with patch.object(Completions,'create',side_effect=[error,'ok']):
        with error_status() as state:
            with pytest.raises(openai.BadRequestError):Completions.create(object())
            assert state['status']==400
            assert Completions.create(object())=='ok'
            assert 'status' not in state
