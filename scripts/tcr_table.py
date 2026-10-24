"""Pooled TCR table: attack runs + benign (no-attack) runs, per policy and k, summed over suites.

Usage:  python scripts/tcr_table.py results/dev/ALL [results/dev/P1 ...] [--csv out.csv]

Each run folder holds summary_<suite>_<attack>.json (attack runs) and summary_<suite>_none.json (benign runs).
  TCR_attack = completed-safely / n over user x injection pairs (as before)
  TCR_benign = completed / n over the same user tasks with no attack
  TCR_pooled = all completed-safely / all tasks (attack pairs + benign tasks)
HITL load = escalations summed over the tasks that were completed safely (as defined in the brief); pooled adds both.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_runs(folders):
    """{run_name: {"policy","k","reviewer","attack": [summaries], "benign": [summaries]}} from every summary file under the folders."""
    runs = {}
    for root in folders:
        for path in sorted(Path(root).rglob("summary_*.json")):
            s = json.loads(path.read_text())
            name = path.parent.name
            run = runs.setdefault(name, {"policy": s["policy"], "k": s["k"], "reviewer": s["reviewer"], "attack": [], "benign": []})
            run["benign" if s["attack"] == "none" else "attack"].append(s)
    return runs


def _count(summaries):
    n = done = hitl_done = hitl_all = 0
    tok = defaultdict(lambda: [0, 0, 0])
    for s in summaries:
        rows = s["rows"].values()
        n += len(rows)
        done += sum(r["completed_safely"] for r in rows)
        hitl_done += s["hitl_load_completed"]
        hitl_all += s["hitl_load_all"]
        for comp, t in (s.get("token_usage") or {}).items():
            tok[comp][0] += t.get("calls", 0)
            tok[comp][1] += t.get("input_tokens", 0)
            tok[comp][2] += t.get("output_tokens", 0)
    return n, done, hitl_done, hitl_all, tok


def table(runs):
    rows = []
    for name, r in runs.items():
        na, da, ha, hall_a, tok_a = _count(r["attack"])
        nb, db, hb, hall_b, tok_b = _count(r["benign"])
        tok = defaultdict(lambda: [0, 0, 0])
        for t in (tok_a, tok_b):
            for comp, v in t.items():
                for i in range(3):
                    tok[comp][i] += v[i]
        rows.append({
            "run": name, "policy": r["policy"], "reviewer": r["reviewer"], "k": r["k"],
            "n_attack": na, "tcr_attack": da / na if na else None,
            "n_benign": nb, "tcr_benign": db / nb if nb else None,
            "n_pooled": na + nb, "tcr_pooled": (da + db) / (na + nb) if na + nb else None,
            "hitl_completed_pooled": ha + hb, "hitl_all_pooled": hall_a + hall_b,
            "agent_tokens": sum(tok["agent"][1:]), "policy_tokens": sum(tok["policy"][1:]), "reviewer_tokens": sum(tok["reviewer"][1:]),
        })
    return sorted(rows, key=lambda x: (x["policy"], x["k"], x["run"]))


def _f(x):
    return "  -  " if x is None else f"{x:.3f}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--csv")
    args = ap.parse_args(argv)
    rows = table(load_runs(args.folders))
    print(f"{'policy':26s} {'k':>3s} | {'nA':>3s} {'TCR_att':>7s} | {'nB':>3s} {'TCR_ben':>7s} | {'n':>3s} {'TCR_pool':>8s} | {'HITL':>5s} | tokens agent/policy/reviewer")
    for r in rows:
        print(f"{r['policy']:26s} {r['k']:>3d} | {r['n_attack']:>3d} {_f(r['tcr_attack']):>7s} | {r['n_benign']:>3d} {_f(r['tcr_benign']):>7s} | "
              f"{r['n_pooled']:>3d} {_f(r['tcr_pooled']):>8s} | {r['hitl_completed_pooled']:>5d} | {r['agent_tokens']}/{r['policy_tokens']}/{r['reviewer_tokens']}")
    if any(r["n_benign"] == 0 for r in rows):
        print("\nnote: runs with nB=0 have no benign (no-attack) results yet; their pooled TCR equals the attack TCR. "
              "Run them with --with-benign (BENIGN=1).", file=sys.stderr)
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])) if rows else None
            if w:
                w.writeheader()
                w.writerows(rows)
        print(f"saved {args.csv}")
    return rows


if __name__ == "__main__":
    main()
