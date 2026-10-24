"""Check that run summaries use the shared setup. Usage: python scripts/check_summaries.py results/dev/P7"""
import json
import sys
from pathlib import Path

WANT = ("lmstudio", "openai/gpt-oss-20b")

for path in sorted(Path(sys.argv[1]).rglob("summary_*.json")):
    s = json.loads(path.read_text())
    used = {name: (c["provider"], c["model"]) for name, c in s["inference"].items()}
    issues = [f"{name}={v}" for name, v in used.items() if v != WANT]
    if s["reviewer"] != "llm":
        issues.append(f"reviewer={s['reviewer']}")
    if s["tasks_with_errors"]:
        issues.append(f"{s['tasks_with_errors']} errored tasks")
    print(("FAIL " if issues else "ok   ") + str(path), *issues)
