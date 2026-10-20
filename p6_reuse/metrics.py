"""Shared counting and CSV helpers for P6's replay, probe and live-run summaries."""
import csv
from pathlib import Path


def reuse_counts(decisions) -> dict:
    """Reviews saved by approval and denial memory, and budget-exhausted denials, from runner decision records."""
    def score(d, name):
        return (d.get("scores") or {}).get(name)

    return {
        "reviews_saved_approval": sum(d["outcome"] == "auto_approve" and score(d, "reuse_approved") == 1.0
                                      for d in decisions),
        "reviews_saved_denial": sum(d["outcome"] == "auto_deny" and score(d, "reuse_denied") == 1.0
                                    for d in decisions),
        "budget_exhausted_denials": sum(d["outcome"] == "budget_exhausted_deny" for d in decisions),
    }


def write_csv(path: Path, rows, fieldnames=None):
    with Path(path).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
