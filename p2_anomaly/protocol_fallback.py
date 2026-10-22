"""Bounded same-model recovery for a specific LM Studio output-parser defect."""
from contextlib import contextmanager
import json
import os
from pathlib import Path

import openai
from openai.resources.chat.completions import Completions
from agent_framework.inference import make_inference_client
from p2_anomaly.experiments import save
from p2_anomaly.hosted20 import HostedStop, MODEL

VERSION='groq20-parser-recovery-v1'


@contextmanager
def protocol_fallback(outdir, limit=10, enabled=False):
    if not enabled:
        yield
        return
    if not 1<=limit<=10:
        raise ValueError('Fallback limit must be between 1 and 10')
    path=Path(outdir)/'protocol-fallback.json'
    ledger=json.loads(path.read_text()) if path.exists() else {'version':VERSION,'model':MODEL,'attempts':[]}
    if ledger['version']!=VERSION or ledger['model']!=MODEL:
        raise ValueError('Fallback ledger identity changed')
    original=Completions.create
    primary=os.environ['LMSTUDIO_BASE_URL'].rstrip('/')
    os.environ['GROQ_MAX_RETRIES']='0'
    def create(self,*args,**kwargs):
        try:
            return original(self,*args,**kwargs)
        except openai.BadRequestError as exc:
            if (str(self._client.base_url).rstrip('/')!=primary
                    or kwargs.get('model')!=MODEL
                    or 'expected peg-native format' not in str(exc.body)):
                raise
            if len(ledger['attempts'])>=limit:
                raise HostedStop('PROTOCOL_FALLBACK_BUDGET_EXHAUSTED') from None
            event={'primary_http_status':400,'provider':'groq','model':MODEL,'status':'started'}
            ledger['attempts'].append(event);save(path,ledger)
            print(f'Native parser failure: same-model Groq recovery {len(ledger["attempts"])}/{limit}.',flush=True)
            try:
                # A failed generation executes no tools. Only the proposed call
                # is recovered; the normal executor still applies policy/budget.
                response=make_inference_client('groq').chat.completions.create(*args,**kwargs)
            except openai.APIError as secondary:
                event.update(status='stopped',http_status=getattr(secondary,'status_code',None))
                save(path,ledger)
                raise
            event.update(status='completed',usage=response.usage.model_dump() if response.usage else None)
            save(path,ledger)
            return response
    Completions.create=create
    try:
        yield
    finally:
        Completions.create=original
