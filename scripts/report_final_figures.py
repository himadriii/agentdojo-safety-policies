"""Final-report figures with the display name "RPP Gate" (Reuse-Aware Plan-or-Provenance Gate = p4_p6_p7_combined_or).

Usage (from the repo root, after report_tcr_hitl.py / report_cost.py / report_failures.py have written report_out/heldout/*.csv):
    python scripts/report_final_figures.py                 # writes report_out/heldout/final/
    python scripts/report_final_figures.py --dir report_out/heldout --out report_out/heldout/final

Figures:
    fig_rpp_tcr.png        RPP Gate vs both baselines (attack / benign / pooled, Wilson 95% bands)
    fig_pooled_tcr_compact.png    small version of the same figure for side-by-side layout
    fig_pooled_tcr_selected.png   pooled TCR@k at every k for the shortlisted policies + baselines (+ tcr_pooled_selected.csv)
    fig_hitl_vs_k.png      escalations vs k (all, and on safely completed tasks)
    fig_failures_k10.png   failure classes at k=10
    fig_cost_stacked_k10.png, fig_cost_added_vs_k.png   token cost by component
    fig_escalation_value.png  call mix and Full-Escalate reviewer outcomes per tool class (numbers from escalation_value.md)
The supervised variant that is shown is the better of supervised_risk / supervised_risk_urlguard by mean pooled TCR over k >= 2
(ties broken by total escalations, then mean added tokens).
"""
import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

NAME = {"p4_p6_p7_combined_or": "RPP Gate", "full_approve": "Full-Approve", "full_escalate": "Full-Escalate"}
COLOR = {"p4_p6_p7_combined_or": "#1f77b4", "provenance": "#9467bd", "plan_consistency": "#d62728",
         "approval_reuse": "#ff7f0e", "anomaly": "#2ca02c", "supervised_risk": "#8c564b",
         "supervised_risk_urlguard": "#8c564b", "full_escalate": "black", "full_approve": "dimgray",
         "similarity_reuse": "#e377c2"}
KS = (0, 2, 5, 7, 10, 15)


def nm(p: str) -> str:
    return NAME.get(p, p)


def read(path: Path) -> list[dict]:
    with path.open() as f:
        return list(csv.DictReader(f))


