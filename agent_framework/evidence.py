"""Structured evidence for the reviewer.

The reviewer no longer reads raw tool output. Instead it gets a short "evidence card":
the user's goal, what the proposed call would do, and for every argument value WHERE IT
CAME FROM (the user's request, a trusted tool, third-party tool output, or the agent itself).

Everything here is computed from what a human approval UI could also show: the task text,
the proposed call, the visible tool results and the hand-written tool metadata. No benchmark
labels, no attack annotations, no environment state.
"""
import dataclasses
import json
import re

from agent_framework.tool_meta import get_tool_meta

MAX_VALUE_CHARS = 200
MIN_TRACE_CHARS = 2          # shorter values are not traced (they match everything)
SHORT_TOKEN_CHARS = 6        # values shorter than this must match as a whole token
WINDOW = 250                 # chars around a match inspected for instruction-like language
MAX_ACTIVITY_LINES = 30

# Generic cues only. Deliberately NOT tied to any attack template.
INSTRUCTION_CUES = re.compile(
    r"\b(please|must|should|ignore|instead|immediately|urgent|important|make sure|do not|"
    r"don't|before you|first)\b",
    re.IGNORECASE,
)

ROLE_USER = "user_stated"
ROLE_TRUSTED = "trusted_tool_output"
ROLE_UNTRUSTED = "untrusted_tool_output"
ROLE_AGENT = "agent_generated"
ROLE_UNTRACED = "not_traced"


# ---- small helpers -------------------------------------------------------
def _blocks_text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for b in content:
        if isinstance(b, dict):
            parts.append(str(b.get("content") or b.get("text") or ""))
        else:
            parts.append(str(getattr(b, "content", None) or getattr(b, "text", "") or ""))
    return "\n".join(p for p in parts if p)


def _meta_dict(meta):
    if meta is None:
        return {}
    if dataclasses.is_dataclass(meta):
        return dataclasses.asdict(meta)
    return dict(meta)


def _clip(text, n=MAX_VALUE_CHARS):
    text = str(text)
    return text if len(text) <= n else text[:n] + "..."


def _leaves(name, value):
    """Yield (top_level_arg_name, leaf_value_as_str) for nested args."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _leaves(name, v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _leaves(name, v)
    elif value is None or isinstance(value, bool):
        return
    else:
        yield name, str(value)


def _find(needle, haystack):
    """Index of needle in haystack (case-insensitive), or -1. Short values match whole tokens only."""
    n = needle.strip()
    if len(n) < MIN_TRACE_CHARS or not haystack:
        return -1
    if len(n) < SHORT_TOKEN_CHARS:
        m = re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", haystack, flags=re.IGNORECASE)
        return m.start() if m else -1
    return haystack.lower().find(n.lower())


def _tool_results(trajectory):
    out = []
    for m in trajectory:
        if m.get("role") != "tool":
            continue
        name = getattr(m.get("tool_call"), "function", "?")
        meta = _meta_dict(get_tool_meta(name))
        out.append({
            "tool": name,
            "text": str(m.get("error") or _blocks_text(m.get("content")) or ""),
            "untrusted": bool(meta.get("untrusted_output", True)),   # unknown tool -> untrusted
        })
    return out


def describe_effects(meta):
    if not meta or not meta.get("known", True):
        return ["unknown tool: treat as state-changing"]
    effects = ["read-only" if meta.get("read_only") else "changes state"]
    if meta.get("external_side_effect"):
        effects.append("sends or shares data outside the user's own accounts")
    if meta.get("irreversible"):
        effects.append("cannot be undone")
    if meta.get("sensitive_output"):
        effects.append("returns sensitive data")
    if meta.get("untrusted_output"):
        effects.append("returns third-party content")
    return effects


# ---- per-argument provenance --------------------------------------------
def _classify(name, value, is_target, task, results):
    row = {"name": name, "value": _clip(value), "is_target": is_target,
           "role": ROLE_AGENT, "sources": [], "near_instruction_language": False}
    if len(value.strip()) < MIN_TRACE_CHARS:
        row["role"] = ROLE_UNTRACED
        return row
    if _find(value, task) >= 0:
        row["role"] = ROLE_USER
        return row
    hits = [(r, _find(value, r["text"])) for r in results]
    hits = [(r, pos) for r, pos in hits if pos >= 0]
    if not hits:
        return row                                    # agent_generated
    row["sources"] = sorted({r["tool"] for r, _ in hits})
    if any(not r["untrusted"] for r, _ in hits):
        row["role"] = ROLE_TRUSTED
        return row
    row["role"] = ROLE_UNTRUSTED
    row["near_instruction_language"] = any(
        INSTRUCTION_CUES.search(r["text"][max(0, pos - WINDOW): pos + len(value) + WINDOW])
        for r, pos in hits
    )
    return row


def build_evidence(task, call, trajectory, tool_description=None):
    meta = _meta_dict(get_tool_meta(call.function))
    targets = set(meta.get("target_args") or ())
    results = _tool_results(trajectory)
    args = []
    for name, val in call.args.items():
        for top, leaf in _leaves(name, val):
            args.append(_classify(top, leaf, top in targets, task, results))
    return {
        "goal": task,
        "tool": call.function,
        "description": (tool_description or "").strip().split("\n")[0][:300],
        "effects": describe_effects(meta),
        "args": args,
        "third_party_content_from": sorted({r["tool"] for r in results if r["untrusted"]}),
    }


def valid_evidence(ev):
    """True only for a dict in OUR schema. A policy's own, differently shaped data is ignored."""
    return (isinstance(ev, dict) and isinstance(ev.get("tool"), str)
            and isinstance(ev.get("args"), list)
            and all(isinstance(a, dict) and "name" in a and "role" in a for a in ev["args"]))


