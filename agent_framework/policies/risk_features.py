"""Feature extraction for the P3 supervised risk policy.

Everything here is computed from the policy context only (task text, proposed call,
visible trajectory, read-only environment). No benchmark labels, injection task ids,
goals or attack names are used. The same function is used at training and inference time.
"""
import math
import re

from agentdojo.types import get_text_content_as_str

# ---- tool taxonomy ----------------------------------------------------------

# Workspace tools classified explicitly; other suites fall back to name prefixes.
_TOOL_CLASS = {
    "send_email": "external",
    "share_file": "external",
    "add_calendar_event_participants": "external",
    "create_calendar_event": "write",
    "reschedule_calendar_event": "write",
    "create_file": "write",
    "append_to_file": "write",
    "delete_email": "destructive",
    "delete_file": "destructive",
    "cancel_calendar_event": "destructive",
}
_PREFIX_CLASS = (
    (("get_", "search_", "list_", "read_", "find_", "check_", "view_", "show_", "fetch_"), "read"),
    (("send_", "post_", "share_", "forward_", "invite_", "reply_", "add_user", "message_"), "external"),
    (("transfer", "pay", "schedule_transaction", "update_scheduled", "book", "reserve"), "financial"),
    (("delete_", "remove_", "cancel_", "clear_"), "destructive"),
)
CLASSES = ("read", "external", "financial", "destructive", "write")


def tool_class(name):
    if name in _TOOL_CLASS:
        return _TOOL_CLASS[name]
    for prefixes, cls in _PREFIX_CLASS:
        if name.startswith(prefixes):
            return cls
    return "write"


# Words in the user's task that make an action plausible, per leading verb of the tool name.
_ACTION_WORDS = {
    "send": ("send", "email", "mail", "write", "reply", "forward", "message", "tell", "let"),
    "delete": ("delete", "remove", "clear", "erase", "trash"),
    "cancel": ("cancel", "remove", "delete"),
    "share": ("share", "send", "give", "grant", "access"),
    "create": ("create", "schedule", "add", "set", "make", "new", "book", "write", "organize"),
    "append": ("append", "add", "write", "update", "include"),
    "reschedule": ("reschedule", "move", "change", "postpone", "shift"),
    "add": ("add", "invite", "include", "participant"),
    "transfer": ("transfer", "send", "pay", "move"),
    "pay": ("pay", "send"),
    "update": ("update", "change", "modify", "set"),
    "book": ("book", "reserve"),
    "reserve": ("book", "reserve"),
}
_OBJECT_WORDS = {
    "email": ("email", "mail", "message", "reply"),
    "file": ("file", "document", "doc", "drive", "spreadsheet", "list", "note"),
    "calendar": ("calendar", "event", "meeting", "appointment", "schedule", "lunch", "call"),
    "event": ("event", "meeting", "calendar", "appointment", "lunch", "call", "schedule"),
    "participants": ("invite", "participant", "attendee", "add"),
    "transaction": ("transaction", "payment", "pay", "transfer", "send", "money"),
}

# ---- regexes ----------------------------------------------------------------

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TOKEN_RE = re.compile(r"[a-z0-9]{4,}")
_URL_RE = re.compile(r"https?://|www\.", re.I)
_SENSITIVE_RE = re.compile(
    r"password|passcode|\bcode\b|verif|security|credential|\biban\b|account|secret|token|\bssn\b|bank|"
    r"private|confidential|salary|invoice", re.I)
_STOP = frozenset("""
this that with from have will your what when where which their there them they then than been were
would could should about into also just more some such only other over very much like make made
please thanks thank hello
""".split())

# Instruction-like phrasing inside tool output (potential prompt injection). Deliberately
# generic: no attack template is matched verbatim.
_CUE_PATTERNS = (
    re.compile(r"<\s*information\s*>", re.I),
    re.compile(r"ignore\b.{0,40}\binstruc", re.I),
    re.compile(r"\binstead\b", re.I),
    re.compile(r"before you (can )?(solve|do|answer|continue|proceed)", re.I),
    re.compile(r"\b(important|urgent)\b.{0,30}\b(message|instruction|task)", re.I),
    re.compile(r"\bTODO\b"),
    re.compile(r"\b(you must|you should|you need to|make sure (to|you)|do the following|first,? (please )?(do|send|email))\b", re.I),
    re.compile(r"\b(to you|assistant|language model|AI model|ai assistant)\b", re.I),
    re.compile(r"\bsigned\b", re.I),
    re.compile(r"\bsystem (message|prompt|override)\b", re.I),
    re.compile(r"(^|[.!?]\s+|\n)\s*(please\s+)?(send|email|forward|delete|share|create|transfer|invite|book|post|reply|click|visit|remove|cancel|add)\b", re.I),
)
_INFO_BLOCK_RE = re.compile(r"<\s*information\s*>.*?<\s*/\s*information\s*>", re.I | re.S)
_SEGMENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")