def wilson(x: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def series(T: list[dict], p: str, col: str) -> dict[int, float]:
    return {int(r["k"]): float(r[col]) for r in T if r["policy"] == p}


def pick_supervised(T: list[dict], C: list[dict]) -> str:
    def key(p):
        t = [float(r["tcr_pooled"]) for r in T if r["policy"] == p and int(r["k"]) >= 2]
        h = sum(int(r["hitl_all"]) for r in T if r["policy"] == p and int(r["k"]) >= 2)
        c = [int(r["added_tokens"]) for r in C if r["policy"] == p and int(r["k"]) >= 2]
        return (round(sum(t) / len(t), 3), -h, -sum(c) / len(c))
    return max(("supervised_risk", "supervised_risk_urlguard"), key=key)


def fig_rpp(T, out):
    pol = "p4_p6_p7_combined_or"
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
    for ax, (title, tcol, ncol) in zip(axes, [("attack", "tcr_attack", "n_attack"), ("benign", "tcr_benign", "n_benign"),
                                              ("pooled", "tcr_pooled", "n_pooled")]):
        fa = series(T, "full_approve", tcol)[0]
        ax.plot(KS, [fa] * len(KS), color="dimgray", ls="--", lw=2, label="Full-Approve")
        fe = series(T, "full_escalate", tcol)
        ax.plot(list(fe), list(fe.values()), color="black", marker="s", lw=2, label="Full-Escalate")
        rows = sorted((r for r in T if r["policy"] == pol), key=lambda r: int(r["k"]))
        ks = [int(r["k"]) for r in rows]
        ys = [float(r[tcol]) for r in rows]
        bands = [wilson(round(y * int(r[ncol])), int(r[ncol])) for y, r in zip(ys, rows)]
        ax.fill_between(ks, [b[0] for b in bands], [b[1] for b in bands], color=COLOR[pol], alpha=0.15)
        ax.plot(ks, ys, color=COLOR[pol], marker="o", lw=2.2, label="RPP Gate")
        ax.set_title(title)
        ax.set_xticks(KS)
        ax.set_xlabel("escalation budget k")
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("TCR")
    axes[0].legend(fontsize=8, loc="upper right")
    fig.suptitle("Test-set TCR@k: RPP Gate vs both baselines (band = 95% Wilson interval)")
    fig.tight_layout()
    fig.savefig(out / "fig_rpp_tcr.png", dpi=200)
    plt.close(fig)


def fig_pooled(T, sup, out):
    pols = ["anomaly", "plan_consistency", "provenance", "approval_reuse", "p4_p6_p7_combined_or", sup]
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    fa = series(T, "full_approve", "tcr_pooled")[0]
    ax.plot(KS, [fa] * len(KS), color="dimgray", ls="--", lw=2.2, label="Full-Approve (k-independent)")
    fe = series(T, "full_escalate", "tcr_pooled")
    ax.plot(list(fe), list(fe.values()), color="black", marker="s", lw=2.6, label="Full-Escalate")
    for p in pols:
        s = series(T, p, "tcr_pooled")
        rpp = p == "p4_p6_p7_combined_or"
        ax.plot(list(s), list(s.values()), marker="o", ms=5 if rpp else 4, lw=3 if rpp else 1.6, color=COLOR[p], label=nm(p))
    ax.set_xticks(KS)
    ax.set_xlabel("escalation budget k")
    ax.set_ylabel("pooled TCR (n=98)")
    ax.set_ylim(0, 0.8)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=2, loc="lower right")
    ax.set_title("Test-set pooled TCR@k, shortlisted policies and baselines")
    fig.tight_layout()
    fig.savefig(out / "fig_pooled_tcr_selected.png", dpi=200)
    plt.close(fig)
    order = ["full_approve", "full_escalate"] + pols
    with (out / "tcr_pooled_selected.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["policy"] + [f"k{k}" for k in KS] + ["mean_k>=2"])
        for p in order:
            s = series(T, p, "tcr_pooled")
            vals = [s.get(0 if p == "full_approve" else k) for k in KS]
            m = sum(v for k, v in zip(KS, vals) if k >= 2) / 5
            w.writerow([nm(p)] + [f"{v:.3f}" for v in vals] + [f"{m:.3f}"])


def fig_pooled_compact(T, sup, out):
    pols = ["anomaly", "plan_consistency", "provenance", "approval_reuse", "p4_p6_p7_combined_or", sup]
    fig, ax = plt.subplots(figsize=(4.6, 4.2))
    fa = series(T, "full_approve", "tcr_pooled")[0]
    ax.plot(KS, [fa] * len(KS), color="dimgray", ls="--", lw=1.8, label="Full-Approve")
    fe = series(T, "full_escalate", "tcr_pooled")
    ax.plot(list(fe), list(fe.values()), color="black", marker="s", ms=4, lw=2, label="Full-Escalate")
    for p in pols:
        s = series(T, p, "tcr_pooled")
        rpp = p == "p4_p6_p7_combined_or"
        ax.plot(list(s), list(s.values()), marker="o", ms=3.5, lw=2.8 if rpp else 1.3, color=COLOR[p], label=nm(p))
    ax.set_xticks(KS)
    ax.set_xlabel("escalation budget k", fontsize=8)
    ax.set_ylabel("pooled TCR (n=98)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.set_ylim(0, 0.8)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=6, ncol=2, loc="lower right")
    fig.tight_layout()
    fig.savefig(out / "fig_pooled_tcr_compact.png", dpi=220)
    plt.close(fig)


def fig_all_pooled(T, out):
    pols = ["anomaly", "approval_reuse", "similarity_reuse", "plan_consistency", "supervised_risk", "supervised_risk_urlguard",
            "provenance", "p4_p6_p7_combined_or"]
    fig, ax = plt.subplots(figsize=(6.2, 4.4))
    fa = series(T, "full_approve", "tcr_pooled")[0]
    ax.plot(KS, [fa] * len(KS), color="dimgray", ls="--", lw=2, label="Full-Approve")
    fe = series(T, "full_escalate", "tcr_pooled")
    ax.plot(list(fe), list(fe.values()), color="black", marker="s", ms=4, lw=2.2, label="Full-Escalate")
    for p in pols:
        s = series(T, p, "tcr_pooled")
        rpp = p == "p4_p6_p7_combined_or"
        ls = "--" if p == "supervised_risk_urlguard" else "-"
        ax.plot(list(s), list(s.values()), marker="o", ms=4, lw=3.2 if rpp else 1.4, ls=ls, color=COLOR[p], label=nm(p))
    ax.set_xticks(KS)
    ax.set_xlabel("escalation budget k")
    ax.set_ylabel("pooled TCR (n=98)")
    ax.set_ylim(0, 0.8)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, ncol=2, loc="lower right")
    ax.set_title("Pooled TCR@k, all policies tried", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "fig_all_policies_pooled_tcr.png", dpi=220)
    plt.close(fig)


def fig_hitl(T, sup, out):
    pols = ["full_escalate", "anomaly", "plan_consistency", "approval_reuse", "provenance", "p4_p6_p7_combined_or", sup]
    ks = [k for k in KS if k > 0]
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))
    for p in pols:
        for a, col in zip(ax, ("hitl_all", "hitl_completed")):
            s = series(T, p, col)
            a.plot(ks, [s[k] for k in ks], marker="o", ms=3, color=COLOR[p], lw=1.4 if p == "full_escalate" else 2.2, label=nm(p))
    ax[0].set_title("Total escalations (98 runs)", fontsize=10)
    ax[1].set_title("Escalations on safely completed tasks", fontsize=10)
    for a in ax:
        a.set_xticks(ks)
        a.set_xlabel("budget k")
        a.grid(alpha=0.3)
    ax[0].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(out / "fig_hitl_vs_k.png", dpi=200)
    plt.close(fig)


