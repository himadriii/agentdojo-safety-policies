"""Scripted replay episodes built from AgentDojo reference solutions (plan KTD9, KTD10).

An episode is the call sequence an agent would make for one held-out user task, with the
injection task's calls spliced in after the first user call. Each call carries a unique id
and a label ("user" or "injection"). Labels never leave p6_reuse/: only the simulated
ideal reviewer and the metrics read them.
"""
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from agentdojo.functions_runtime import FunctionCall
from agentdojo.task_suite.load_suites import get_suite

from p6_reuse.handwritten_injection_gt import with_ground_truth

BENCHMARK_VERSION = "v1.2"
SPLIT_PATH = Path(__file__).parent / "data" / "split.json"

# Workspace mirrors P3's held-out split (origin/sahana: p3_risk/data/split.json).
WORKSPACE_USER_TASKS = [0, 1, 13, 15, 2, 22, 27, 28, 33, 35, 4, 8]
WORKSPACE_INJECTION_TASKS = [10, 2, 7, 9]
SLACK_INJECTION_TASKS = [1, 3]   # phishing DM to Alice; attacker URL visit (the R6 holes)


@dataclass
class Episode:
    suite: str
    user_task: str
    injection_task: str | None
    prompt: str
    calls: list = field(default_factory=list)    # FunctionCall with id
    labels: dict = field(default_factory=dict)   # call id -> "user" | "injection"


def _ids(prefix, numbers):
    return [f"{prefix}_{n}" for n in numbers]


def make_split(seed=0):
    rng = random.Random(seed)
    split = {"seed": seed, "benchmark_version": BENCHMARK_VERSION, "suites": {
        "workspace": {"user_tasks": _ids("user_task", sorted(WORKSPACE_USER_TASKS)),
                      "injection_tasks": _ids("injection_task", sorted(WORKSPACE_INJECTION_TASKS))},
        "slack": {"injection_tasks": _ids("injection_task", SLACK_INJECTION_TASKS)},
        "travel": {},
    }}
    for name in ("slack", "travel"):
        suite = get_suite(BENCHMARK_VERSION, name)
        users = sorted(suite.user_tasks, key=lambda t: int(t.rsplit("_", 1)[1]))
        split["suites"][name]["user_tasks"] = sorted(rng.sample(users, round(len(users) / 3)),
                                                     key=lambda t: int(t.rsplit("_", 1)[1]))
    travel = get_suite(BENCHMARK_VERSION, "travel")
    env = travel.load_and_inject_default_environment({})
    with_gt = sorted((t for t, task in travel.injection_tasks.items() if task.ground_truth(env)),
                     key=lambda t: int(t.rsplit("_", 1)[1]))
    split["suites"]["travel"]["injection_tasks"] = sorted(rng.sample(with_gt, 2),
                                                          key=lambda t: int(t.rsplit("_", 1)[1]))
    return split


def load_split(path=SPLIT_PATH):
    return json.loads(Path(path).read_text())


def _with_ids(calls, label, start, labels):
    out = []
    for i, c in enumerate(calls):
        call_id = f"replay_{start + i}"
        out.append(FunctionCall(function=c.function, args=dict(c.args), id=call_id))
        labels[call_id] = label
    return out


def make_episode(suite, user_task, prompt, user_calls, injection_task=None, injection_calls=()):
    labels = {}
    users = _with_ids(user_calls, "user", 0, labels)
    injected = _with_ids(injection_calls, "injection", len(users), labels)
    calls = users[:1] + injected + users[1:]   # injected text arrives with the first tool result
    return Episode(suite, user_task, injection_task, prompt, calls, labels)


def build_episodes(suites=("slack", "workspace", "travel"), split=None):
    """Return (episodes, skipped) where skipped lists (suite, injection_task) with no reference solution."""
    split = split or load_split()
    episodes, skipped = [], []
    for name in suites:
        suite = get_suite(split.get("benchmark_version", BENCHMARK_VERSION), name)
        cfg = split["suites"][name]
        injections = []
        for inj_id in cfg["injection_tasks"]:
            task = suite.injection_tasks[inj_id]
            if name == "workspace":   # P3's hand-written sequences cover workspace tasks only
                task = with_ground_truth(suite, task)
            calls = task.ground_truth(suite.load_and_inject_default_environment({})) if task else []
            if calls:
                injections.append((inj_id, calls))
            else:
                skipped.append((name, inj_id))
        for user_id in cfg["user_tasks"]:
            user = suite.user_tasks[user_id]
            user_calls = user.ground_truth(suite.load_and_inject_default_environment({}))
            episodes.append(make_episode(name, user_id, user.PROMPT, user_calls))
            for inj_id, inj_calls in injections:
                episodes.append(make_episode(name, user_id, user.PROMPT, user_calls, inj_id, inj_calls))
    return episodes, skipped


if __name__ == "__main__":
    SPLIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPLIT_PATH.write_text(json.dumps(make_split(), indent=2) + "\n")
    print(f"wrote {SPLIT_PATH}")
