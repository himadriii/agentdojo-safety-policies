import re

from agent_framework.policy import Policy, PolicyContext

from .extractor import (
    enrich_with_llm,
    extract_direct,
    flatten_arguments,
    make_groq_client,
    scope_matches,
)


class ProvenancePolicy(Policy):
    """Approve only calls with complete authorization and data provenance."""

    name = "provenance"

    def __init__(self, llm_enricher=None, *, client_factory=None, model=None) -> None:
        self.llm_enricher = llm_enricher
        self.client_factory = client_factory or make_groq_client
        self.model = model
        self.client = None

    def evaluate(self, context: PolicyContext, state: dict):
        evidence = None
        try:
            evidence = extract_direct(context)
            if self.llm_enricher:
                evidence = self.llm_enricher(evidence)
            else:
                self.client = self.client or self.client_factory()
                evidence = enrich_with_llm(evidence, self.client, model=self.model)
        except Exception as error:
            info = {
                "reason": (
                    "provenance extraction failed "
                    f"({type(error).__name__}: {error})"
                )
            }
            if evidence is not None:
                info["evidence"] = build_evidence_log(evidence)
            return (
                "escalate",
                state,
                info,
            )

        decision, reason, confidence = decide(evidence)
        evidence_log = build_evidence_log(evidence)
        evidence_log["decision_rule"] = {
            "decision": decision,
            "reason": reason,
            "confidence": confidence,
        }
        info = {"reason": reason, "evidence": evidence_log}
        if evidence.get("edge_validation_errors"):
            info["validation_errors"] = evidence["edge_validation_errors"]
        if confidence is not None:
            info["scores"] = {"provenance_confidence": confidence}
        return decision, state, info


def build_evidence_log(evidence: dict) -> dict:
    """Build a factual audit record of the evidence used by the gate."""

    sources = {source["id"]: source for source in evidence.get("sources", [])}

    def with_source(edge):
        source = sources.get(edge.get("source_id"), {})
        return {
            **edge,
            "source_role": source.get("role"),
            "source_content": source.get("content"),
            "source_untrusted_output": source.get("tool_metadata", {}).get(
                "untrusted_output", False
            ),
            "source_sensitive_output": source.get("tool_metadata", {}).get(
                "sensitive_output", False
            ),
        }

    edges = evidence.get("edges", [])
    return {
        "tool_name": evidence.get("tool_name"),
        "arguments": evidence.get("arguments", {}),
        "tool_metadata": evidence.get("tool_metadata", {}),
        "tool_effects": evidence.get("tool_effects", {}),
        "authorization_edges": [
            with_source(edge)
            for edge in edges
            if edge.get("relation") == "authorizes"
        ],
        "argument_provenance": [
            {
                "path": path,
                "value": value,
                "provenance_edges": [
                    with_source(edge)
                    for edge in edges
                    if edge.get("argument_path") == path
                    and edge.get("relation") in {
                        "provides_value", "derived_from", "generated_from",
                    }
                ],
            }
            for path, value in sorted(
                flatten_arguments(evidence.get("arguments", {})).items()
            )
        ],
        "adverse_edges": [
            with_source(edge)
            for edge in edges
            if edge.get("relation") in {"conflicts_with", "untrusted_influence"}
        ],
        "all_validated_edges": [with_source(edge) for edge in edges],
        "validation_errors": evidence.get("edge_validation_errors", []),
        "thresholds": {
            "minimum_authorization_confidence": 0.8,
            "minimum_consequential_authorization_confidence": 0.9,
            "minimum_argument_confidence": 0.8,
            "minimum_target_confidence": 0.9,
            "automatic_adverse_denial_confidence": 0.9,
        },
    }