def fig_fail(F, sup, out):
    pols = ["full_approve", "full_escalate", "anomaly", "plan_consistency", "approval_reuse", "provenance", "p4_p6_p7_combined_or", sup]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    for i, p in enumerate(pols):
        k = "0" if p == "full_approve" else "10"
        r = next(x for x in F if x["policy"] == p and x["k"] == k)
        left = 0
        for key, c, l in (("over_permissive", "#c0392b", "over-permissive"), ("over_conservative", "#e0a100", "over-conservative"),
                          ("other", "#9aa5b1", "other (agent failure)")):
            v = int(r[key])
            ax.barh(i, v, left=left, color=c, label=l if i == 0 else None)
            if v > 3:
                ax.text(left + v / 2, i, str(v), ha="center", va="center", fontsize=8)
            left += v
    ax.set_yticks(range(len(pols)))
    ax.set_yticklabels([nm(p) for p in pols], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("failed runs out of 98 (k=10; Full-Approve is k-independent)")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    fig.savefig(out / "fig_failures_k10.png", dpi=200)
    plt.close(fig)


def fig_cost(C, sup, out):
    pols = ["full_approve", "full_escalate", "p4_p6_p7_combined_or", "provenance", "plan_consistency", "approval_reuse", "anomaly", sup]
    by = {(r["policy"], int(r["k"])): r for r in C}

    def tok(r, c):
        return int(r[f"{c}_input_tokens"]) + int(r[f"{c}_output_tokens"])
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    bottom = [0.0] * len(pols)
    for c, col in (("agent", "#9aa5b1"), ("policy", "tab:blue"), ("reviewer", "tab:orange")):
        vals = [tok(by[(p, 0 if p == "full_approve" else 10)], c) / 1000 for p in pols]
        ax.bar(range(len(pols)), vals, bottom=bottom, color=col, label={"agent": "agent execution", "policy": "policy inference", "reviewer": "reviewer simulation"}[c])
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_xticks(range(len(pols)))
    ax.set_xticklabels([nm(p) for p in pols], fontsize=6.5, rotation=40, ha="right")
    ax.set_ylabel("tokens (thousands, input + output)", fontsize=8)
    ax.set_title("API cost by component, k=10", fontsize=9)
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "fig_cost_stacked_k10.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 4))
    ks = [k for k in KS if k > 0]
    for p in pols[1:]:
        ys = [int(by[(p, k)]["added_tokens"]) / 1000 for k in ks]
        ax.plot(ks, ys, marker="o", ms=4, color=COLOR[p], lw=3 if p == "p4_p6_p7_combined_or" else 1.6, label=nm(p))
    ax.set_xticks(ks)
    ax.set_xlabel("escalation budget k")
    ax.set_ylabel("added tokens (policy + reviewer), thousands")
    ax.set_title("Test-set added API cost vs k")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(out / "fig_cost_added_vs_k.png", dpi=200)
    plt.close(fig)


def fig_escval(out):
    # numbers copied from report_out/heldout/escalation_value.md (tables 1 and 2)
    cl = ["read-only", "internal\nreversible", "internal\nirreversible", "external\neffect"]
    calls, att = [213, 5, 14, 100], [19, 0, 6, 48]
    blk, let, wr = [47, 0, 29, 141], [19, 0, 0, 2], [100, 0, 0, 9]
    x = range(4)
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.3))
    ax[0].bar([i - .2 for i in x], calls, .4, color="#9aa5b1", label="all calls")
    ax[0].bar([i + .2 for i in x], att, .4, color="#c0392b", label="attacker's calls")
    ax[0].set_title("Call mix, Full-Approve", fontsize=10)
    ax[1].bar([i - .27 for i in x], blk, .27, color="#2a9d8f", label="attacker blocked")
    ax[1].bar(list(x), let, .27, color="#c0392b", label="attacker let through")
    ax[1].bar([i + .27 for i in x], wr, .27, color="#e0a100", label="safe wrongly denied")
    ax[1].set_title("Reviewer outcomes, Full-Escalate (k>=2)", fontsize=10)
    for a in ax:
        a.set_xticks(list(x))
        a.set_xticklabels(cl, fontsize=8)
        a.legend(fontsize=7)
        a.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "fig_escalation_value.png", dpi=200)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="report_out/heldout")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    d = Path(a.dir)
    out = Path(a.out or d / "final")
    out.mkdir(parents=True, exist_ok=True)
    T, C, F = read(d / "tcr_by_k.csv"), read(d / "cost_by_k.csv"), read(d / "failures_by_k.csv")
    sup = pick_supervised(T, C)
    print("supervised variant shown:", sup)
    fig_rpp(T, out)
    fig_pooled(T, sup, out)
    fig_pooled_compact(T, sup, out)
    fig_all_pooled(T, out)
    fig_hitl(T, sup, out)
    fig_fail(F, sup, out)
    fig_cost(C, sup, out)
    fig_escval(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
