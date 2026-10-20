"""Development split v2: declared task families, not just different task IDs.

The team's outer test IDs are preserved. Earlier v1 model/calibration results
are superseded. Public task definitions are inspected only to audit the split;
no ground-truth calls or benchmark evaluators are invoked here.
"""
from agentdojo.base_tasks import BaseUserTask

SPLIT_VERSION = 'v2-family-audited'
TEST = [0, 1, 2, 4, 8, 13, 15, 22, 27, 28, 33, 35]
QUARANTINE = [6, 10, 19, 20, 23, 38, 39]
FIT = [3, 7, 9, 12, 16, 21, 25, 29, 30, 31, 32, 36, 37]
CALIBRATE = [5, 11, 14, 17, 18, 24, 26, 34]
FAMILIES = {
    'lunch_timing': [5, 11],
    'hiking': [17, 18],
    'followup_meeting': [9, 12, 21],
    'hawaii_files': [30, 31, 32, 36, 37],
}


def group_id(uid):
    number = int(uid.removeprefix('user_task_'))
    return next((name for name, members in FAMILIES.items() if number in members), uid)


def leaves(task):
    cells = task.ground_truth.__func__.__closure__ or []
    children = [c.cell_contents for c in cells if isinstance(c.cell_contents, BaseUserTask)]
    return set().union(*(leaves(child) for child in children)) if children else {task.ID}


def audit(suite):
    partitions = [set(FIT), set(CALIBRATE), set(TEST), set(QUARANTINE)]
    if set.union(*partitions) != set(range(40)) or sum(map(len, partitions)) != 40:
        raise ValueError('task partition must cover each task exactly once')
    test_leaves = set().union(*(leaves(suite.user_tasks[f'user_task_{i}']) for i in TEST))
    overlaps = {f'user_task_{i}': sorted(leaves(suite.user_tasks[f'user_task_{i}']) & test_leaves)
                for i in range(40) if i not in TEST and
                leaves(suite.user_tasks[f'user_task_{i}']) & test_leaves}
    if any(f'user_task_{i}' in overlaps for i in FIT + CALIBRATE):
        raise ValueError('development task contains a held-out component')
    fit_groups = {group_id(f'user_task_{i}') for i in FIT}
    cal_groups = {group_id(f'user_task_{i}') for i in CALIBRATE}
    if fit_groups & cal_groups:
        raise ValueError('task-family overlap between fit and calibration')
    return {'version': SPLIT_VERSION, 'fit': FIT, 'calibration': CALIBRATE, 'test': TEST,
            'quarantined': QUARANTINE, 'declared_test_component_overlaps': overlaps,
            'additional_variant_quarantine': {'10': 'date-counting variant of held-out task 1',
                                              '20': 'lunch-event variant of held-out component 6'},
            'fit_families': sorted(fit_groups), 'calibration_families': sorted(cal_groups),
            'limitations': 'Shared environment entities and unrecognized semantic overlap remain possible.'}
