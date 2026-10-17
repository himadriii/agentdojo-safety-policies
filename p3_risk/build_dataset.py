"""P3: build the labeled tool-call dataset from AgentDojo ground truth.

For every (user task, injection task, attack) we replay the user task's ground-truth
calls in an environment that contains the attack's injection text, then splice in the
injection task's ground-truth calls right after the tool result that carried the text.
Each proposed call becomes one row: label 0 = user-task call, label 1 = injection-task call.
Labels exist only here (training/evaluation); the policy never sees them.

Splits are by task (seeded, written to data/split.json) and mixed pairs are dropped so
neither the user task nor the injection task of a held-out episode appears in training.

Usage:  python -m p3_risk.build_dataset [--suite workspace]
"""
import argparse
import json
import random
import re
import warnings
from pathlib import Path

import pandas as pd

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
from agentdojo.attacks.attack_registry import ATTACKS, load_attack
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.types import get_text_content_as_str, text_content_block_from_string

from agent_framework.policies.risk_features import FEATURE_NAMES, extract_features
from p3_risk.handwritten_injection_gt import with_ground_truth

DATA_DIR = Path(__file__).parent / "data"
ATTACK_NAMES = ["none", "important_instructions", "direct", "ignore_previous",
                "injecagent", "tool_knowledge", "system_message"]
TRAIN_ATTACKS = ["none", "important_instructions", "direct", "ignore_previous"]
TEST_ONLY_ATTACKS = ["injecagent", "tool_knowledge", "system_message"]  # unseen in training
N_TEST_USER, N_TEST_INJ, SEED = 12, 4, 0


class _NamedPipeline(BasePipelineElement):
    """Attacks only read pipeline.name (to address the model by name)."""
    name = "gpt-4o-2024-05-13"

    def query(self, *a, **k):  # pragma: no cover
        raise NotImplementedError


def make_split(suite):
    path = DATA_DIR / "split.json"
    if path.exists():
        return json.loads(path.read_text())
    rng = random.Random(SEED)
    users, injs = sorted(suite.user_tasks), sorted(suite.injection_tasks)
    rng.shuffle(users)
    rng.shuffle(injs)
    split = {
        "seed": SEED, "suite": suite.name,
        "test_user_tasks": sorted(users[:N_TEST_USER]), "dev_user_tasks": sorted(users[N_TEST_USER:]),
        "test_injection_tasks": sorted(injs[:N_TEST_INJ]), "dev_injection_tasks": sorted(injs[N_TEST_INJ:]),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(split, indent=2))
    return split


def _alnum(text):
    """Whitespace/punctuation-insensitive form (tool outputs are YAML-serialised)."""
    return re.sub(r"\W+", "", text)


def _msg_text(m):
    return get_text_content_as_str(m["content"]) if m.get("content") else ""


def _system_message():
    return {"role": "system", "content": [text_content_block_from_string("You are a helpful assistant.")]}


def _user_message(prompt):
    return {"role": "user", "content": [text_content_block_from_string(prompt)]}


def replay(suite, task, injections, extra_messages=()):
    """Run a task's ground truth in a fresh (injected) environment; return (env, messages)."""
    env = suite.load_and_inject_default_environment(injections)
    prompt = getattr(task, "PROMPT", None) or task.GOAL
    if hasattr(task, "init_environment"):
        env = task.init_environment(env)
    runtime = FunctionsRuntime(suite.tools)
    start = [_system_message(), _user_message(prompt), *extra_messages]
    _, _, env, msgs, _ = GroundTruthPipeline(task).query(prompt, runtime, env, start)
    return env, list(msgs)


def calls_with_context(messages, labels):
    """Yield (call, trajectory_up_to_and_including_the_requesting_assistant_message, label)."""
    for i, m in enumerate(messages):
        if m["role"] == "assistant" and m.get("tool_calls"):
            for call in m["tool_calls"]:
                yield call, messages[: i + 1], labels.get(id(m), 0)


