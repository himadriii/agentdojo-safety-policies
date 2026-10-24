"""Opt-in authorization rules; no task IDs, attacker targets, or evaluator access."""
import re

from agentdojo.types import get_text_content_as_str
from agent_framework.policies.anomaly_context import call_parts, canonical_url, source_urls, urls

VERSION = 'explicit-intent-v5'
SUPPORTED_VERSIONS = ('explicit-intent-v2','explicit-intent-v3','explicit-intent-v4', VERSION)


def authorization_guard(context, version=VERSION):
    task, call = context['task'], context['proposed_call']
    if version in ('explicit-intent-v4', VERSION) and call.function in ('send_money','schedule_transaction'):
        recipients=re.findall(r'\b(?:to|refund|pay|recipient\s*(?:is|:|=))\s+([A-Z]{2}\d{2}[A-Z0-9]{10,30})\b',task,re.I)
        target=call.args.get('recipient')
        if recipients and isinstance(target,str) and target.replace(' ','').upper() not in {x.upper() for x in recipients}:
            return 'deny','Authorization: payment recipient differs from the explicit user-supplied account'
    booking_words = r'\b(book|booking|reserve|reservation|reservations)\b'
    if call.function == 'reserve_car_rental':
        booking_words = r'\b(book|booking|reserve|reservation|reservations|rent|hire)\b'
    if call.function.startswith('reserve_') and not re.search(booking_words, task, re.I):
        return 'deny', 'Authorization: recommendations do not authorize a reservation'
    if call.function == 'get_webpage':
        target = canonical_url(call.args.get('url'))
        roots, _ = source_urls(context)
        if target and target not in roots:
            for message in context.get('trajectory', []):
                function, _ = call_parts(message.get('tool_call'))
                if (message.get('role') == 'tool' and function == 'get_channels'
                        and not message.get('error') and message.get('content')
                        and target in urls(get_text_content_as_str(message['content']))):
                    return 'deny', 'Authorization: channel listings cannot authorize website visits'
    # Message and invitation calls have no template-specific approval bypass.
    # Nonmatching generic constraints fall through to coverage/model/review.
    return None
