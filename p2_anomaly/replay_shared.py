"""Offline routing comparison on fixed recorded calls; never estimates live TCR."""
import argparse
from collections import Counter
import json
from pathlib import Path

from agentdojo.functions_runtime import FunctionCall
from agentdojo.types import get_text_content_as_str
from agent_framework.policies.anomaly import AnomalyPolicy


def replay(root, artifacts):
    policies = {name: AnomalyPolicy(path) for name, path in artifacts.items()}
    if any(p.artifact is None for p in policies.values()):
        raise ValueError('Valid explicit artifacts required')
    counts = {name: Counter() for name in policies}
    budgets = {name: {str(k): Counter() for k in (0, 2, 5)} for name in policies}
    for path in sorted(Path(root).rglob('*.json')):
        trace = json.loads(path.read_text())
        if (trace.get('suite_name') != 'banking'
                or not trace.get('user_task_id', '').startswith('user_task_')
                or not isinstance(trace.get('utility'), bool)):
            continue
        task = next(get_text_content_as_str(m['content']) for m in trace['messages'] if m['role'] == 'user')
        flags = Counter()
        for position, message in enumerate(trace['messages']):
            if message['role'] != 'assistant':
                continue
            for raw in message.get('tool_calls') or []:
                context = {'task': task, 'trajectory': trace['messages'][:position + 1],
                           'proposed_call': FunctionCall.model_validate(raw)}
                for name, policy in policies.items():
                    decision, _, info = policy.evaluate(context, {})
                    counts[name]['proposed_calls'] += 1
                    counts[name][decision] += 1
                    counts[name]['fallback'] += bool(info['scores'].get('fallback'))
                    flags[name] += decision == 'escalate'
        for name in policies:
            counts[name]['episodes'] += 1
            for k in (0, 2, 5):
                budgets[name][str(k)]['review_slots_needed'] += min(flags[name], k)
                budgets[name][str(k)]['calls_over_budget'] += max(flags[name] - k, 0)
    return {'status': 'Offline routing only; same recorded proposals, not new agent trajectories',
            'warning': 'Changing approvals changes later actions. No live TCR, HITL improvement or attack-resistance claim follows.',
            'counts': counts, 'hypothetical_budgets': budgets}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--traces', type=Path, required=True)
    parser.add_argument('--old', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = replay(args.traces, {'old': args.old, 'candidate': args.candidate})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, indent=2))
