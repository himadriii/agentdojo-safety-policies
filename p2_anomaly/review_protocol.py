"""Opt-in Groq reviewer response protocol; decision instructions stay unchanged."""
from contextlib import contextmanager

VERSION='review-json-v1'
MAX_TOKENS=2048
RESPONSE_FORMAT={'type':'json_schema','json_schema':{'name':'approval_decision','strict':True,
    'schema':{'type':'object','properties':{'decision':{'type':'string','enum':['approve','deny']},
    'reason':{'type':'string'}},'required':['decision','reason'],'additionalProperties':False}}}


@contextmanager
def reviewer_json_variant(enabled):
    if not enabled:
        yield
        return
    from p2_anomaly import hosted20
    from agent_framework import runner
    original_reviewer=hosted20.HostedReviewer
    original_builder=runner.build_pipeline
    class JsonReviewer(original_reviewer):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if str(self.client.base_url).rstrip('/')!='https://api.groq.com/openai/v1':
                raise ValueError('Strict review protocol requires the Groq endpoint')
            original_create=self.client.chat.completions.create
            def create(*args,**kwargs):
                kwargs.update(max_tokens=MAX_TOKENS,reasoning_effort='low',response_format=RESPONSE_FORMAT)
                response=original_create(*args,**kwargs)
                self.last_response_metadata={'finish_reason':response.choices[0].finish_reason if response.choices else 'no_choices'}
                return response
            self.client.chat.completions.create=create
    def build(*args,**kwargs):
        pipeline=original_builder(*args,**kwargs)
        pipeline.name+='-'+VERSION
        pipeline.inference_config['reviewer'].update(response_protocol=VERSION,max_tokens=MAX_TOKENS,reasoning_effort='low')
        return pipeline
    hosted20.HostedReviewer=JsonReviewer
    runner.build_pipeline=build
    try:
        yield
    finally:
        hosted20.HostedReviewer=original_reviewer
        runner.build_pipeline=original_builder
