"""Pooled TCR table: attack runs + benign (no-attack) runs, per policy and k, summed over suites.

Usage:  python scripts/tcr_table.py results/dev/ALL [results/dev/P1 ...] [--csv out.csv]
        [--html out.html]
        [--suites banking slack travel | --exclude-suites workspace] [--split heldout] [--by-suite]

Each run folder holds summary_<suite>_<attack>.json (attack runs) and summary_<suite>_none.json (benign runs).
  TCR_attack = completed-safely / n over user x injection pairs (as before)
  TCR_benign = completed / n over the same user tasks with no attack
  TCR_pooled = all completed-safely / all tasks (attack pairs + benign tasks)
HITL load = escalations summed over the tasks that were completed safely (as defined in the brief); pooled adds both.
"""
import argparse
import csv
import html
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_runs(folders, suites=None, exclude_suites=None, split=None, by_suite=False):
    """{run_identity: {"run","policy","k","reviewer","suite","attack": [summaries], "benign": [summaries]}} from every summary file under the folders.

    suites / exclude_suites filter on the summary's "suite"; split filters on its "split" (dev / heldout).
    Runs with the same model/policy/reviewer/k identity are pooled even when their
    suites are stored in separate folders (for example, a ``-workspace`` folder).
    The public run label is the policy name rather than the storage-folder name.
    by_suite=True keeps one row per (run identity, suite) instead of pooling suites.
    A (run folder, suite, attack) seen twice (the same run copied into two folders) is counted once.
    """
    runs, seen = {}, set()
    for root in folders:
        for path in sorted(Path(root).rglob("summary_*.json")):
            s = json.loads(path.read_text())
            suite = s.get("suite", "?")
            if (suites and suite not in suites) or (exclude_suites and suite in exclude_suites):
                continue
            if split and s.get("split") != split:
                continue
            key = (path.parent.name, suite, s["attack"])
            if key in seen:
                print(f"warning: duplicate summary skipped: {path}", file=sys.stderr)
                continue
            seen.add(key)
            identity = (s.get("provider"), s.get("llm"), s["policy"], s["reviewer"],
                        s.get("reviewer_model"), s["k"])
            group = identity + ((suite,) if by_suite else ())
            label = f"{s['policy']} [{suite}]" if by_suite else s["policy"]
            run = runs.setdefault(group, {"run": label, "policy": s["policy"], "k": s["k"],
                                          "reviewer": s["reviewer"],
                                          "suite": suite if by_suite else "pooled",
                                          "attack": [], "benign": []})
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
    for r in runs.values():
        na, da, ha, hall_a, tok_a = _count(r["attack"])
        nb, db, hb, hall_b, tok_b = _count(r["benign"])
        tok = defaultdict(lambda: [0, 0, 0])
        for t in (tok_a, tok_b):
            for comp, v in t.items():
                for i in range(3):
                    tok[comp][i] += v[i]
        rows.append({
            "run": r["run"], "suite": r["suite"], "policy": r["policy"], "reviewer": r["reviewer"], "k": r["k"],
            "n_attack": na, "tcr_attack": da / na if na else None,
            "n_benign": nb, "tcr_benign": db / nb if nb else None,
            "n_pooled": na + nb, "tcr_pooled": (da + db) / (na + nb) if na + nb else None,
            "hitl_completed_pooled": ha + hb, "hitl_all_pooled": hall_a + hall_b,
            "agent_tokens": sum(tok["agent"][1:]), "policy_tokens": sum(tok["policy"][1:]), "reviewer_tokens": sum(tok["reviewer"][1:]),
        })
    return sorted(rows, key=lambda x: (x["policy"], x["k"], x["run"]))


def _f(x):
    return "  -  " if x is None else f"{x:.3f}"


def write_html(rows, output):
    """Write a standalone, copy-friendly HTML table."""
    columns = [
        ("policy", "Policy"), ("k", "k"), ("suite", "Suite"), ("reviewer", "Reviewer"),
        ("n_attack", "Attack n"), ("tcr_attack", "Attack TCR"),
        ("n_benign", "Benign n"), ("tcr_benign", "Benign TCR"),
        ("n_pooled", "Pooled n"), ("tcr_pooled", "Pooled TCR"),
        ("hitl_completed_pooled", "HITL (completed)"), ("hitl_all_pooled", "HITL (all)"),
        ("agent_tokens", "Agent tokens"), ("policy_tokens", "Policy tokens"),
        ("reviewer_tokens", "Reviewer tokens"),
    ]

    def cell(value, key):
        if key.startswith("tcr_"):
            value = "-" if value is None else f"{value:.3f}"
        return html.escape(str(value))

    header = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = "\n".join(
        "<tr>" + "".join(f"<td>{cell(row[key], key)}</td>" for key, _ in columns) + "</tr>"
        for row in rows
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TCR summary</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; }}
table {{ border-collapse: collapse; font-size: 10pt; }}
th, td {{ border: 1px solid #9aa0a6; padding: 5px 8px; text-align: right; white-space: nowrap; }}
th {{ background: #e8f0fe; font-weight: 700; }}
th:first-child, td:first-child, th:nth-child(3), td:nth-child(3), th:nth-child(4), td:nth-child(4) {{ text-align: left; }}
tbody tr:nth-child(even) {{ background: #f8f9fa; }}
</style>
</head>
<body>
<table>
<thead><tr>{header}</tr></thead>
<tbody>
{body}
</tbody>
</table>
</body>
</html>
"""
    Path(output).write_text(document, encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--csv")
    ap.add_argument("--html", help="write a standalone HTML table for browser/Google Docs copy-paste")
    ap.add_argument("--suites", nargs="+", help="only these suites, e.g. banking slack travel")
    ap.add_argument("--exclude-suites", nargs="+", help="drop these suites, e.g. workspace")
    ap.add_argument("--split", choices=["dev", "heldout"], help="only summaries of this split")
    ap.add_argument("--by-suite", action="store_true", help="one row per policy, k and suite instead of pooling suites")
    args = ap.parse_args(argv)
    rows = table(load_runs(args.folders, args.suites, args.exclude_suites, args.split, args.by_suite))
    print(f"{'policy':26s} {'k':>3s} | {'nA':>3s} {'TCR_att':>7s} | {'nB':>3s} {'TCR_ben':>7s} | {'n':>3s} {'TCR_pool':>8s} | {'HITL':>5s} | tokens agent/policy/reviewer")
    for r in rows:
        print(f"{r['policy'] + ('/' + r['suite'] if args.by_suite else ''):26s} {r['k']:>3d} | {r['n_attack']:>3d} {_f(r['tcr_attack']):>7s} | {r['n_benign']:>3d} {_f(r['tcr_benign']):>7s} | "
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
    if args.html:
        write_html(rows, args.html)
        print(f"saved {args.html}")
    return rows


if __name__ == "__main__":
    main()
