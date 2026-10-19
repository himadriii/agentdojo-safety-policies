"""Comparison gate: reuse approvals by lexical similarity alone.

This is the "cluster similar operations" reading of the original idea, kept only to
measure what unrestricted similarity reuse costs in safety. It has no key-argument
protection, no injected-token scan and no denial memory.
"""
import json
import re

from agent_framework.policies.approval_reuse.policy import ApprovalReusePolicy

_TOKEN_RE = re.compile(r"[a-z0-9]+")
THRESHOLD = 0.5


def _tokens(args: dict) -> set:
    return set(_TOKEN_RE.findall(json.dumps(list(args.values()), default=str).casefold()))


def similar_enough(tool, new_args, approved_args, task_text, threshold=THRESHOLD) -> bool:
    new, old = _tokens(new_args), _tokens(approved_args)
    if not new and not old:
        return True
    return len(new & old) / len(new | old) >= threshold


class SimilarityReusePolicy(ApprovalReusePolicy):
    name = "similarity_reuse"

    def __init__(self, base=None):
        super().__init__(base=base, covers=similar_enough, remember_denials=False)
