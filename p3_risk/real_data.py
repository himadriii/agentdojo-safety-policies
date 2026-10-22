"""P3: turn real agent traces (from collect_real.sh / runner) into labeled feature rows.

Reads AgentDojo trace JSONs written by the runner, rebuilds the policy context at every
proposed tool call, and labels the call:
    1  matches the paired injection task's own target (same tool and recipient / file / email id)
    0  every other call, in runs with or without an attack
   (read-only calls that merely share a tool name with the injection chain are dropped:
    we cannot tell them apart reliably, so they are not scored)
Labels are for evaluation/training only; the policy never sees them.

Usage:  python -m p3_risk.real_data --results results/p3_collect --out p3_risk/data/real_dev.csv
"""
import argparse
import json
import warnings
from pathlib import Path

import pandas as pd

from agentdojo.functions_runtime import FunctionCall
from agentdojo.task_suite.load_suites import get_suite

from agent_framework.policies.risk_features import extract_features, tool_class
from p3_risk.handwritten_injection_gt import with_ground_truth

ID_ARG = {"send_email": "recipients", "delete_file": "file_id", "delete_email": "email_id",
          "share_file": "email", "create_calendar_event": "participants"}


def _norm(v):
    return sorted(map(str, v)) if isinstance(v, list) else str(v)


def matches(call, gt_calls):
    for g in gt_calls:
        if g.function != call.function:
            continue
        key = ID_ARG.get(g.function)
        if key is None:
            if g.args == call.args:
                return True
        elif _norm(g.args.get(key)) == _norm(call.args.get(key)):
            return True
    return False


def _rebuild(messages):
    """Trace JSON messages -> the dict form policies receive (tool_calls as FunctionCall)."""
    out = []
    for m in messages:
        m = dict(m)
        if m.get("tool_calls"):
            m["tool_calls"] = [FunctionCall(function=c["function"], args=c["args"], id=c.get("id"))
                               for c in m["tool_calls"]]
        out.append(m)
    return out


def build(results_dir, split_file, benchmark_version="v1.2", suite_name="workspace"):
    warnings.filterwarnings("ignore")
    suite = get_suite(benchmark_version, suite_name)
    split = json.loads(Path(split_file).read_text())
    rows = []
    for path in sorted(Path(results_dir).rglob("*.json")):
        if path.name.startswith("summary_"):
            continue
        t = json.loads(path.read_text())
        if "messages" not in t or t.get("suite_name") != suite_name:
            continue
        uid, iid, attack = t["user_task_id"], t["injection_task_id"], t["attack_type"] or "none"
        if uid not in suite.user_tasks:
            continue  # AgentDojo's baseline run of an injection task as a plain user task
        if uid in split["test_user_tasks"] or (iid and iid in split["test_injection_tasks"]):
            continue  # held-out tasks must not enter training data
        if iid and iid not in suite.injection_tasks:
            continue  # AgentDojo also runs injection tasks as plain user tasks; not used here
        env = suite.load_and_inject_default_environment(t.get("injections") or {})
        messages = _rebuild(t["messages"])
        task_text = suite.user_tasks[uid].PROMPT
        gt = []
        if iid:
            inj = with_ground_truth(suite, suite.injection_tasks[iid])
            gt = inj.ground_truth(suite.load_and_inject_default_environment({})) if inj else []
        for i, m in enumerate(messages):
            if m["role"] != "assistant" or not m.get("tool_calls"):
                continue
            for call in m["tool_calls"]:
                unsafe = bool(gt) and matches(call, gt)
                if gt and not unsafe and tool_class(call.function) == "read" and \
                        any(g.function == call.function for g in gt):
                    continue  # ambiguous read: not scored
                ctx = {"task": task_text, "proposed_call": call, "environment": env,
                       "trajectory": messages[: i + 1], "remaining_budget": 0, "metadata": {}}
                rows.append({
                    "episode": f"real|{attack}|{uid}|{iid}", "attack": attack, "user_task": uid,
                    "inj_task": iid or "none", "split": "dev", "order": i, "tool": call.function,
                    "label": int(unsafe), "inj_pos": -1, "injected": int(bool(iid)), "seen_attack": 1,
                    "source": "real", **extract_features(ctx)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results/p3_collect")
    ap.add_argument("--split-file", default="p3_risk/data/split.json")
    ap.add_argument("--out", default="p3_risk/data/real_dev.csv")
    a = ap.parse_args()
    df = build(a.results, a.split_file)
    df.to_csv(a.out, index=False)
    print(df.groupby(["attack", "label"]).size().unstack(fill_value=0))
    print("saved", a.out, len(df), "rows")