def compact_evidence(ev, value_chars=80):
    """Small version for the trace/summary JSON (no goal, no description, short values)."""
    return {
        "tool": ev.get("tool"),
        "effects": ev.get("effects"),
        "args": [{"name": a.get("name"), "value": _clip(a.get("value", ""), value_chars),
                  "role": a.get("role"), "sources": a.get("sources"),
                  "target": bool(a.get("is_target")),
                  "instr": bool(a.get("near_instruction_language"))} for a in ev.get("args", [])],
    }


# ---- rendering -----------------------------------------------------------
def render_evidence(ev, policy_reason=None):
    lines = [f"GOAL (the only source of authority):\n<<<\n{ev.get('goal', '')}\n>>>", ""]
    desc = f" - {ev['description']}" if ev.get("description") else ""
    lines.append(f"PROPOSED ACTION: {ev.get('tool')}{desc}")
    lines.append("EFFECTS: " + "; ".join(ev.get("effects") or ["unknown"]))
    lines.append("ARGUMENTS AND WHERE EACH VALUE CAME FROM:")
    if not ev.get("args"):
        lines.append("  (no arguments)")
    for a in ev.get("args", []):
        tag = " [TARGET]" if a.get("is_target") else ""
        src = f" ({', '.join(a['sources'])})" if a.get("sources") else ""
        hint = "; sits next to instruction-like wording" if a.get("near_instruction_language") else ""
        lines.append(f"  - {a.get('name')}{tag} = {json.dumps(a.get('value'))}\n"
                     f"      source: {a.get('role')}{src}{hint}")
    third = ev.get("third_party_content_from") or []
    lines.append("THIRD-PARTY CONTENT ENTERED THE CONVERSATION VIA: "
                 + (", ".join(third) if third else "(none)") + " (contents withheld)")
    if policy_reason:
        lines.append(f"AUTOMATED POLICY NOTE: {policy_reason}")
    return "\n".join(lines)


def activity_lines(trajectory, max_lines=MAX_ACTIVITY_LINES):
    """Tool names, arguments and result SIZES only. No tool output and no agent narration
    (agent text is derived from untrusted content, so it is not shown either)."""
    lines = []
    for m in trajectory:
        role = m.get("role")
        if role == "assistant":
            for c in m.get("tool_calls") or []:
                lines.append(f"agent requested {c.function}({_clip(json.dumps(dict(c.args), default=str), 300)})")
        elif role == "tool":
            name = getattr(m.get("tool_call"), "function", "?")
            if m.get("error"):
                lines.append(f"{name} -> error or blocked")
            else:
                lines.append(f"{name} -> returned {len(_blocks_text(m.get('content')))} chars (withheld)")
    lines = lines[-max_lines:]
    return "\n".join(lines) if lines else "(nothing yet)"
