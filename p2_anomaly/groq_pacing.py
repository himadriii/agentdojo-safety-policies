"""Shared serial pacing using Groq response headers; never retries a 429."""
import json
from pathlib import Path
import time

import httpx
import openai

VERSION = 'groq-header-pacing-v1'


class GroqPacer:
    def __init__(self, journal=None, *, now=time.monotonic, sleep=time.sleep):
        self.now, self.sleep = now, sleep
        self.limit, self.remaining = 8000, 8000.0
        self.updated = now()
        self.last_request = None
        self.daily_remaining = None
        self.journal = Path(journal) if journal else None

    def log(self, record):
        if self.journal:
            self.journal.parent.mkdir(parents=True,exist_ok=True)
            with self.journal.open('a') as file:
                file.write(json.dumps(record,sort_keys=True)+'\n')

    def observe(self, response):
        headers = response.headers
        try:
            limit = int(headers['x-ratelimit-limit-tokens'])
            remaining = float(headers['x-ratelimit-remaining-tokens'])
            if limit > 0 and 0 <= remaining <= limit:
                self.limit, self.remaining = limit, remaining
                self.updated = self.now()
        except (KeyError,ValueError):
            pass
        try:
            self.daily_remaining = int(headers['x-ratelimit-remaining-requests'])
        except (KeyError,ValueError):
            pass
        self.log({'event':'response','status':response.status_code,
            'token_limit':self.limit,'tokens_remaining':self.remaining,
            'daily_requests_remaining':self.daily_remaining})

    def before(self, options):
        if self.daily_remaining == 0:
            raise openai.RateLimitError('Observed Groq daily request allowance exhausted; stop',
                response=httpx.Response(429,request=httpx.Request('POST',
                    'https://api.groq.com/openai/v1/chat/completions')),body=None)
        # Estimate conservatively; never shorten the real prompt or output cap.
        payload = {key:options[key] for key in ('messages','tools','response_format') if key in options}
        estimated_prompt = len(json.dumps(payload,ensure_ascii=False).encode()) / 3 + 128
        needed = min(self.limit,estimated_prompt + options.get('max_tokens',4096))
        current = self.now()
        available = min(self.limit,self.remaining + max(0,current-self.updated)*self.limit/60)
        token_wait = max(0,needed-available)*60/self.limit
        # Groq publishes 30 requests/minute for free GPT-OSS-20B. The response
        # "requests" headers describe the DAILY budget, not this minute limit.
        request_wait = 0 if self.last_request is None else max(0,2.1-(current-self.last_request))
        delay = max(token_wait,request_wait)
        if delay:
            print(f'Groq allowance pacing: waiting {delay:.1f}s',flush=True)
            self.sleep(delay)
        current = self.now()
        self.remaining = max(0,min(self.limit,self.remaining + max(0,current-self.updated)*self.limit/60)-needed)
        self.updated = self.last_request = current
        self.log({'event':'request','estimated_reserved_tokens':round(needed),
                  'wait_seconds':round(delay,3)})
