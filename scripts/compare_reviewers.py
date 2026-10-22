"""Compare two runner summaries (e.g. reviewer v3 vs raw). Usage:
python -m scripts.compare_reviewers <summary_A.json> <summary_B.json>
"""
import json
import sys
from collections import Counter
from pathlib import Path


def load(path):
    s = json.loads(Path(path).read_text())
    return s, s["rows"]


def stats(name, s):
    rows = s["rows"]
    ds = [d for d in s.get("gate_decisions", []) if d.get("reviewer_called")]
    approved = sum(d["executed"] for d in ds)
    print(f"\n== {name}")
    print(f"  pairs={s['n']}  TCR={s['tcr']:.3f}  utility={sum(r['utility'] for r in rows.values())}"
          f"  attacks_succeeded={sum(r['attack_succeeded'] for r in rows.values())}")
    print(f"  reviewer calls={len(ds)}  approved={approved}  denied={len(ds) - approved}")
    print(f"  reviewer tokens: {s.get('token_usage', {}).get('reviewer')}")
    by_tool = Counter((d["tool"], "approve" if d["executed"] else "deny") for d in ds)
    for (tool, v), n in sorted(by_tool.items()):
        print(f"    {tool:28s} {v:8s} {n}")


def main(a, b):
    sa, ra = load(a)
    sb, rb = load(b)
    stats("A: " + Path(a).parent.name, sa)
    stats("B: " + Path(b).parent.name, sb)
    print("\n== pairs whose outcome differs (A -> B)")
    shown = 0
    for key in sorted(set(ra) & set(rb)):
        x, y = ra[key], rb[key]
        if (x["utility"], x["attack_succeeded"]) != (y["utility"], y["attack_succeeded"]):
            shown += 1
            print(f"  {key}: utility {x['utility']}->{y['utility']}, "
                  f"attack {x['attack_succeeded']}->{y['attack_succeeded']}")
    if not shown:
        print("  (none)")
    print("\n== reviewer denials in A and B (read the reasons)")
    for tag, s in (("A", sa), ("B", sb)):
        for d in s.get("gate_decisions", []):
            if d.get("reviewer_called") and not d["executed"]:
                print(f"  [{tag}] {d['user_task']}|{d['injection_task']} {d['tool']} "
                      f"{json.dumps(d['args'], ensure_ascii=False)[:110]} :: {d.get('reviewer_reason')}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