_MAX_TEXT = 20000  # cap per text to keep extraction fast


# ---- helpers ----------------------------------------------------------------

def _text(message):
    try:
        content = message.get("content")
        return get_text_content_as_str(content) if content else ""
    except Exception:
        return ""


def _flatten(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten(v)]
    if isinstance(value, (list, tuple, set)):
        return [s for v in value for s in _flatten(v)]
    return [str(value)]


def _tokens(text):
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP}


def _emails(text):
    return {e.lower() for e in _EMAIL_RE.findall(text)}


def _stem(w):
    return w[:4]


def _mentions(task_stems, words):
    return any(_stem(w) in task_stems for w in words)


def _injection_span(text):
    """Return (span_text, clean_text, n_cue_patterns) for one tool output.

    The span is the instruction-like part: an <INFORMATION> block if present, otherwise
    each cue-bearing segment plus the two segments after it."""
    text = text[:_MAX_TEXT]
    n_patterns = sum(1 for p in _CUE_PATTERNS if p.search(text))
    if n_patterns == 0:
        return "", text, 0
    spans = [m.group(0) for m in _INFO_BLOCK_RE.finditer(text)]
    rest = _INFO_BLOCK_RE.sub(" ", text)
    segments = [s for s in _SEGMENT_SPLIT_RE.split(rest) if s and s.strip()]
    flagged = set()
    for i, seg in enumerate(segments):
        if any(p.search(seg) for p in _CUE_PATTERNS):
            flagged.update(range(i, min(i + 3, len(segments))))
    spans.extend(segments[i] for i in sorted(flagged))
    span_text = " ".join(spans)
    clean_text = " ".join(segments[i] for i in range(len(segments)) if i not in flagged)
    return span_text, clean_text, n_patterns


def _env_contacts(env):
    """Known email addresses (own account + contacts). Empty set if the suite has none."""
    known = set()
    try:
        inbox = getattr(env, "inbox", None)
        if inbox is not None:
            own = getattr(inbox, "account_email", None)
            if own:
                known.add(own.lower())
            for c in getattr(inbox, "contact_list", []) or []:
                email = getattr(c, "email", None)
                if email:
                    known.add(email.lower())
    except Exception:
        pass
    return known


def _frac(num, den):
    return num / den if den else 0.0


# ---- main -------------------------------------------------------------------

FEATURE_NAMES = (
    [f"cls_{c}" for c in CLASSES] + [
        "n_args", "log_arg_chars", "n_emails", "n_novel_emails", "frac_emails_in_task",
        "frac_emails_known", "frac_emails_in_clean_outputs", "frac_emails_in_span",
        "n_tokens", "frac_tokens_novel", "n_novel_tokens", "frac_novel_in_span",
        "frac_novel_in_clean_outputs", "frac_novel_in_any_output",
        "task_overlap_jaccard", "action_match", "object_match", "action_unmentioned_effect",
        "has_url", "n_sensitive", "n_sensitive_not_in_task",
        "span_mentions_action", "span_mentions_object",
        "verbatim_from_output", "verbatim_from_span",
        "n_cue_outputs", "max_cue_patterns", "cue_in_last_output",
        "cue_patterns_last", "span_chars_log", "has_info_block",
        "effect_x_cue", "effect_x_novel_email", "effect_x_unmentioned",
    ]
)


def extract_features(context):
    """Map a policy context to {feature_name: float}. Never raises."""
    try:
        return _extract(context)
    except Exception:
        return {name: 0.0 for name in FEATURE_NAMES}


