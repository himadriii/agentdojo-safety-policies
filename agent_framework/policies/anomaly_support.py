"""Conservative transfer between explicitly classified read tools."""
from agent_framework.policies.anomaly_features import FEATURE_NAMES

SHAPE_FEATURES = ('log_args', 'n_keys', 'n_emails', 'n_urls')


def unsupported_reason(artifact, tool, vector):
    if tool not in artifact['tool_table']:
        return 'unknown_tool'
    # Original artifacts contain only the fitted tools.
    if tool in artifact.get('trained_tools', artifact['tool_table']):
        return None
    if artifact.get('support_mode') != 'category':
        return 'unseen_tool'
    category = artifact['tool_table'][tool]
    if category != 'read':
        return 'unseen_side_effect_tool'
    support = artifact.get('category_support', {}).get(category, {})
    if support.get('calls', 0) < 5 or support.get('tasks', 0) < 3:
        return 'insufficient_category_support'
    for name in SHAPE_FEATURES:
        low, high = support['bounds'][name]
        if not low <= vector[FEATURE_NAMES.index(name)] <= high:
            return 'outside_category_shape_support'
    return None
