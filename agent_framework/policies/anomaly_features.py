"""Visible-context features shared by normal-only training and runtime scoring."""
import math
import re

from agentdojo.types import get_text_content_as_str

SCHEMA_VERSION = 2
# Populated from the pinned workspace suite at training time, not name guesses.
EFFECTS = {
    'send_email': 'external', 'share_file': 'external',
    'add_calendar_event_participants': 'external',
    'delete_email': 'destructive', 'delete_file': 'destructive',
    'cancel_calendar_event': 'destructive', 'create_calendar_event': 'write',
    'reschedule_calendar_event': 'write', 'create_file': 'write',
    'append_to_file': 'write',
}
FEATURE_NAMES = (
    'read', 'external', 'destructive', 'write', 'log_args', 'n_keys',
    'n_emails', 'n_urls', 'task_overlap', 'history_overlap',
    'emails_in_task', 'emails_in_history', 'action_in_task',
    'log_previous_calls', 'log_repeated_calls', 'log_errors',
)
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
ACTION_WORDS = {
    'send_email': ('send', 'forward', 'reply', 'notify'),
    'share_file': ('share', 'grant'),
    'append_to_file': ('append', 'add', 'update', 'include', 'extend'),
    'create_file': ('create', 'write', 'draft', 'make', 'prepare'),
    'create_calendar_event': ('create', 'schedule', 'book', 'add', 'organize'),
    'reschedule_calendar_event': ('reschedule', 'move', 'postpone', 'shift'),
    'add_calendar_event_participants': ('add', 'invite', 'include'),
    'cancel_calendar_event': ('cancel', 'remove'),
    'delete_email': ('delete', 'remove', 'erase'),
    'delete_file': ('delete', 'remove', 'erase'),
}


def _strings(value):
    if isinstance(value, dict):
        return ' '.join(_strings(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return ' '.join(_strings(v) for v in value)
    return '' if value is None else str(value)


def _tokens(text):
    return set(re.findall(r'[a-z0-9]+', text.lower()))


def extract_features(context, tool_table):
    call = context['proposed_call']
    if call.function not in tool_table:
        raise ValueError('unsupported tool')
    if not isinstance(call.args, dict):
        raise ValueError('invalid arguments')
    task = context['task'].lower()
    messages = context['trajectory']
    outputs = [m for m in messages if m['role'] == 'tool']
    history = ' '.join(get_text_content_as_str(m['content'])
                       for m in outputs if m.get('content')).lower()
    args = _strings(call.args).lower()
    tokens = _tokens(args)
    emails = set(EMAIL.findall(args))
    fraction = lambda a, b: len(a & b) / len(a) if a else 0.0
    completed = [m.get('tool_call') for m in outputs]
    def function(c):
        return c.get('function') if isinstance(c, dict) else getattr(c, 'function', None)
    category = tool_table[call.function]
    values = [float(category == c) for c in ('read', 'external', 'destructive', 'write')]
    values += [math.log1p(len(args)), float(len(call.args)), float(len(emails)),
               float(len(re.findall(r'https?://', args))),
               fraction(tokens, _tokens(task)), fraction(tokens, _tokens(history)),
               fraction(emails, set(EMAIL.findall(task))),
               fraction(emails, set(EMAIL.findall(history))),
               float(any(word in _tokens(task) for word in
                         ACTION_WORDS.get(call.function, (call.function.split('_')[0],)))),
               math.log1p(len(outputs)),
               math.log1p(sum(function(c) == call.function for c in completed)),
               math.log1p(sum(bool(m.get('error')) for m in outputs))]
    if not all(math.isfinite(v) for v in values):
        raise ValueError('nonfinite features')
    return values
