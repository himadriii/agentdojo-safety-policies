from agentdojo.types import text_content_block_from_string as T
from p2_anomaly.completion_check import CompletionCheckMixin,INSTRUCTION


class FakeAgent:
    def __init__(self,responses):self.responses=iter(responses);self.calls=0
    def query(self,q,r,e,m,a):
        self.calls+=1
        return q,r,e,[*m,next(self.responses)],a


class Checked(CompletionCheckMixin,FakeAgent):pass


def answer(text):return {'role':'assistant','content':[T(text)],'tool_calls':[]}


def test_one_check_corrects_draft_without_mutating_input():
    agent=Checked([answer('Draft'),answer('Corrected')])
    messages=[{'role':'user','content':[T('Request')]}]
    result=agent.query('Request',None,messages=messages)
    assert agent.calls==2
    assert result[3][-1]==answer('Corrected')
    assert result[3][-2]=={'role':'system','content':[T(INSTRUCTION)]}
    assert len(messages)==1


def test_tool_proposals_are_returned_to_executor_without_extra_check():
    proposed={'role':'assistant','content':[],'tool_calls':[{'function':'lookup'}]}
    agent=Checked([proposed])
    assert agent.query('request',None)[3][-1]==proposed
    assert agent.calls==1


def test_new_lookup_after_check_does_not_cause_another_check():
    proposed={'role':'assistant','content':[],'tool_calls':[{'function':'lookup'}]}
    agent=Checked([answer('Missing facts'),proposed,answer('Finished')])
    result=agent.query('request',None)
    assert result[3][-1]==proposed
    from agentdojo.functions_runtime import FunctionCall
    history=[*result[3],{'role':'tool','content':[T('facts')],
                        'tool_call':FunctionCall(function='get_balance',args={})}]
    final=agent.query('request',None,messages=history)
    assert agent.calls==3
    assert final[3][-1]==answer('Finished')


def test_successful_write_prevents_completion_pass_that_could_repeat_action():
    from agentdojo.functions_runtime import FunctionCall
    agent=Checked([answer('Sent')])
    history=[{'role':'tool','content':[T('Success')],'error':None,
              'tool_call':FunctionCall(function='send_money',args={'amount':10})}]
    assert agent.query('request',None,messages=history)[3][-1]==answer('Sent')
    assert agent.calls==1