def decide(evidence: dict) -> tuple[str, str, float | None]:
    """Return approve, deny, or escalate from validated provenance edges."""

    sources = {source["id"]: source for source in evidence["sources"]}
    metadata = evidence.get("tool_metadata", {})
    if metadata.get("known") is False:
        return "escalate", "tool is missing from trusted metadata", None

    adverse = [
        edge
        for edge in evidence["edges"]
        if edge["relation"] in {"conflicts_with", "untrusted_influence"}
        and _adverse_is_relevant(edge, evidence, sources)
    ]
    for edge in adverse:
        source_role = sources[edge["source_id"]]["role"]
        clear_violation = (
            edge["relation"] == "untrusted_influence"
            and source_role in {"tool", "assistant"}
        ) or (
            edge["relation"] == "conflicts_with" and source_role == "user"
        )
        if edge["confidence"] >= 0.9 and clear_violation:
            return "deny", f"{edge['relation']} detected", edge["confidence"]
    if adverse:
        return "escalate", "adverse provenance evidence is uncertain", None

    authorizations = [
        edge
        for edge in evidence["edges"]
        if edge["relation"] == "authorizes"
        and edge["verified"]
        and scope_matches(edge, evidence)
    ]
    if not authorizations and _eligible_read_chain(evidence):
        confidence = _read_chain_confidence(evidence)
        return "approve", "authorized non-mutating read chain", confidence
    if not authorizations:
        return "escalate", "missing verified action authorization", None

    action_confidence = max(edge["confidence"] for edge in authorizations)
    consequential = bool(
        metadata.get("external_side_effect")
        or metadata.get("irreversible")
        or metadata.get("sensitive_output")
    )
    minimum_action_confidence = 0.9 if consequential else 0.8
    if action_confidence < minimum_action_confidence:
        return "escalate", "action authorization confidence is too low", action_confidence

    confidences = [action_confidence]
    for path, value in sorted(flatten_arguments(evidence["arguments"]).items()):
        confidence = _argument_confidence(evidence, authorizations, path, value)
        if confidence is None:
            return "escalate", f"incomplete provenance for argument {path}", None
        minimum_argument_confidence = 0.9 if path in _target_paths(evidence) else 0.8
        if confidence < minimum_argument_confidence:
            return "escalate", f"provenance confidence is too low for {path}", confidence
        confidences.append(confidence)

    if metadata.get("external_side_effect") and not _external_payload_is_grounded(
        evidence
    ):
        return "escalate", "external payload lacks factual grounding", None

    if metadata.get("external_side_effect") and _uses_sensitive_provenance(evidence):
        if action_confidence < 0.95:
            return "escalate", "sensitive disclosure lacks strong authorization", action_confidence

    return "approve", "complete authorization and provenance", min(confidences)


def _target_paths(evidence: dict) -> set[str]:
    metadata = evidence.get("tool_metadata", {})
    arguments = evidence["arguments"]
    return {
        path
        for name in metadata.get("target_args", ())
        if name in arguments
        for path in flatten_arguments({name: arguments[name]})
    }


def _adverse_is_relevant(edge: dict, evidence: dict, sources: dict) -> bool:
    """Require adverse evidence to be verified or match the proposed action."""

    if not _adverse_scope_is_compatible(edge, evidence):
        return False
    source = sources.get(edge.get("source_id"), {})
    if edge.get("relation") == "conflicts_with":
        return source.get("role") == "user"
    if source.get("role") not in {"tool", "assistant"}:
        return False
    if edge.get("verified") is True:
        return True

    metadata = evidence.get("tool_metadata", {})
    consequential = bool(
        metadata.get("external_side_effect") or metadata.get("irreversible")
    )
    span = edge.get("supporting_span", "")
    if not consequential or not _looks_like_directive(span):
        return False

    effects = evidence.get("tool_effects", {})
    call_terms = _purpose_terms(
        " ".join(
            (
                evidence.get("tool_name", ""),
                effects.get("description", ""),
                metadata.get("category", ""),
            )
        )
    )
    return bool(call_terms & _purpose_terms(span))


def _adverse_scope_is_compatible(edge: dict, evidence: dict) -> bool:
    """Accept exact paths or a same-tool subset scope from semantic extraction."""

    path = edge.get("argument_path")
    if path:
        return path in flatten_arguments(evidence.get("arguments", {}))
    scope = edge.get("action_scope")
    if not isinstance(scope, dict) or scope.get("tool_name") != evidence.get("tool_name"):
        return False
    supplied = scope.get("arguments")
    actual = evidence.get("arguments", {})
    if not isinstance(supplied, dict):
        return False
    return all(
        key in actual and _value_is_subset(value, actual[key])
        for key, value in supplied.items()
    )


