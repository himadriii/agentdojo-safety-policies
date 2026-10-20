"""Create splits/workspace_v1.2.json. Run once, commit the file.
Usage: python scripts/make_split.py [--examined splits/examined.json]
Examined tasks always go to dev; heldout is drawn only from tasks nobody has examined."""
import argparse
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

from agentdojo.attacks.attack_registry import load_attack
from agentdojo.task_suite.load_suites import get_suite

p = argparse.ArgumentParser()
p.add_argument("--version", default="v1.2")
p.add_argument("--seed", type=int, default=2026)
p.add_argument("--user-dev", type=int, default=8)
p.add_argument("--user-held", type=int, default=10)
p.add_argument("--inj-dev", type=int, default=3)
p.add_argument("--inj-held", type=int, default=4)
p.add_argument("--examined", default="splits/examined.json")
p.add_argument("--suite", default="workspace")
p.add_argument("--out", default=None)
# p.add_argument("--out", default="splits/workspace_v1.2.json")
a = p.parse_args()
out_path = a.out or f"splits/{a.suite}_{a.version}.json"

examined = {"user_tasks": set(), "injection_tasks": set()}
if Path(a.examined).exists():
    full = json.loads(Path(a.examined).read_text())
    if "user_tasks" in full:
        sys.exit("examined.json uses the old flat format; key it by suite")
    raw = full.get(a.suite, {})
    for kind in examined:
        for owner_list in raw.get(kind, {}).values():
            examined[kind] |= set(owner_list)

suite = get_suite(a.version, a.suite)
rng = random.Random(a.seed)
atk = load_attack("important_instructions", suite, SimpleNamespace(name="gpt-4o-2024-05-13"))

# user tasks the attack can actually inject into (others would crash the attack run)
injectable = []
for tid, ut in suite.user_tasks.items():
    try:
        atk.get_injection_candidates(ut)
        injectable.append(tid)
    except ValueError:
        pass

# injection tasks, round-robin over their tool signature so each split covers different attack types
env = suite.load_and_inject_default_environment({})
groups = {}
for iid, it in suite.injection_tasks.items():
    sig = tuple(sorted({c.function for c in it.ground_truth(env)}))
    groups.setdefault(sig, []).append(iid)
for g in groups.values():
    rng.shuffle(g)
inj_order = []
while any(groups.values()):
    for g in groups.values():
        if g:
            inj_order.append(g.pop())


def split(pool, seen, n_dev, n_held, label):
    seen_in_pool = sorted(t for t in pool if t in seen)
    fresh = [t for t in pool if t not in seen]
    rng.shuffle(fresh)
    dev = seen_in_pool + fresh[: max(0, n_dev - len(seen_in_pool))]
    rest = [t for t in fresh if t not in dev]
    held = rest[:n_held]
    if len(held) < n_held:
        print(f"WARNING: only {len(held)} unexamined {label} left for heldout (wanted {n_held})", file=sys.stderr)
    return dev, held


u_dev, u_held = split(injectable, examined["user_tasks"], a.user_dev, a.user_held, "user tasks")
i_dev, i_held = split(inj_order, examined["injection_tasks"], a.inj_dev, a.inj_held, "injection tasks")

out = {
    "seed": a.seed, "benchmark_version": a.version, "suite": a.suite,
    "note": "heldout may be run once per frozen policy with --final. Examined tasks are in dev by construction.",
    "dev": {"user_tasks": u_dev, "injection_tasks": i_dev},
    "heldout": {"user_tasks": u_held, "injection_tasks": i_held},
    "excluded_from_heldout_as_examined": {k: sorted(v) for k, v in examined.items()},
}
Path(out_path).parent.mkdir(exist_ok=True)
Path(out_path).write_text(json.dumps(out, indent=2))
print(json.dumps({k: out[k] for k in ("dev", "heldout")}, indent=2))
