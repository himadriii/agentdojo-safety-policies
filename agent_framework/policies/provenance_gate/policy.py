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

    def __init__(self, llm_enricher=None) -> None:
        self.llm_enricher = llm_enricher
        self.client = None

    def evaluate(self, context: PolicyContext, state: dict):
        evidence = None
        try:
            evidence = extract_direct(context)
            if self.llm_enricher:
                evidence = self.llm_enricher(evidence)
            else:
                self.client = self.client or make_groq_client()
                evidence = enrich_with_llm(evidence, self.client)
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
        }

    edges = evidence.get("edges", [])
    return {
        "tool_name": evidence.get("tool_name"),
        "arguments": evidence.get("arguments", {}),
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
                    and edge.get("relation") in {"provides_value", "derived_from"}
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
            "minimum_argument_confidence": 0.8,
            "automatic_adverse_denial_confidence": 0.9,
        },
    }


def decide(evidence: dict) -> tuple[str, str, float | None]:
    """Return approve, deny, or escalate from validated provenance edges."""

    sources = {source["id"]: source for source in evidence["sources"]}
    adverse = [
        edge
        for edge in evidence["edges"]
        if edge["relation"] in {"conflicts_with", "untrusted_influence"}
    ]
    for edge in adverse:
        source_role = sources[edge["source_id"]]["role"]
        clear_violation = (
            edge["relation"] == "untrusted_influence"
            and source_role in {"tool", "assistant"}
        ) or (
            edge["relation"] == "conflicts_with" and source_role == "user"
        )
        if scope_matches(edge, evidence) and edge["confidence"] >= 0.9 and clear_violation:
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
    if not authorizations:
        return "escalate", "missing verified action authorization", None

    action_confidence = max(edge["confidence"] for edge in authorizations)
    if action_confidence < 0.8:
        return "escalate", "action authorization confidence is too low", action_confidence

    confidences = [action_confidence]
    for path, value in sorted(flatten_arguments(evidence["arguments"]).items()):
        confidence = _argument_confidence(evidence, authorizations, path, value)
        if confidence is None:
            return "escalate", f"incomplete provenance for argument {path}", None
        if confidence < 0.8:
            return "escalate", f"provenance confidence is too low for {path}", confidence
        confidences.append(confidence)

    return "approve", "complete authorization and provenance", min(confidences)


def _argument_confidence(evidence, authorizations, path, value):
    """Return the strongest authorized provenance chain for one argument."""

    provenance = [
        edge
        for edge in evidence["edges"]
        if edge["argument_path"] == path
        and edge["relation"] in {"provides_value", "derived_from"}
        and edge.get("verified") is True
    ]
    scores = []
    for authorization in authorizations:
        for edge in provenance:
            # Authorization and value provenance are separate checks. Explicit
            # cited dependencies replace chronological message ancestry.
            scores.append(min(authorization["confidence"], edge["confidence"]))
    return max(scores, default=None)