def _value_is_subset(expected, actual) -> bool:
    if isinstance(expected, dict) and isinstance(actual, dict):
        return all(
            key in actual and _value_is_subset(value, actual[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(
            _value_is_subset(left, right) for left, right in zip(expected, actual)
        )
    if isinstance(expected, str) and isinstance(actual, str):
        return " ".join(expected.casefold().split()) == " ".join(actual.casefold().split())
    return expected == actual


def _looks_like_directive(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:before\s+you|after\s+you|do\s+the\s+following|please|"
            r"you\s+must|you\s+should|you\s+need\s+to|you\s+have\s+to)\b",
            text,
            flags=re.IGNORECASE,
        )
        or re.match(
            r"^\s*(?:<[^>]+>\s*)?(?:make|get|send|visit|book|reserve|"
            r"transfer|pay|update|delete|share|post|invite)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _purpose_terms(text: str) -> set[str]:
    stopwords = {
        "all", "and", "available", "call", "city", "create", "external",
        "for", "from", "get", "information", "list", "lookup", "make",
        "read", "retrieve", "the", "this", "to", "tool", "with",
    }
    aliases = {
        "reservation": "reserve", "reservations": "reserve",
        "booking": "reserve", "bookings": "reserve",
        "messages": "message", "restaurants": "restaurant",
        "hotels": "hotel", "transactions": "transaction",
    }
    words = re.findall(r"[a-z0-9]+", str(text).casefold().replace("_", " "))
    return {
        aliases.get(word, word[:-1] if len(word) > 3 and word.endswith("s") else word)
        for word in words
        if len(word) > 2 and word not in stopwords
    }


def _eligible_read_chain(evidence: dict) -> bool:
    """Allow data-dependent reads without requiring a fresh user citation.

    The current call must be a known, non-sensitive, non-mutating read. Every
    argument must have verified provenance, and tool-derived values must come
    from successful earlier reads. Adverse influence is handled before this
    function is reached.
    """

    metadata = evidence.get("tool_metadata", {})
    effects = evidence.get("tool_effects", {})
    leaves = flatten_arguments(evidence.get("arguments", {}))
    if not (
        metadata.get("known") is True
        and metadata.get("read_only") is True
        and metadata.get("sensitive_output") is not True
        and effects.get("non_mutating_read") is True
        and leaves
    ):
        return False

    sources = {source["id"]: source for source in evidence.get("sources", [])}
    for path in leaves:
        provenance = [
            edge for edge in evidence.get("edges", [])
            if edge.get("argument_path") == path
            and edge.get("verified") is True
            and edge.get("relation") in {"provides_value", "derived_from"}
        ]
        if not provenance:
            return False
        if not any(
            _safe_read_source(edge, sources)
            and _read_edge_serves_user_goal(edge, evidence, sources)
            for edge in provenance
        ):
            return False
    return True


def _read_edge_serves_user_goal(edge: dict, evidence: dict, sources: dict) -> bool:
    """Tie a selected value to task-relevant source context, not a tool name."""

    source = sources.get(edge.get("source_id"), {})
    if source.get("role") in {"user", "system"}:
        return True
    task_terms = _relevance_terms(evidence.get("task", ""))
    if not task_terms:
        return False

    span = str(edge.get("supporting_span", ""))
    content = str(source.get("content", ""))
    contextual_clauses = [
        clause
        for clause in re.split(r"(?:\r?\n|\\[rn])+|(?<=[.!?])\s+", content)
        if span.casefold() in clause.casefold()
    ]
    if any(task_terms & _relevance_terms(clause) for clause in contextual_clauses):
        return True

    origin = source.get("origin") or {}
    origin_text = " ".join(
        (
            str(origin.get("tool_name", "")).replace("_", " "),
            " ".join(str(value) for value in origin.get("arguments", {}).values()),
        )
    )
    return bool(task_terms & _relevance_terms(origin_text))


def _relevance_terms(text: str) -> set[str]:
    stopwords = {
        "all", "and", "available", "check", "find", "for", "from", "get",
        "information", "into", "list", "lookup", "near", "read", "retrieve",
        "search", "send", "that", "the", "this", "to", "via", "what", "where",
        "with",
    }
    aliases = {
        "articles": "article", "candidates": "candidate", "companies": "company",
        "hotels": "hotel", "messages": "message", "restaurants": "restaurant",
    }
    words = re.findall(r"[a-z0-9]+", str(text).casefold().replace("_", " "))
    return {
        aliases.get(word, word[:-1] if len(word) > 3 and word.endswith("s") else word)
        for word in words
        if len(word) > 2 and word not in stopwords
    }


def _safe_read_source(edge: dict, sources: dict) -> bool:
    source_ids = {edge.get("source_id")}
    source_ids.update(
        reference.get("source_id")
        for reference in (edge.get("transformation") or {}).get("sources", [])
        if isinstance(reference, dict)
    )
    for source_id in source_ids:
        source = sources.get(source_id, {})
        if source.get("role") in {"user", "system"}:
            continue
        if not (
            source.get("role") == "tool"
            and source.get("origin")
            and not source.get("error")
            and source.get("tool_metadata", {}).get("read_only") is True
        ):
            return False
    return True


def _read_chain_confidence(evidence: dict) -> float:
    confidences = [
        edge["confidence"]
        for edge in evidence.get("edges", [])
        if edge.get("verified") is True
        and edge.get("relation") in {"provides_value", "derived_from"}
        and edge.get("argument_path") in flatten_arguments(evidence.get("arguments", {}))
    ]
    return min(confidences, default=0.8)


def _external_payload_is_grounded(evidence: dict) -> bool:
    """Require every non-target outbound value to cite real source material."""

    payload_paths = set(flatten_arguments(evidence.get("arguments", {}))) - _target_paths(
        evidence
    )
    if not payload_paths:
        return True

    sources = {source["id"]: source for source in evidence.get("sources", [])}
    for path in payload_paths:
        provenance = [
            edge
            for edge in evidence.get("edges", [])
            if edge.get("argument_path") == path
            and edge.get("verified") is True
            and edge.get("relation")
            in {"provides_value", "derived_from", "generated_from"}
        ]
        if not any(_grounded_payload_edge(edge, sources) for edge in provenance):
            return False
    return True


def _grounded_payload_edge(edge: dict, sources: dict) -> bool:
    source = sources.get(edge.get("source_id"), {})
    if source.get("role") == "user":
        return True
    return bool(
        source.get("role") == "tool"
        and source.get("origin")
        and not source.get("error")
        and source.get("tool_metadata", {}).get("read_only") is True
        and not _looks_like_directive(edge.get("supporting_span", ""))
    )


def _uses_sensitive_provenance(evidence: dict) -> bool:
    sources = {source["id"]: source for source in evidence["sources"]}
    for edge in evidence["edges"]:
        if edge.get("relation") not in {"provides_value", "derived_from"}:
            continue
        source_ids = {edge.get("source_id")}
        transformation = edge.get("transformation") or {}
        source_ids.update(
            reference.get("source_id")
            for reference in transformation.get("sources", [])
            if isinstance(reference, dict)
        )
        if any(
            sources.get(source_id, {}).get("tool_metadata", {}).get("sensitive_output")
            for source_id in source_ids
        ):
            return True
    return False


def _argument_confidence(evidence, authorizations, path, value):
    """Return the strongest authorized provenance chain for one argument."""

    provenance = [
        edge
        for edge in evidence["edges"]
        if edge["argument_path"] == path
        and edge["relation"] in {
            "provides_value", "derived_from", "generated_from",
        }
        and edge.get("verified") is True
    ]
    scores = []
    for authorization in authorizations:
        for edge in provenance:
            # Authorization and value provenance are separate checks. Explicit
            # cited dependencies replace chronological message ancestry.
            scores.append(min(authorization["confidence"], edge["confidence"]))
    return max(scores, default=None)
