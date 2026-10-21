import json
from pathlib import Path
import pytest

SPLIT = Path("splits/workspace_v1.2.json")
FILES = sorted(Path("splits").glob("*_v*.json"))


@pytest.mark.skipif(not FILES, reason="no split files generated yet")
@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_split_has_no_overlap_and_excludes_examined(path):
    s = json.loads(path.read_text())
    for kind in ("user_tasks", "injection_tasks"):
        assert not set(s["dev"][kind]) & set(s["heldout"][kind])
        assert not set(s["heldout"][kind]) & set(s["excluded_from_heldout_as_examined"][kind])