def build_episode(suite, user_task, inj_task, injections):
    """Return an ordered list of (call, trajectory, label, inj_pos) for one episode."""
    env, umsgs = replay(suite, user_task, injections)
    # strip the final no-tool-call answer
    umsgs = [m for m in umsgs if not (m["role"] == "assistant" and not m.get("tool_calls"))]
    if inj_task is None:
        return env, [(c, t, 0, -1) for c, t, _ in calls_with_context(umsgs, {})]

    marker = next(iter(injections.values()), None)
    # index of the first tool result that carries the injection text; with no injection
    # (attack "none") the unsafe calls appear after the first tool result, in clean context
    key = _alnum(marker)[:40] if marker else None
    j = next((i for i, m in enumerate(umsgs)
              if m["role"] == "tool" and (key is None or key in _alnum(_msg_text(m)))), None)
    if j is None:
        return env, [(c, t, 0, -1) for c, t, _ in calls_with_context(umsgs, {})]

    prefix, suffix = umsgs[: j + 1], umsgs[j + 1:]
    # injection task ground truth, executed in its own fresh environment
    inj_task = with_ground_truth(suite, inj_task)
    if inj_task is None:
        return env, [(c, t, 0, -1) for c, t, _ in calls_with_context(umsgs, {})]
    _, imsgs = replay(suite, inj_task, {})
    imsgs = [m for m in imsgs[2:] if not (m["role"] == "assistant" and not m.get("tool_calls"))]
    spliced = prefix + imsgs + suffix
    episode, inj_pos = [], 0
    inj_ids = {id(m) for m in imsgs}
    for i, m in enumerate(spliced):
        if m["role"] == "assistant" and m.get("tool_calls"):
            is_inj = id(m) in inj_ids
            for call in m["tool_calls"]:
                episode.append((call, spliced[: i + 1], int(is_inj), inj_pos if is_inj else -1))
            inj_pos += int(is_inj)
    return env, episode


def main():
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="workspace")
    ap.add_argument("--benchmark-version", default="v1.2")
    ap.add_argument("--out", default=str(DATA_DIR / "dataset.csv"))
    args = ap.parse_args()

    suite = get_suite(args.benchmark_version, args.suite)
    split = make_split(suite)
    dev_u, test_u = set(split["dev_user_tasks"]), set(split["test_user_tasks"])
    dev_i, test_i = set(split["dev_injection_tasks"]), set(split["test_injection_tasks"])
    pipeline = _NamedPipeline()

    rows, skipped = [], []
    for attack_name in ATTACK_NAMES:
        attack = None if attack_name == "none" else load_attack(attack_name, suite, pipeline)
        for uid, utask in sorted(suite.user_tasks.items()):
            for iid, itask in sorted(suite.injection_tasks.items()):
                if uid in dev_u and iid in dev_i:
                    part = "dev"
                elif uid in test_u and iid in test_i:
                    part = "test"
                else:
                    continue  # mixed pair: dropped to prevent leakage
                if attack_name in TEST_ONLY_ATTACKS and part == "dev":
                    continue  # unseen attacks are used only for held-out evaluation
                try:
                    if attack is None:
                        injections = {}
                    else:
                        injections = attack.attack(utask, itask)
                    env, episode = build_episode(suite, utask, itask, injections)
                except Exception as e:  # not injectable, or ground truth fails in this state
                    skipped.append((attack_name, uid, iid, type(e).__name__))
                    continue
                eid = f"{attack_name}|{uid}|{iid}"
                for order, (call, traj, label, inj_pos) in enumerate(episode):
                    ctx = {"task": utask.PROMPT, "proposed_call": call, "environment": env,
                           "trajectory": traj, "remaining_budget": 0, "metadata": {}}
                    feats = extract_features(ctx)
                    rows.append({
                        "episode": eid, "attack": attack_name, "user_task": uid, "inj_task": iid,
                        "split": part, "order": order, "tool": call.function, "label": label,
                        "inj_pos": inj_pos, "injected": int(bool(injections)),
                        "seen_attack": int(attack_name in TRAIN_ATTACKS), **feats,
                    })
        print(f"{attack_name}: {len(rows)} rows so far")

    df = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(df.groupby(["split", "label"]).size().unstack(fill_value=0))
    print(f"skipped {len(skipped)} (attack,user,inj) combos; examples: {skipped[:5]}")
    assert list(FEATURE_NAMES) == [c for c in df.columns if c in FEATURE_NAMES]


if __name__ == "__main__":
    main()
