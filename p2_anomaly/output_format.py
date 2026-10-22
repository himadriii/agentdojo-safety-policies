"""Cosmetic final-answer typography, independent of tasks and evaluators."""
import copy
import re

VERSION = 'plain-typography-v1'
PROTECTED = re.compile(r'(```[\s\S]*?```|`[^`\n]*`|https?://\S+|www\.\S+)')
TRANSLATION = str.maketrans({'\u202f':' ','\u00a0':' ','\u2011':'-'})


def plain_typography(text):
    parts=PROTECTED.split(text)
    return ''.join(part if i%2 else part.translate(TRANSLATION) for i,part in enumerate(parts))


def format_final(messages):
    if not messages or messages[-1]['role']!='assistant' or messages[-1].get('tool_calls'):
        return messages
    result=list(messages)
    result[-1]=copy.deepcopy(messages[-1])
    for block in result[-1].get('content') or []:
        if block.get('type')=='text' and isinstance(block.get('content'),str):
            block['content']=plain_typography(block['content'])
    return result
