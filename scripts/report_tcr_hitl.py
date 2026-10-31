"""Held-out TCR@k curves and HITL-load tables for the report.

Usage (from the repo root):
    python scripts/report_tcr_hitl.py                       # held-out, all four suites, writes report_out/heldout/
    python scripts/report_tcr_hitl.py --suites banking slack travel --tag no_workspace   # optional subset
    python scripts/report_tcr_hitl.py --highlight provenance

Reads every run folder under submitted_results/<split>/ALL/k*/ (summary_<suite>_<attack>.json files) through
scripts/tcr_table.py, so the numbers match `tcr_table.py`.

Outputs (in --out):
    tcr_by_k<tag>.csv                 policy, k, n and TCR for attack / benign / pooled (+ 95% Wilson interval for pooled)
    tcr_all_<metric><tag>.png         every policy on one plot; the two baselines are highlighted
    tcr_<policy><tag>.png             one policy against Full-Escalate and Full-Approve, three panels (attack, benign, pooled)
    hitl_total<tag>.md / .csv         total escalations per policy and k (all tasks, attack + benign)
    hitl_completed<tag>.md            escalations spent on tasks that were completed safely (the brief's HITL load)

Full-Approve never escalates, so it was run once at k=0 and is drawn as a flat line across the k range.
TCR_attack = completed safely / user x injection pairs; TCR_benign = completed / user tasks with no attack;
TCR_pooled = all completed safely / all tasks. See docs for the definitions.
"""
import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tcr_table import load_runs, table  # noqa: E402

BASELINE_APPROVE = "full_approve"
BASELINE_ESCALATE = "full_escalate"
METRICS = {"attack": ("tcr_attack", "n_attack"), "benign": ("tcr_benign", "n_benign"), "pooled": ("tcr_pooled", "n_pooled")}


