"""Scoped URL-source checks and a versioned read-history feature transform.

These rules use only the original task and visible tool results, never task IDs
or benchmark goals. They are not a complete provenance/authorization system.
"""
import re
import ipaddress
from urllib.parse import urlsplit

from agentdojo.types import get_text_content_as_str
from agent_framework.policies.anomaly_features import FEATURE_NAMES

TRANSFORM = 'neutral-read-history-v1'
URL = re.compile(r'(?:https?://|www\.)[^\s<>"\']+', re.I)


def canonical_url(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        p = urlsplit(text if '://' in text else 'https://' + text)
        if p.scheme.lower() not in ('http', 'https') or not p.hostname or p.username or p.password:
            return None
        host = p.hostname.rstrip('.').encode('idna').decode().lower()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', label) for label in host.split('.')):
                return None
        port = p.port
        # Match the benchmark's scheme-less links to their HTTP(S) spelling.
        default_port = 80 if p.scheme.lower() == 'http' else 443
        return (host, None if port in (None, default_port) else port, p.path or '/', p.query)
    except (ValueError, UnicodeError):
        return None


def urls(text):
    return {u for match in URL.findall(str(text))
            if (u := canonical_url(match.rstrip('.,;!)]}'))) is not None}


def call_parts(call):
    if isinstance(call, dict):
        return call.get('function'), call.get('args') or {}
    return getattr(call, 'function', None), getattr(call, 'args', {}) or {}


def requested_source(task, function, args):
    if function == 'read_channel_messages':
        channels = [v for k, v in args.items() if 'channel' in k and isinstance(v, str)]
        return any(v and re.search(r'(?<!\w)' + re.escape(v) + r'(?!\w)', task, re.I) for v in channels)
    if function == 'read_inbox':
        return bool(re.search(r'\b(inbox|direct messages?)\b', task, re.I))
    return False


def source_urls(context):
    task = context['task']
    roots, pages = urls(task), set()
    for message in context.get('trajectory', []):
        if message.get('role') != 'tool' or message.get('error') or not message.get('content'):
            continue
        function, args = call_parts(message.get('tool_call'))
        found = urls(get_text_content_as_str(message['content']))
        if function == 'get_webpage':
            pages.update(found)
        elif requested_source(task, function, args):
            roots.update(found)
    return roots, pages


def context_guard(context):
    """Return an explicit decision/reason, or None to use anomaly scoring."""
    call = context['proposed_call']
    task = context['task']
    if call.function not in ('get_webpage', 'send_direct_message', 'send_channel_message', 'send_email'):
        return None
    roots, pages = source_urls(context)
    delegates_links = bool(re.search(r'\b(follow|crawl|explore|click)\b.{0,100}\b(links?|hyperlinks?)\b', task, re.I))
    if call.function == 'get_webpage':
        target = canonical_url(call.args.get('url'))
        if target is None:
            return 'deny', 'URL source: invalid or credential-bearing URL'
        if target in roots:
            return None
        if target in pages and not delegates_links:
            return 'deny', 'URL source: a webpage cannot authorize a new browsing action'
        return 'escalate', 'URL source: user-requested origin not established'
    body = call.args.get('body', '')
    if not isinstance(body, str):
        return None
    body_urls = urls(body)
    if body_urls & (pages - roots) and not delegates_links:
        return 'deny', 'URL source: webpage-supplied link is outside the requested source'
    if re.search(r'\b(summarize|summarise|summary|summaries)\b', task, re.I) and body_urls:
        remainder = URL.sub('', body).strip(' \t\n.,;:()[]{}<>')
        if not remainder and not re.search(r'\b(send|share|forward)\b.{0,40}\b(the )?links?\b', task, re.I):
            return 'deny', 'Requested summary cannot be replaced with only a link'
    return None


def transform_features(vector, category, transform):
    result = list(vector)
    if transform not in (None, TRANSFORM):
        raise ValueError('Unknown feature transform')
    if transform == TRANSFORM and category == 'read':
        for name in ('log_previous_calls', 'log_repeated_calls', 'log_errors'):
            result[FEATURE_NAMES.index(name)] = 0.0
    return result
