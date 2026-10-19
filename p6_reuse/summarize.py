"""Summarize P6 live runs from the runner's saved summaries and traces (plan R18).

Reads every results/<pipeline>/summary_<suite>_<attack>.json under --outdir plus the per-task
traces it points to, and writes one comparison table per suite (policy x k x attack).
Live attack success comes from AgentDojo's final-state check and is never mixed with the
replay attack success that p6_reuse.replay reports.

Run: python -m p6_reuse.summarize [--outdir results/p6_live]
"""
import argparse
import csv
import json
from pathlib import Path

COLUMNS = ["suite", "policy", "k", "attack", "n", "tcr", "utility", "live_attack_success", "reviews",
           "reviews_saved_approval", "reviews_saved_denial", "budget_exhausted_denials", "mean_gate_ms",
           "reviewer_unparseable", "policy_tokens", "tasks_with_errors"]


def _trace(run_dir, suite, attack, row_key):
    user_task, inj = row_key.split("|")
    path = run_dir / suite / user_task / attack / f"{inj if inj != 'None' else 'none'}.json"
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def summarize_run(summary_path: Path) -> dict:
    s = json.loads(summary_path.read_text())
    run_dir = summary_path.parent
    rows = s["rows"]
    decisions, unparseable = [], 0
    for key in rows:
        trace = _trace(run_dir, s["suite"], s["attack"], key)
        decisions.extend(trace.get("approval_decisions", []))
        unparseable += trace.get("reviewer_unparseable", 0)
    gate_ms = [d["scores"]["gate_ms"] for d in decisions if (d.get("scores") or {}).get("gate_ms") is not None]
    n = len(rows) or 1
    attacked = s["attack"] != "none"
    policy_tokens = s.get("token_usage", {}).get("policy", {})
    return {
        "suite": s["suite"], "policy": s["policy"], "k": s["k"], "attack": s["attack"], "n": len(rows),
        "tcr": s["tcr"],
        "utility": sum(r["utility"] for r in rows.values()) / n,
        "live_attack_success": sum(r["attack_succeeded"] for r in rows.values()) / n if attacked else None,
        "reviews": s["hitl_load_all"],
        "reviews_saved_approval": sum(d["outcome"] == "auto_approve" and (d.get("scores") or {}).get("reuse_approved") == 1.0
                                      for d in decisions),
        "reviews_saved_denial": sum(d["outcome"] == "auto_deny" and (d.get("scores") or {}).get("reuse_denied") == 1.0
                                    for d in decisions),
        "budget_exhausted_denials": sum(d["outcome"] == "budget_exhausted_deny" for d in decisions),
        "mean_gate_ms": sum(gate_ms) / len(gate_ms) if gate_ms else None,
        "reviewer_unparseable": unparseable,
        "policy_tokens": policy_tokens.get("input_tokens", 0) + policy_tokens.get("output_tokens", 0),
        "tasks_with_errors": s.get("tasks_with_errors", 0),
    }


def collect(outdir: Path) -> list[dict]:
    rows = [summarize_run(p) for p in sorted(Path(outdir).glob("*/summary_*.json"))]
    return sorted(rows, key=lambda r: (r["suite"], r["attack"], r["policy"], r["k"]))


def _fmt(value):
    if value is None:
        return "-"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def to_markdown(rows) -> str:
    out = []
    for suite in sorted({r["suite"] for r in rows}):
        out += [f"### {suite}", "", "| " + " | ".join(COLUMNS[1:]) + " |", "|" + "---|" * (len(COLUMNS) - 1)]
        out += ["| " + " | ".join(_fmt(r[c]) for c in COLUMNS[1:]) + " |" for r in rows if r["suite"] == suite]
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="results/p6_live")
    args = ap.parse_args(argv)
    rows = collect(Path(args.outdir))
    if not rows:
        print(f"no runner summaries under {args.outdir}")
        return 1
    out = Path(args.outdir)
    with (out / "p6_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    (out / "p6_summary.md").write_text(to_markdown(rows))
    print(to_markdown(rows))
    print(f"saved {out / 'p6_summary.csv'} and {out / 'p6_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
