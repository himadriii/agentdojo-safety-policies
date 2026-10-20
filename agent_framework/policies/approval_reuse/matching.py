"""Decide whether a proposed call is covered by an approved call or repeats a denied one.

Pure functions over tool names and argument dicts, shared by the gate, the similarity
comparison and the offline probe set.
"""
import json
import re

from agent_framework.policies.approval_reuse.tool_table import spec_for

_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b(?:/[^\s<>\"']*)?", re.I)
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")  # anchored: no quadratic rescans
_DIGITS_RE = re.compile(r"\b\d{5,}\b")
_MIXED_RE = re.compile(r"\b(?=[a-z0-9]*[a-z])(?=[a-z0-9]*\d)[a-z0-9]{8,}\b", re.I)


_SCHEME_RE = re.compile(r"^https?://", re.I)
MIN_GROUNDED_LEN = 3   # shorter argument values (ids, counts) do not count as evidence of a drill-down


def _norm(value) -> str:
    """Case-folded text; links also lose the scheme, a leading www. and a trailing slash."""
    text = str(value).strip().casefold()
    if _SCHEME_RE.match(text) or text.startswith("www."):
        text = _SCHEME_RE.sub("", text).removeprefix("www.").rstrip("/")
    return text


def _as_set(value) -> frozenset:
    if value is None:
        return frozenset()
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(_norm(v) for v in value if v is not None)
    return frozenset({_norm(value)})


def _key_names(spec, *arg_dicts):
    if spec.key is None:   # unknown tool: every argument is key
        return set().union(*(d.keys() for d in arg_dicts))
    return spec.key


def _amount_within(new, approved) -> bool:
    try:
        return float(new) <= float(approved)
    except (TypeError, ValueError):
        return False


def free_text_names(tool: str, args: dict) -> list[str]:
    """Arguments that are neither key nor amount for `tool`, in argument order."""
    spec = spec_for(tool)
    named = _key_names(spec, args) | spec.amount
    return [k for k in args if k not in named]


def _free_text(tool, args) -> str:
    return " ".join(str(args[k]) for k in free_text_names(tool, args) if args[k] is not None)


def injected_tokens(text: str, known: str) -> list[str]:
    """Links, email addresses and code-like tokens in `text` that `known` never mentions."""
    known = known.casefold()
    patterns = (_URL_RE, _EMAIL_RE, _DIGITS_RE, _MIXED_RE) if "@" in text else (_URL_RE, _DIGITS_RE, _MIXED_RE)
    found = []
    for pattern in patterns:
        found.extend(m.group(0) for m in pattern.finditer(text))
    return [t for t in found if t.casefold() not in known]


def leaf_values(value) -> list[str]:
    """Non-empty scalar values inside an argument value, flattened."""
    if isinstance(value, dict):
        return [v for x in value.values() for v in leaf_values(x)]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [v for x in value for v in leaf_values(x)]
    text = "" if value is None else str(value)
    return [text] if text.strip() else []


def _args_text(args: dict) -> str:
    return " ".join(leaf_values(args))


def covers_approval(tool: str, new_args: dict, approved_args: dict, task_text: str) -> bool:
    """True when an approval of `approved_args` also authorizes `new_args` for the same tool."""
    spec = spec_for(tool)
    for name in _key_names(spec, new_args, approved_args):
        if not _as_set(new_args.get(name)) <= _as_set(approved_args.get(name)):
            return False
    known = f"{task_text} {json.dumps(approved_args, default=str)}"
    if not spec.side_effect:   # a read may not smuggle in a new link, address or code either
        return not injected_tokens(_free_text(tool, new_args), known)
    for name in spec.amount:
        if not _amount_within(new_args.get(name), approved_args.get(name)):
            return False
    return not injected_tokens(_free_text(tool, new_args), known)


def drill_down_covers(tool: str, new_args: dict, root_tool: str, root_args: dict, pool: str, task_text: str) -> bool:
    """True when a read of another tool only follows up on what an approved read already returned.

    `pool` is the text the approved read (and the calls it covered) took and returned. Every
    substantive argument value must occur in the task or the pool, there must be at least one
    such value, and no argument may carry a link, address or code that the task and the approved
    call do not already mention. Side effects are never covered across tools.
    """
    if spec_for(tool).side_effect or spec_for(root_tool).side_effect:
        return False
    values = [v for v in leaf_values(new_args) if len(v.strip()) >= MIN_GROUNDED_LEN]
    if not values:
        return False
    if injected_tokens(_args_text(new_args), f"{task_text} {json.dumps(root_args, default=str)}"):
        return False
    haystack = f"{task_text} {pool}".casefold()
    return all(v.strip().casefold() in haystack for v in values)


def matches_denial(tool: str, new_args: dict, denied_args: dict) -> bool:
    """True when `new_args` repeats a call the reviewer denied."""
    spec = spec_for(tool)
    if not spec.side_effect:
        return _canonical(new_args) == _canonical(denied_args)
    names = _key_names(spec, new_args, denied_args)
    return all(_as_set(new_args.get(n)) == _as_set(denied_args.get(n)) for n in names)


def _canonical(args: dict) -> dict:
    return {k: _as_set(v) for k, v in args.items() if v is not None}