def wilson(p: float | None, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion p observed on n tasks."""
    if p is None or n == 0:
        return (float("nan"), float("nan"))
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def collect(folders: list[str], split: str, suites: list[str] | None) -> list[dict]:
    runs = load_runs(folders, suites=suites, split=split)
    rows = table(runs)
    if not rows:
        sys.exit("no summaries found (check the folders, --split and --suites)")
    return rows


def by_policy(rows: list[dict]) -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = {}
    for r in rows:
        out.setdefault(r["policy"], {})[r["k"]] = r
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["policy", "k", "n_attack", "tcr_attack", "n_benign", "tcr_benign", "n_pooled", "tcr_pooled",
                    "pooled_ci_low", "pooled_ci_high", "hitl_all", "hitl_completed"])
        for r in rows:
            lo, hi = wilson(r["tcr_pooled"], r["n_pooled"])
            w.writerow([r["policy"], r["k"], r["n_attack"], _r(r["tcr_attack"]), r["n_benign"], _r(r["tcr_benign"]),
                        r["n_pooled"], _r(r["tcr_pooled"]), _r(lo), _r(hi), r["hitl_all_pooled"], r["hitl_completed_pooled"]])


def _r(x: float | None) -> str:
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.4f}"


def hitl_tables(pol: dict[str, dict[int, dict]], ks: list[int], out: Path, tag: str) -> None:
    order = [BASELINE_APPROVE, BASELINE_ESCALATE] + sorted(p for p in pol if p not in (BASELINE_APPROVE, BASELINE_ESCALATE))
    order = [p for p in order if p in pol]
    for key, name, title in (("hitl_all_pooled", "hitl_total", "Total escalations over all tasks (attack + benign)"),
                             ("hitl_completed_pooled", "hitl_completed", "Escalations spent on tasks completed safely")):
        lines = [f"**{title}** (held-out)", "", "| policy | " + " | ".join(f"k={k}" for k in ks) + " |",
                 "|---|" + "---:|" * len(ks)]
        csv_rows = [["policy"] + [f"k{k}" for k in ks]]
        for p in order:
            cells = []
            for k in ks:
                r = pol[p].get(k) or (pol[p].get(0) if p == BASELINE_APPROVE else None)
                cells.append("-" if r is None else str(r[key]))
            lines.append(f"| {p} | " + " | ".join(cells) + " |")
            csv_rows.append([p] + cells)
        (out / f"{name}{tag}.md").write_text("\n".join(lines) + "\n")
        if name == "hitl_total":
            with (out / f"{name}{tag}.csv").open("w", newline="") as f:
                csv.writer(f).writerows(csv_rows)


def curve(pol: dict[str, dict[int, dict]], policy: str, metric: str, ks: list[int]):
    key, nkey = METRICS[metric]
    xs, ys, lo, hi = [], [], [], []
    for k in ks:
        r = pol[policy].get(k)
        if policy == BASELINE_APPROVE:
            r = pol[policy].get(0)  # never escalates, so independent of k
        if r is None or r[key] is None:
            continue
        xs.append(k)
        ys.append(r[key])
        a, b = wilson(r[key], r[nkey])
        lo.append(a)
        hi.append(b)
    return xs, ys, lo, hi


def plot_all(pol, ks, metric, out: Path, tag: str, highlight: str | None, plt) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    cmap = plt.get_cmap("tab10")
    others = sorted(p for p in pol if p not in (BASELINE_APPROVE, BASELINE_ESCALATE))
    for i, p in enumerate(others):
        xs, ys, _, _ = curve(pol, p, metric, ks)
        emph = p == highlight
        ax.plot(xs, ys, marker="o", ms=4, lw=2.6 if emph else 1.3, alpha=1 if (emph or not highlight) else 0.45,
                color=cmap(i % 10), label=p)
    for p, style in ((BASELINE_ESCALATE, dict(color="black", ls="-", lw=2.2, marker="s")),
                     (BASELINE_APPROVE, dict(color="dimgray", ls="--", lw=2.2))):
        if p in pol:
            xs, ys, _, _ = curve(pol, p, metric, ks)
            ax.plot(xs, ys, label=p.replace("_", "-") + (" (k-independent)" if p == BASELINE_APPROVE else ""), **style)
    ax.set_xlabel("escalation budget k")
    ax.set_ylabel(f"TCR ({metric})")
    ax.set_xticks(ks)
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, ncol=2, loc="best")
    ax.set_title(f"Held-out TCR@k, {metric}")
    fig.tight_layout()
    fig.savefig(out / f"tcr_all_{metric}{tag}.png", dpi=200)
    plt.close(fig)


def plot_policy(pol, ks, policy: str, out: Path, tag: str, plt) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
    for ax, metric in zip(axes, METRICS):
        for p, kw in ((BASELINE_APPROVE, dict(color="dimgray", ls="--", marker="")),
                      (BASELINE_ESCALATE, dict(color="black", ls="-", marker="s")),
                      (policy, dict(color="tab:blue", ls="-", marker="o"))):
            if p not in pol:
                continue
            xs, ys, lo, hi = curve(pol, p, metric, ks)
            ax.plot(xs, ys, lw=2, ms=4, label=p.replace("_", "-"), **kw)
            if p == policy:
                ax.fill_between(xs, lo, hi, color="tab:blue", alpha=0.15, linewidth=0)
        ax.set_title(metric)
        ax.set_xlabel("escalation budget k")
        ax.set_xticks(ks)
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("TCR")
    axes[0].legend(fontsize=8)
    fig.suptitle(f"Held-out TCR@k: {policy} vs both baselines (band = 95% Wilson interval)")
    fig.tight_layout()
    fig.savefig(out / f"tcr_{policy}{tag}.png", dpi=200)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="*", help="default: every submitted_results/<split>/ALL/k* folder")
    ap.add_argument("--split", default="heldout", choices=["dev", "heldout"])
    ap.add_argument("--suites", nargs="+", default=["banking", "slack", "travel", "workspace"],
                    help="suites to pool (default: all four)")
    ap.add_argument("--tag", default="", help="suffix for the output file names, e.g. all4")
    ap.add_argument("--out", default=None)
    ap.add_argument("--highlight", default=None, help="policy to emphasise in the all-policies plots")
    ap.add_argument("--ks", nargs="+", type=int, default=None, help="k values to include (default: all found)")
    ap.add_argument("--no-plots", action="store_true")
    args = ap.parse_args(argv)

    folders = args.folders or sorted(str(p) for p in Path(f"submitted_results/{args.split}/ALL").glob("k*") if p.is_dir())
    rows = collect(folders, args.split, args.suites)
    pol = by_policy(rows)
    ks = sorted({r["k"] for r in rows} if args.ks is None else set(args.ks))
    out = Path(args.out or f"report_out/{args.split}")
    out.mkdir(parents=True, exist_ok=True)
    tag = f"_{args.tag}" if args.tag else ""

    write_csv(rows, out / f"tcr_by_k{tag}.csv")
    hitl_tables(pol, ks, out, tag)
    print((out / f"hitl_total{tag}.md").read_text())
    print((out / f"hitl_completed{tag}.md").read_text())

    if not args.no_plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        for metric in METRICS:
            plot_all(pol, ks, metric, out, tag, args.highlight, plt)
        for p in sorted(pol):
            if p not in (BASELINE_APPROVE, BASELINE_ESCALATE):
                plot_policy(pol, ks, p, out, tag, plt)
    n_files = len(list(out.iterdir()))
    print(f"wrote {n_files} files to {out}/ (suites: {', '.join(args.suites)}; k: {ks})")


if __name__ == "__main__":
    main()
