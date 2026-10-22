"""Coverage and task-clustered uncertainty; no benchmark labels enter scoring."""
from collections import Counter, defaultdict

import numpy as np


def coverage(rows, table):
    counts = Counter(r['tool'] for r in rows)
    tasks = defaultdict(set)
    real = Counter()
    for row in rows:
        tasks[row['tool']].add(row.get('group_id', row['user_task']))
        real[row['tool']] += row.get('source') == 'audited_real'
    return {tool: {'category': category, 'calls': counts[tool],
                   'independent_tasks': len(tasks[tool]), 'audited_real_calls': real[tool]}
            for tool, category in sorted(table.items())}


def clustered_flag_interval(rows, flags, repetitions=2000):
    groups = defaultdict(lambda: [0, 0])
    for row, flag in zip(rows, flags):
        groups[row.get('group_id', row['user_task'])][0] += int(flag)
        groups[row.get('group_id', row['user_task'])][1] += 1
    values = np.asarray(list(groups.values()))
    rng = np.random.default_rng(42)
    estimates = []
    for _ in range(repetitions):
        sample = values[rng.integers(0, len(values), len(values))].sum(axis=0)
        estimates.append(float(sample[0] / sample[1]))
    return {'method': 'task-family cluster bootstrap, descriptive, not a safety guarantee',
            'independent_groups': len(groups), 'independent_tasks': len(groups), 'calls': len(rows),
            'distinct_task_ids': len({r['user_task'] for r in rows}),
            'rate': float(np.sum(flags) / len(flags)),
            'lower_95': float(np.quantile(estimates, 0.025)),
            'upper_95': float(np.quantile(estimates, 0.975))}
