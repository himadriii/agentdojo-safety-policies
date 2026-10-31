"""Per-strategy API cost breakdown (tokens, optionally dollars) by component, from the held-out summaries.

Usage (from the repo root):
    python scripts/report_cost.py                          # k=10 table, writes report_out/heldout/
    python scripts/report_cost.py --k 5 10 15              # several tables
    python scripts/report_cost.py --price-in 0.05 --price-out 0.20    # add USD columns (USD per 1M tokens, same price for every component)

Components (from each summary's token_usage):
    agent     the agent LLM executing the user's task (baseline cost; every strategy pays it)
    policy    LLM calls made by the approval policy itself (e.g. provenance extraction); 0 for rule-only policies
    reviewer  the simulated human reviewer, called on escalation
"Added" = policy + reviewer = what the strategy adds on top of running the agent. Totals cover every task in the
selected suites, attack and benign runs together. They do not include the plain injection-task runs AgentDojo
performs before the attack runs, so absolute totals are a little below the true spend.

Outputs (in --out):
    cost_by_k.csv                 policy, k, calls / input / output tokens per component, added tokens, per-task added tokens
    cost_k<k>.md                  table for each requested k
    cost_stacked_k<k>.png         stacked bars (agent / policy / reviewer tokens) per policy
    cost_added_vs_k.png           added tokens (policy + reviewer) against k, one line per policy
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tcr_table import load_runs  # noqa: E402

COMPONENTS = ("agent", "policy", "reviewer")
ORDER_FIRST = ["full_approve", "full_escalate"]


def aggregate(folders: list[str], split: str, suites: list[str] | None) -> list[dict]:
    runs = load_runs(folders, suites=suites, split=split)
    rows = []
    for name, r in runs.items():
        tok = {c: {"calls": 0, "in": 0, "out": 0} for c in COMPONENTS}
        n_tasks = 0
        for s in r["attack"] + r["benign"]:
            n_tasks += len(s["rows"])
            for comp, t in (s.get("token_usage") or {}).items():
                if comp in tok:
                    tok[comp]["calls"] += t.get("calls", 0)
                    tok[comp]["in"] += t.get("input_tokens", 0)
                    tok[comp]["out"] += t.get("output_tokens", 0)
        total = {c: tok[c]["in"] + tok[c]["out"] for c in COMPONENTS}
        added = total["policy"] + total["reviewer"]
        rows.append({"policy": r["policy"], "k": r["k"], "n_tasks": n_tasks, "tok": tok, "total": total,
                     "added": added, "added_per_task": added / n_tasks if n_tasks else 0.0,
                     "added_pct_of_agent": 100 * added / total["agent"] if total["agent"] else 0.0})
    if not rows:
        sys.exit("no summaries found (check --split / --suites)")
    return sorted(rows, key=lambda x: (x["k"], x["policy"]))


def policy_order(rows: list[dict]) -> list[str]:
    pols = sorted({r["policy"] for r in rows})
    return [p for p in ORDER_FIRST if p in pols] + [p for p in pols if p not in ORDER_FIRST]


def usd(tokens_in: int, tokens_out: int, p_in: float, p_out: float) -> float:
    return (tokens_in * p_in + tokens_out * p_out) / 1e6


def write_csv(rows: list[dict], path: Path) -> None:
    head = ["policy", "k", "n_tasks"]
    for c in COMPONENTS:
        head += [f"{c}_calls", f"{c}_input_tokens", f"{c}_output_tokens"]
    head += ["added_tokens", "added_tokens_per_task", "added_pct_of_agent"]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        for r in rows:
            line = [r["policy"], r["k"], r["n_tasks"]]
            for c in COMPONENTS:
                line += [r["tok"][c]["calls"], r["tok"][c]["in"], r["tok"][c]["out"]]
            w.writerow(line + [r["added"], round(r["added_per_task"], 1), round(r["added_pct_of_agent"], 1)])


def md_table(rows: list[dict], k: int, p_in: float | None, p_out: float | None) -> str:
    sel = {r["policy"]: r for r in rows if r["k"] == k or (r["policy"] == "full_approve" and r["k"] == 0)}
    head = ["policy", "agent tokens", "policy tokens", "reviewer tokens", "added (policy + reviewer)", "added / task",
            "added vs agent", "policy calls", "reviewer calls"]
    if p_in is not None:
        head += ["added USD", "total USD"]
    lines = [f"**API cost by component, held-out, k={k}** (input + output tokens; {next(iter(sel.values()))['n_tasks']} tasks per policy)",
             "", "| " + " | ".join(head) + " |", "|---|" + "---:|" * (len(head) - 1)]
    for p in policy_order(list(sel.values())):
        r = sel[p]
        cells = [p, f"{r['total']['agent']:,}", f"{r['total']['policy']:,}", f"{r['total']['reviewer']:,}", f"{r['added']:,}",
                 f"{r['added_per_task']:,.0f}", f"{r['added_pct_of_agent']:.0f}%", f"{r['tok']['policy']['calls']:,}",
                 f"{r['tok']['reviewer']['calls']:,}"]
        if p_in is not None:
            add_usd = sum(usd(r["tok"][c]["in"], r["tok"][c]["out"], p_in, p_out) for c in ("policy", "reviewer"))
            all_usd = add_usd + usd(r["tok"]["agent"]["in"], r["tok"]["agent"]["out"], p_in, p_out)
            cells += [f"${add_usd:.4f}", f"${all_usd:.4f}"]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def plot_stacked(rows: list[dict], k: int, out: Path, plt) -> None:
    sel = {r["policy"]: r for r in rows if r["k"] == k or (r["policy"] == "full_approve" and r["k"] == 0)}
    pols = policy_order(list(sel.values()))
    fig, ax = plt.subplots(figsize=(9, 5))
    bottom = [0.0] * len(pols)
    colors = {"agent": "#9aa5b1", "policy": "tab:blue", "reviewer": "tab:orange"}
    for c in COMPONENTS:
        vals = [sel[p]["total"][c] / 1000 for p in pols]
        ax.bar(range(len(pols)), vals, bottom=bottom, label=c, color=colors[c])
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_xticks(range(len(pols)))
    ax.set_xticklabels([p.replace("_", "\n") for p in pols], fontsize=7)
    ax.set_ylabel("tokens (thousands, input + output)")
    ax.set_title(f"Held-out API cost by component, k={k}")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / f"cost_stacked_k{k}.png", dpi=200)
    plt.close(fig)


def plot_added_vs_k(rows: list[dict], out: Path, plt) -> None:
    by = defaultdict(dict)
    for r in rows:
        by[r["policy"]][r["k"]] = r["added"] / 1000
    ks = sorted({r["k"] for r in rows})
    fig, ax = plt.subplots(figsize=(8, 5))
    cmap = plt.get_cmap("tab10")
    for i, p in enumerate(policy_order(rows)):
        if p == "full_approve":
            ax.plot(ks, [0] * len(ks), color="dimgray", ls="--", lw=2, label="full-approve (no added cost)")
            continue
        xs = [k for k in ks if k in by[p]]
        ax.plot(xs, [by[p][k] for k in xs], marker="o", ms=4, lw=2.2 if p == "full_escalate" else 1.3,
                color="black" if p == "full_escalate" else cmap(i % 10), label=p)
    ax.set_xticks(ks)
    ax.set_xlabel("escalation budget k")
    ax.set_ylabel("added tokens (policy + reviewer), thousands")
    ax.set_title("Held-out added API cost vs k")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(out / "cost_added_vs_k.png", dpi=200)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="*", help="default: every submitted_results/<split>/ALL/k* folder")
    ap.add_argument("--split", default="heldout", choices=["dev", "heldout"])
    ap.add_argument("--suites", nargs="+", default=["banking", "slack", "travel", "workspace"])
    ap.add_argument("--k", nargs="+", type=int, default=[10], help="k value(s) for the tables and bar charts")
    ap.add_argument("--price-in", type=float, default=None, help="USD per 1M input tokens (adds USD columns)")
    ap.add_argument("--price-out", type=float, default=None, help="USD per 1M output tokens")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args(argv)
    if (args.price_in is None) != (args.price_out is None):
        sys.exit("give both --price-in and --price-out, or neither")

    folders = args.folders or sorted(str(p) for p in Path(f"submitted_results/{args.split}/ALL").glob("k*") if p.is_dir())
    rows = aggregate(folders, args.split, args.suites)
    out = Path(args.out or f"report_out/{args.split}")
    out.mkdir(parents=True, exist_ok=True)
    write_csv(rows, out / "cost_by_k.csv")
    for k in args.k:
        text = md_table(rows, k, args.price_in, args.price_out)
        (out / f"cost_k{k}.md").write_text(text)
        print(text)
    if not args.no_plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        for k in args.k:
            plot_stacked(rows, k, out, plt)
        plot_added_vs_k(rows, out, plt)
    print(f"wrote cost files to {out}/")


if __name__ == "__main__":
    main()
