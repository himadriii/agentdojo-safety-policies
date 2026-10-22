import httpx
import openai
import pytest

from p2_anomaly.groq_pacing import GroqPacer


def setup():
    clock=[0.0]; waits=[]
    def sleep(seconds):
        waits.append(seconds);clock[0]+=seconds
    return GroqPacer(now=lambda:clock[0],sleep=sleep),clock,waits


def test_small_requests_use_available_allowance_without_minute_delay():
    pacer,clock,waits=setup()
    options={'messages':[],'max_tokens':100}
    pacer.before(options)
    pacer.observe(httpx.Response(200,headers={'x-ratelimit-limit-tokens':'8000',
        'x-ratelimit-remaining-tokens':'7900','x-ratelimit-remaining-requests':'999'}))
    pacer.before(options)
    assert waits==[2.1]
    assert pacer.daily_remaining==999


def test_low_token_allowance_waits_for_refill():
    pacer,clock,waits=setup()
    pacer.observe(httpx.Response(200,headers={'x-ratelimit-limit-tokens':'8000',
        'x-ratelimit-remaining-tokens':'0'}))
    pacer.before({'messages':[],'max_tokens':1000})
    assert 8 < waits[0] < 10
    assert pacer.remaining==pytest.approx(0,abs=0.001)


def test_idle_time_replenishes_allowance_without_sleep():
    pacer,clock,waits=setup()
    pacer.observe(httpx.Response(200,headers={'x-ratelimit-limit-tokens':'8000',
        'x-ratelimit-remaining-tokens':'0'}))
    clock[0]=60
    pacer.before({'messages':[],'max_tokens':4096})
    assert waits==[]


def test_daily_exhaustion_stops_without_retry_or_sleep():
    pacer,clock,waits=setup()
    pacer.observe(httpx.Response(200,headers={'x-ratelimit-remaining-requests':'0'}))
    with pytest.raises(openai.RateLimitError):pacer.before({'messages':[]})
    assert waits==[]


def test_missing_headers_keeps_conservative_fallback():
    pacer,clock,waits=setup()
    pacer.observe(httpx.Response(200))
    assert pacer.limit==8000 and pacer.remaining==8000


def limit_error(message,delay='3'):
    return openai.RateLimitError(message,response=httpx.Response(429,
        request=httpx.Request('POST','https://api.groq.com/openai/v1/chat/completions'),
        headers={'retry-after':delay}),body={'message':message})


def test_minute_limit_retries_same_request_after_server_wait():
    pacer,clock,waits=setup();calls=[]
    error=limit_error('Tokens per minute (TPM): Limit 8000, Used 7000, Requested 2000')
    def request(**kwargs):
        calls.append(kwargs)
        if len(calls)==1:raise error
        return 'ok'
    assert pacer.call(request,messages=[],max_tokens=100)=='ok'
    assert calls[0]==calls[1]
    assert waits==[3.5]


@pytest.mark.parametrize('message',[
    'Tokens per day (TPD) exhausted', 'Requests per day (RPD) exhausted',
    'Rate limit exceeded', 'Tokens per minute (TPM): Limit 8000, Requested 9000'])
def test_daily_unknown_or_oversized_limits_do_not_retry(message):
    pacer,clock,waits=setup();calls=[]
    def request(**kwargs):
        calls.append(kwargs);raise limit_error(message)
    with pytest.raises(openai.RateLimitError):pacer.call(request,messages=[],max_tokens=100)
    assert len(calls)==1 and waits==[]


def test_repeated_minute_limit_has_bounded_attempts():
    pacer,clock,waits=setup();calls=[]
    def request(**kwargs):
        calls.append(kwargs);raise limit_error('Requests per minute (RPM) exhausted')
    with pytest.raises(openai.RateLimitError):pacer.call(request,messages=[],max_tokens=100)
    assert len(calls)==4
