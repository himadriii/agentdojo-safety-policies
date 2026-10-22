"""Refit a saved feature dataset and verify model scores without API access."""
import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

import joblib
import numpy as np

from p2_anomaly.splits import FIT, CALIBRATE, group_id
from p2_anomaly.train import fit_artifact


def reproduce(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('revoked'):
        raise ValueError('revoked artifact cannot be reproduced as a current candidate')
    for package in ('scikit-learn', 'joblib', 'numpy'):
        if version(package) != manifest['versions'][package]:
            raise ValueError(f'version mismatch: {package}')
    raw = (directory / 'reference_features.json').read_text().removesuffix('\n')
    if hashlib.sha256(raw.encode()).hexdigest() != manifest['data_sha256']:
        raise ValueError('dataset checksum mismatch')
    if hashlib.sha256((directory / 'model.joblib').read_bytes()).hexdigest() != manifest['model_sha256']:
        raise ValueError('model checksum mismatch')
    data = json.loads(raw)
    for part, ids in [('fit', FIT), ('calibration', CALIBRATE)]:
        allowed = {f'user_task_{i}' for i in ids}
        for row in data[part]:
            if row['user_task'] not in allowed or row.get('group_id') != group_id(row['user_task']):
                raise ValueError('dataset task/family partition mismatch')
    fitted, report = fit_artifact(data['fit'], data['calibration'], manifest['tool_table'],
                                  manifest['target_review_rate'], manifest['support_mode'])
    original = joblib.load(directory / 'model.joblib')
    vectors = [r['features'] for r in data['fit'] + data['calibration']]
    if not np.allclose(fitted['model'].score_samples(vectors), original['model'].score_samples(vectors),
                       rtol=0, atol=1e-12) or fitted['threshold'] != original['threshold']:
        raise ValueError('refitted scores or threshold differ from saved artifact')
    return {'verified': True, 'api_calls': 0, 'fit_calls': report['fit_calls'],
            'calibration_calls': report['calibration_calls'], 'threshold': fitted['threshold']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    print(json.dumps(reproduce(parser.parse_args().directory), indent=2))
