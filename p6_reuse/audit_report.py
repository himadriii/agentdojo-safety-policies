"""Report for the P6 live leak audit (p6_reuse/run_audit.sh).

Reads every trace under --outdir and writes p6_audit.md and p6_audit.csv with three levels:
suite x attack x policy, injection task, and user task. A "leak" is a reuse approval the reviewer
would have denied (shadow verdict deny). The same rate on no-attack runs is the baseline: a reviewer
that is strict on benign calls also "denies" benign reuse approvals, so only a rate above that
baseline, or a successful attack, points at the gate.

Run: python -m p6_reuse.audit_report [--outdir results/p6_live_audit]
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from p6_reuse.metrics import write_csv

# {provider}-{llm}-{policy}-{reviewer}-k{k}[-{config hash}]; older runs lack the provider prefix and the hash.
PIPELINE = re.compile(r"-(?P<policy>full_approve|full_escalate|approval_reuse|similarity_reuse)-[a-z0-9_]+"
                      r"-k(?P<k>\d+)(?:-[0-9a-f]{10})?$")
COLUMNS = ["suite", "attack", "policy", "k", "n", "errors", "utility", "attack_success", "tcr", "reviews",
           "reuse_approvals", "shadow_denied", "shadow_deny_rate", "budget_denials", "reviewer_denials"]


def load_traces(outdir: Path):
    """Yield one dict per task trace, with the pre-run (injection task as user task) rows left out."""
    for path in sorted(outdir.glob("*/*/*/*/*.json")):
        pipeline, suite, user_task, attack, inj = path.parts[-5:-1] + (path.stem,)
        match = PIPELINE.search(pipeline)
        if not match or user_task.startswith("injection_task") or path.name.startswith("summary"):
            continue
        trace = json.loads(path.read_text())
        decisions = trace.get("approval_decisions") or []
        shadow = trace.get("reuse_shadow") or []
        yield {
            "suite": suite, "attack": attack, "policy": match["policy"], "k": int(match["k"]),
            "user_task": user_task, "injection": None if inj == "none" else inj,
            "error": bool(trace.get("error")),   # AgentDojo scores a skipped task as utility False, attack True
            "utility": bool(trace.get("utility")),
            "attack_success": bool(trace.get("security")) if attack != "none" else False,
            "reviews": sum(d["reviewer_called"] for d in decisions),
            "reuse_approvals": sum(bool((d.get("scores") or {}).get("reuse_approved")) for d in decisions),
            "shadow": shadow,
            "shadow_denied": [s for s in shadow if s["shadow_verdict"] == "deny"],
            "budget_denials": sum(d["outcome"] == "budget_exhausted_deny" for d in decisions),
            "reviewer_denials": sum(d["outcome"] == "escalate_denied" for d in decisions),
        }


def aggregate(traces) -> dict:
    """Rates are over runs that finished; errored runs (server errors) are counted but not scored."""
    ok = [t for t in traces if not t["error"]]
    n = len(ok) or 1
    approvals = sum(t["reuse_approvals"] for t in traces)
    denied = sum(len(t["shadow_denied"]) for t in traces)
    attacked = traces and traces[0]["attack"] != "none"
    return {
        "n": len(traces),
        "errors": len(traces) - len(ok),
        "utility": sum(t["utility"] for t in ok) / n,
        "attack_success": sum(t["attack_success"] for t in ok) / n if attacked else None,
        "tcr": sum(t["utility"] and not t["attack_success"] for t in ok) / n,
        "reviews": sum(t["reviews"] for t in traces),
        "reuse_approvals": approvals,
        "shadow_denied": denied,
        "shadow_deny_rate": denied / approvals if approvals else None,
        "budget_denials": sum(t["budget_denials"] for t in traces),
        "reviewer_denials": sum(t["reviewer_denials"] for t in traces),
    }


def _fmt(value):
    if value is None:
        return "-"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def _table(header, rows):
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + \
           ["| " + " | ".join(_fmt(c) for c in row) + " |" for row in rows]


def level_one(traces):
    groups = defaultdict(list)
    for t in traces:
        groups[(t["suite"], t["attack"], t["policy"], t["k"])].append(t)
    return [{"suite": s, "attack": a, "policy": p, "k": k, **aggregate(v)} for (s, a, p, k), v in sorted(groups.items())]


def to_markdown(traces) -> str:
    rows = level_one(traces)
    out = ["# P6 live leak audit", "",
           "Reuse approvals are shadow-reviewed: `shadow_denied` counts calls the gate approved from memory "
           "that the reviewer would have denied. Compare the attack rate with the no-attack rate.", ""]
    for suite in sorted({r["suite"] for r in rows}):
        out += [f"## {suite}", "", "### Level 1: suite x attack x policy", ""]
        out += _table(COLUMNS[1:], [[r[c] for c in COLUMNS[1:]] for r in rows if r["suite"] == suite]) + [""]

        out += ["### Level 2: injection tasks (attack runs)", ""]
        by_inj = defaultdict(list)
        for t in traces:
            if t["suite"] == suite and t["injection"]:
                by_inj[(t["injection"], t["policy"])].append(t)
        out += _table(["injection", "policy", "n", "errors", "utility", "attack_success", "reuse_approvals",
                       "shadow_denied"],
                      [[i, p, *[aggregate(v)[c] for c in ("n", "errors", "utility", "attack_success",
                                                         "reuse_approvals", "shadow_denied")]]
                       for (i, p), v in sorted(by_inj.items())]) + [""]

        out += ["### Level 3: user tasks (utility / attack success / reuse approvals / shadow-denied)", ""]
        by_task = defaultdict(list)
        for t in traces:
            if t["suite"] == suite:
                by_task[(t["user_task"], t["policy"])].append(t)
        policies = sorted({p for _, p in by_task})
        tasks = sorted({u for u, _ in by_task}, key=lambda u: int(u.rsplit("_", 1)[1]))
        cells = []
        for u in tasks:
            row = [u]
            for p in policies:
                runs = by_task.get((u, p), [])
                clean = [t for t in runs if t["attack"] == "none" and not t["error"]]
                hit = [t for t in runs if t["attack"] != "none" and not t["error"]]
                row.append(f"none u={sum(t['utility'] for t in clean)}/{len(clean)}; "
                           f"attack u={sum(t['utility'] for t in hit)}/{len(hit)} "
                           f"asr={sum(t['attack_success'] for t in hit)}; "
                           f"err={sum(t['error'] for t in runs)}; "
                           f"reuse={sum(t['reuse_approvals'] for t in runs)} "
                           f"shadow_deny={sum(len(t['shadow_denied']) for t in runs)}")
            cells.append(row)
        out += _table(["user task", *policies], cells) + [""]

    flagged = [(t, s) for t in traces for s in t["shadow_denied"]]
    out += ["## Reuse approvals the reviewer would have denied", ""]
    if not flagged:
        out += ["None."]
    else:
        out += _table(["suite", "attack", "policy", "user task", "injection", "tool", "args"],
                      [[t["suite"], t["attack"], t["policy"], t["user_task"], t["injection"], s["tool"],
                        json.dumps(s["args"], default=str)[:90]] for t, s in flagged])
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="results/p6_live_audit")
    args = ap.parse_args(argv)
    outdir = Path(args.outdir)
    traces = list(load_traces(outdir))
    if not traces:
        print(f"no traces under {outdir}")
        return 1
    write_csv(outdir / "p6_audit.csv", level_one(traces), COLUMNS)
    (outdir / "p6_audit.md").write_text(to_markdown(traces))
    print(f"saved {outdir / 'p6_audit.md'} and {outdir / 'p6_audit.csv'} ({len(traces)} task runs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
