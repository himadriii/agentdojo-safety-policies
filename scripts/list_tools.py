"""Print every tool per suite and whether tool_meta covers it. Usage: python scripts/list_tools.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentdojo.task_suite.load_suites import get_suites
from agent_framework.tool_meta import TOOL_META

for suite_name, suite in get_suites("v1.2").items():
    names = sorted(t.name for t in suite.tools)
    missing = [n for n in names if n not in TOOL_META]
    print(f"\n== {suite_name}: {len(names)} tools, {len(missing)} not in table ==")
    for n in names:
        print(("   " if n in TOOL_META else " ? ") + n)
    if suite_name == "workspace":
        stale = sorted(set(TOOL_META) - set(names))
        if stale:
            print("   in table but not in the workspace suite:", stale)