def _extract(context):
    call = context["proposed_call"]
    task = (context.get("task") or "")[:_MAX_TEXT]
    traj = list(context.get("trajectory") or [])
    env = context.get("environment")
    name = call.function
    args = call.args or {}

    cls = tool_class(name)
    f = {f"cls_{c}": float(cls == c) for c in CLASSES}
    effect = float(cls != "read")

    task_tokens = _tokens(task)
    task_stems = {_stem(t) for t in re.findall(r"[a-z]{3,}", task.lower())}
    task_emails = _emails(task)
    known = _env_contacts(env)

    arg_strings = _flatten(args)
    arg_text = " ".join(arg_strings)[:_MAX_TEXT]
    arg_tokens = _tokens(arg_text)
    arg_emails = _emails(arg_text)
    novel_tokens = arg_tokens - task_tokens

    # tool outputs: split each into injection-like span and clean remainder
    outputs = [m for m in traj if m.get("role") == "tool"]
    span_texts, clean_texts, cue_counts = [], [], []
    for m in outputs:
        span, clean, n_pat = _injection_span(_text(m))
        span_texts.append(span)
        clean_texts.append(clean)
        cue_counts.append(n_pat)
    span_all = " ".join(s for s in span_texts if s)
    clean_all = " ".join(clean_texts)
    span_tokens, clean_tokens = _tokens(span_all), _tokens(clean_all)
    span_emails, clean_emails = _emails(span_all), _emails(clean_all)
    span_lower, clean_lower = span_all.lower(), clean_all.lower()

    novel_emails = {e for e in arg_emails if e not in task_emails and e not in known}

    f["n_args"] = float(len(args))
    f["log_arg_chars"] = math.log1p(len(arg_text))
    f["n_emails"] = float(len(arg_emails))
    f["n_novel_emails"] = float(len(novel_emails))
    f["frac_emails_in_task"] = _frac(len(arg_emails & task_emails), len(arg_emails))
    f["frac_emails_known"] = _frac(len(arg_emails & known), len(arg_emails))
    f["frac_emails_in_clean_outputs"] = _frac(len(arg_emails & clean_emails), len(arg_emails))
    f["frac_emails_in_span"] = _frac(len(arg_emails & span_emails), len(arg_emails))

    f["n_tokens"] = float(len(arg_tokens))
    f["frac_tokens_novel"] = _frac(len(novel_tokens), len(arg_tokens))
    f["n_novel_tokens"] = float(len(novel_tokens))
    f["frac_novel_in_span"] = _frac(len(novel_tokens & span_tokens), len(novel_tokens))
    f["frac_novel_in_clean_outputs"] = _frac(len(novel_tokens & clean_tokens), len(novel_tokens))
    f["frac_novel_in_any_output"] = _frac(len(novel_tokens & (span_tokens | clean_tokens)), len(novel_tokens))
    f["task_overlap_jaccard"] = _frac(len(arg_tokens & task_tokens), len(arg_tokens | task_tokens))

    # does the user's task plausibly call for this action / object?
    parts = name.split("_")
    action_words = _ACTION_WORDS.get(parts[0], (parts[0],))
    object_words = [w for p in parts[1:] for w in _OBJECT_WORDS.get(p, (p,))]
    f["action_match"] = float(_mentions(task_stems, action_words))
    f["object_match"] = float(_mentions(task_stems, object_words)) if object_words else 1.0
    unmentioned = effect * (1.0 - f["action_match"])
    f["action_unmentioned_effect"] = unmentioned

    f["has_url"] = float(bool(_URL_RE.search(arg_text)))
    n_sens = len(_SENSITIVE_RE.findall(arg_text))
    f["n_sensitive"] = float(n_sens)
    f["n_sensitive_not_in_task"] = float(max(0, n_sens - len(_SENSITIVE_RE.findall(task))))

    span_stems = {_stem(t) for t in re.findall(r"[a-z]{3,}", span_lower)}
    f["span_mentions_action"] = float(_mentions(span_stems, action_words))
    f["span_mentions_object"] = float(_mentions(span_stems, object_words)) if object_words else 0.0

    long_args = [s.strip().lower() for s in arg_strings if len(s.strip()) >= 20]
    f["verbatim_from_output"] = float(any(s in clean_lower or s in span_lower for s in long_args))
    f["verbatim_from_span"] = float(any(s in span_lower for s in long_args))

    f["n_cue_outputs"] = float(sum(1 for c in cue_counts if c))
    f["max_cue_patterns"] = float(max(cue_counts, default=0))
    last_cues = cue_counts[-1] if cue_counts else 0
    f["cue_in_last_output"] = float(last_cues > 0)
    f["cue_patterns_last"] = float(last_cues)
    f["span_chars_log"] = math.log1p(len(span_all))
    f["has_info_block"] = float(bool(_INFO_BLOCK_RE.search(span_all)) or "<information" in span_lower)

    f["effect_x_cue"] = effect * float(f["n_cue_outputs"] > 0)
    f["effect_x_novel_email"] = effect * float(len(novel_emails) > 0)
    f["effect_x_unmentioned"] = unmentioned * float(f["n_cue_outputs"] > 0)

    return {n: float(f[n]) for n in FEATURE_NAMES}


def feature_vector(context):
    feats = extract_features(context)
    return [feats[n] for n in FEATURE_NAMES], feats


def explain(feats):
    """Short factual notes for the reviewer, derived from the feature values."""
    notes = []
    if feats.get("n_novel_emails", 0) > 0:
        notes.append(f"{int(feats['n_novel_emails'])} recipient address(es) not in task or contacts")
    if feats.get("n_cue_outputs", 0) > 0:
        notes.append("instruction-like text appeared in tool output")
    if feats.get("frac_novel_in_span", 0) > 0.5:
        notes.append("arguments mostly come from that instruction-like text")
    if feats.get("action_unmentioned_effect", 0) > 0:
        notes.append("action not mentioned in the user task")
    if feats.get("n_sensitive_not_in_task", 0) > 0:
        notes.append("sensitive keywords not in task")
    return "; ".join(notes)
