"""Rebuild runner-format summary_*.json files from the per-task trace JSONs.

Why: the runner writes one summary per invocation and overwrites the previous one. When a suite
is run pair by pair (to survive a server error on one pair), the summary only describes the last
pair. This script recomputes it from every finished trace, with the runner's own definitions
(agent_framework/runner.py, run_one): a pair counts only if AgentDojo recorded a result for it,
and AgentDojo's baseline runs of injection tasks as plain user tasks are excluded.

Usage:  python -m p3_risk.summarize_traces results/dev/sahana [--check]
  --check  compare with the existing summaries instead of overwriting them
"""
import argparse
import glob
import json
import os
import re

COUNT_KEYS = ("calls", "input_tokens", "output_tokens")


def build(pipeline_dir, suite, attack):
    rows, tokens = {}, {}
    for path in sorted(glob.glob(os.path.join(pipeline_dir, suite, "user_task_*", attack, "*.json"))):
        t = json.load(open(path))
        if "utility" not in t or not t.get("injection_task_id"):
            continue  # unfinished trace, or a no-attack run
        d = t.get("approval_decisions", [])
        attack_succeeded = bool(t["security"])
        rows[f"{t['user_task_id']}|{t['injection_task_id']}"] = {
            "utility": bool(t["utility"]),
            "attack_succeeded": attack_succeeded,
            "completed_safely": bool(t["utility"]) and not attack_succeeded,
            "escalations": sum(x["reviewer_called"] for x in d),
            "budget_exhausted_denials": sum(x["outcome"] == "budget_exhausted_deny" for x in d),
            "auto_denials": sum(x["outcome"] == "auto_deny" for x in d),
            "executed_calls": sum(x["executed"] for x in d),
            "error": t.get("error"),
        }
        for comp, u in (t.get("token_usage") or {}).items():
            agg = tokens.setdefault(comp, {k: 0 for k in COUNT_KEYS})
            for k in COUNT_KEYS:
                agg[k] += u.get(k, 0)
    return rows, tokens


def summarize(pipeline_dir, suite, attack, template):
    rows, tokens = build(pipeline_dir, suite, attack)
    n = max(len(rows), 1)
    s = dict(template)
    s.update({
        "n": len(rows),
        "tcr": sum(r["completed_safely"] for r in rows.values()) / n,
        "hitl_load_completed": sum(r["escalations"] for r in rows.values() if r["completed_safely"]),
        "hitl_load_all": sum(r["escalations"] for r in rows.values()),
        "tasks_with_errors": sum(r["error"] is not None for r in rows.values()),
        "token_usage": tokens,
        "rows": rows,
    })
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    for pdir in sorted(glob.glob(os.path.join(args.outdir, "*", ""))):
        pdir = pdir.rstrip("/\\")
        for old in sorted(glob.glob(os.path.join(pdir, "summary_*.json"))):
            m = re.match(r"summary_(.+?)_(.+)\.json$", os.path.basename(old))
            suite, attack = m.group(1), m.group(2)
            if attack == "none":
                continue
            template = {k: v for k, v in json.load(open(old)).items() if k not in ("rows",)}
            new = summarize(pdir, suite, attack, template)
            if args.check:
                prev = json.load(open(old))
                same = all(prev.get(k) == new[k] for k in ("n", "tcr", "hitl_load_completed", "hitl_load_all", "tasks_with_errors", "rows"))
                print(f"{os.path.basename(pdir)[-30:]} {suite:8s} runner n={prev['n']:2d} rebuilt n={new['n']:2d} identical={same}")
            else:
                json.dump(new, open(old, "w"), indent=2)
                print(f"rebuilt {suite:8s} {os.path.basename(pdir)[-30:]}  n={new['n']} tcr={new['tcr']:.3f}")


if __name__ == "__main__":
    main()
