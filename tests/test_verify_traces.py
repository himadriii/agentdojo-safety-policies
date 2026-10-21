"""The shared checker must validate every suite, including nested P2 outputs."""
import json
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify_traces.py'


def test_empty_results_are_not_success(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'no traces checked' in result.stdout


def test_all_suites_checked_and_policy_errors_rejected(tmp_path):
    for suite in ('workspace', 'banking', 'slack', 'travel'):
        path = tmp_path / 'runs' / suite / 'pipeline-k2-llm' / suite / 'user_task_0' / 'none.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'approval_decisions': [], 'token_usage': {'agent': {'calls': 1}}}))
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0
    assert 'checked 4 traces, 0 problems' in result.stdout
    data = json.loads(path.read_text())
    data['token_usage']['agent']['calls'] = 0
    path.write_text(json.dumps(data))
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'no agent token usage' in result.stdout
