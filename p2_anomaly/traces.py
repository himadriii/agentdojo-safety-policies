"""Extract audited clean real calls without future-message or held-out leakage.

Audit JSON format: [{"path": "results/.../none.json", "sha256": "...",
                     "approved_call_indices": [0, 1]}].
Indices enumerate proposed calls, not messages. Human audit establishes legitimacy;
utility=true or attack_type=null alone does not.
"""
import hashlib
import json
from pathlib import Path

from agentdojo.functions_runtime import FunctionCall
from agent_framework.policies.anomaly_features import extract_features
from p2_anomaly.splits import group_id


def extract_audited(manifest_path, fit_tasks, calibration_tasks, tool_table):
    fit, calibration = [], []
    seen = set()
    manifest_path = Path(manifest_path)
    for entry in json.loads(manifest_path.read_text()):
        path = Path(entry['path'])
        if not path.is_absolute():
            path = manifest_path.parent / path
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != entry['sha256']:
            raise ValueError('audit trace hash mismatch')
        if digest in seen:
            raise ValueError('duplicate audited trace')
        seen.add(digest)
        trace = json.loads(raw)
        uid = trace['user_task_id']
        if uid not in fit_tasks | calibration_tasks:
            raise ValueError('held-out or auxiliary task in audit manifest')
        if (trace.get('suite_name') != 'workspace' or trace.get('attack_type') not in (None, 'none')
                or trace.get('injection_task_id') is not None or trace.get('injections')
                or (trace.get('error') and not entry.get('partial_episode'))):
            raise ValueError('audit trace must be a clean, non-error workspace episode')
        if entry.get('partial_episode') and not entry.get('episode_status'):
            raise ValueError('partial episode requires an explicit audit status')
        messages = trace['messages']
        task = next(m for m in messages if m['role'] == 'user')
        from agentdojo.types import get_text_content_as_str
        task_text = get_text_content_as_str(task['content'])
        approved = entry['approved_call_indices']
        if len(set(approved)) != len(approved) or any(type(i) is not int or i < 0 for i in approved):
            raise ValueError('invalid audited call indices')
        found, index = set(), 0
        for pos, message in enumerate(messages):
            if message['role'] != 'assistant':
                continue
            for raw_call in message.get('tool_calls') or []:
                if index in approved:
                    call = FunctionCall.model_validate(raw_call)
                    vector = extract_features({'task': task_text, 'proposed_call': call,
                                               'trajectory': messages[:pos + 1]}, tool_table)
                    row = {'user_task': uid, 'tool': call.function, 'features': vector,
                           'group_id': group_id(uid),
                           'source': 'audited_real', 'trace_sha256': digest, 'call_index': index,
                           'audit_kind': entry.get('audit_kind', 'manually selected'),
                           'reviewer_model': entry.get('reviewer_model'),
                           'partial_episode': bool(entry.get('partial_episode')),
                           'episode_status': entry.get('episode_status', 'completed'),
                           'agent_configuration': entry.get('agent_configuration', 'see source trace')}
                    (fit if uid in fit_tasks else calibration).append(row)
                    found.add(index)
                index += 1
        if found != set(approved):
            raise ValueError('audited call index outside trace')
    return fit, calibration
