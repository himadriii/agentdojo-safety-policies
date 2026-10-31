"""Escalation-value analysis: which kinds of tool calls benefit from human escalation and which can be auto-approved.

Usage (from the repo root):
    python scripts/report_escalation_value.py                 # held-out, all four suites, writes report_out/heldout/
    python scripts/report_escalation_value.py --k 10          # which k the per-policy table uses (default 10)

Every tool call is put in one of four classes using agent_framework/tool_meta.py:
    read_only             get_/search_/list_/read_ ... (no state change)
    internal_reversible   writes that stay inside the user's own data and can be undone (create_file, append_to_file, ...)
    internal_irreversible deletions inside the user's own data
    external_effect       reaches someone else, moves money or publishes (send_money, send_email, share_file, post_webpage, ...)

A call is "attacker's" with the same heuristic as report_failures.py (a string argument of 5+ characters appears in the injected
text and not in the user's request); every other call is "safe". It is a heuristic, so read the counts as estimates.

Tables written to escalation_value.md and escalation_value_<k>.csv:
  1. Call mix: how many calls of each class the unconstrained agent (Full-Approve) makes, and how many are the attacker's.
  2. What the reviewer does when every call is escalated (Full-Escalate, k >= 2): per class, how many attacker calls it blocks,
     how many it lets through, and how many safe calls it wrongly denies.
  3. Per-policy handling of each class at the chosen k: share auto-approved, escalated, and denied, plus attacker calls
     auto-approved (misses) and safe calls blocked (utility cost).
"""
import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from report_failures import load, policy_order  # noqa: E402

from agent_framework.tool_meta import get_tool_meta  # noqa: E402

CLASSES = ("read_only", "internal_reversible", "internal_irreversible", "external_effect")
ESCALATED = ("escalate_approved", "escalate_denied")
APPROVED = ("auto_approve", "escalate_approved")
DENIED = ("auto_deny", "escalate_denied", "budget_exhausted_deny")


def tool_class(name: str) -> str:
    m = get_tool_meta(name)
    if m["read_only"]:
        return "read_only"
    if m["external_side_effect"]:
        return "external_effect"
    return "internal_irreversible" if m["irreversible"] else "internal_reversible"


def calls_of(recs: list[dict]):
    for r in recs:
        for g in r["calls"]:
            yield g


def pct(a: int, b: int) -> str:
    return "-" if b == 0 else f"{100 * a / b:.0f}%"


def call_mix(data: dict) -> tuple[list[str], list[list]]:
    recs = [r for (p, k), rs in data.items() if p == "full_approve" for r in rs]
    c = {cl: Counter() for cl in CLASSES}
    tools = {cl: Counter() for cl in CLASSES}
    for g in calls_of(recs):
        cl = tool_class(g["tool"])
        c[cl]["calls"] += 1
        c[cl]["attacker" if g["unsafe"] else "safe"] += 1
        if g["unsafe"]:
            tools[cl][g["tool"]] += 1
    head = ["class", "calls", "safe", "attacker's", "attacker share of class", "attacker tools (count)"]
    rows = [[cl, c[cl]["calls"], c[cl]["safe"], c[cl]["attacker"], pct(c[cl]["attacker"], c[cl]["calls"]),
             ", ".join(f"{t} {n}" for t, n in tools[cl].most_common(4)) or "-"] for cl in CLASSES]
    return head, rows


def reviewer_value(data: dict) -> tuple[list[str], list[list]]:
    recs = [r for (p, k), rs in data.items() if p == "full_escalate" and k >= 2 for r in rs]
    c = {cl: Counter() for cl in CLASSES}
    for g in calls_of(recs):
        if g["outcome"] not in ESCALATED:
            continue
        cl = tool_class(g["tool"])
        approved = g["outcome"] == "escalate_approved"
        key = ("att_" if g["unsafe"] else "safe_") + ("approved" if approved else "denied")
        c[cl][key] += 1
    head = ["class", "escalated", "attacker blocked", "attacker let through", "block rate", "safe approved", "safe wrongly denied",
            "false-deny rate"]
    rows = []
    for cl in CLASSES:
        x = c[cl]
        att, safe = x["att_denied"] + x["att_approved"], x["safe_approved"] + x["safe_denied"]
        rows.append([cl, att + safe, x["att_denied"], x["att_approved"], pct(x["att_denied"], att), x["safe_approved"],
                     x["safe_denied"], pct(x["safe_denied"], safe)])
    return head, rows


def per_policy(data: dict, k: int) -> tuple[list[str], list[list]]:
    head = ["policy", "class", "calls", "auto-approved", "escalated", "denied without reviewer", "attacker auto-approved (miss)", "safe calls blocked"]
    rows = []
    sel = {p: rs for (p, kk), rs in data.items() if kk == k and p != "full_approve"}
    for p in policy_order(list(sel)):
        c = {cl: Counter() for cl in CLASSES}
        for g in calls_of(sel[p]):
            cl = tool_class(g["tool"])
            c[cl]["calls"] += 1
            c[cl]["auto"] += g["outcome"] == "auto_approve"
            c[cl]["esc"] += g["outcome"] in ESCALATED or g["outcome"] == "budget_exhausted_deny"
            c[cl]["den"] += g["outcome"] in ("auto_deny", "budget_exhausted_deny")
            c[cl]["miss"] += g["outcome"] == "auto_approve" and g["unsafe"]
            c[cl]["safe_blocked"] += g["outcome"] in DENIED and not g["unsafe"]
        for cl in CLASSES:
            x = c[cl]
            rows.append([p, cl, x["calls"], f"{x['auto']} ({pct(x['auto'], x['calls'])})",
                         f"{x['esc']} ({pct(x['esc'], x['calls'])})", f"{x['den']} ({pct(x['den'], x['calls'])})",
                         x["miss"], x["safe_blocked"]])
    return head, rows


def md(title: str, head: list[str], rows: list[list]) -> str:
    lines = [f"**{title}**", "", "| " + " | ".join(head) + " |", "|---|" + "---:|" * (len(head) - 1)]
    lines += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="*", help="default: every submitted_results/<split>/ALL/k* folder")
    ap.add_argument("--split", default="heldout", choices=["dev", "heldout"])
    ap.add_argument("--suites", nargs="+", default=["banking", "slack", "travel", "workspace"])
    ap.add_argument("--k", type=int, default=10, help="k for the per-policy table")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    folders = args.folders or sorted(str(p) for p in Path(f"submitted_results/{args.split}/ALL").glob("k*") if p.is_dir())
    data = load(folders, args.split, args.suites)
    out = Path(args.out or f"report_out/{args.split}")
    out.mkdir(parents=True, exist_ok=True)

    t1, t2, t3 = call_mix(data), reviewer_value(data), per_policy(data, args.k)
    text = "\n".join([
        md("1. Call mix of the unconstrained agent (Full-Approve, all executed calls)", *t1),
        md("2. Reviewer decisions when every call is escalated (Full-Escalate, k >= 2)", *t2),
        md(f"3. How each policy handles each class (k={args.k})", *t3)])
    (out / "escalation_value.md").write_text(text)
    with (out / f"escalation_value_k{args.k}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(t3[0])
        w.writerows(t3[1])
    print(text)
    print(f"wrote {out}/escalation_value.md")


if __name__ == "__main__":
    main()
