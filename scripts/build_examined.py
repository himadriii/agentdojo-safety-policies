"""Write splits/examined.json from what each owner reported. Run from the repo root."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ALL40 = [f"user_task_{i}" for i in range(40)]
inj = lambda *n: [f"injection_task_{i}" for i in n]

examined = {
    "workspace": {
        "user_tasks": {
            "P1": ALL40[:3],
            "P2_inspected": ALL40,
            "P4": ALL40,
            "P6": ALL40,
            "P7": [f"user_task_{i}" for i in (0, 1, 2, 4, 8, 13, 15, 22, 27, 28, 33, 35)],
            "P3": [], "P5": [],
        },
        "injection_tasks": {
            "P1": inj(0, 1), "P2": inj(0), "P4": inj(0, 1), "P7": inj(2, 7, 9, 10),
            "P3": [], "P5": [], "P6": [],
        },
    },
    "slack": {
        "user_tasks": {"P7": [f"user_task_{i}" for i in (1, 6, 8, 12, 13, 15, 16)], "P2": [],
                       "P3": [], "P4": [], "P5": [], "P6": []},
        "injection_tasks": {"P7": inj(1, 3)},
    },
    "travel": {
        "user_tasks": {"P7": [f"user_task_{i}" for i in (2, 4, 6, 9, 11, 15, 18)], "P2": [],
                       "P3": [], "P4": [], "P5": [], "P6": []},
        "injection_tasks": {"P7": inj(0, 4)},
    },
    "banking": {"user_tasks": {"P2": []}, "injection_tasks": {}},
}
Path("splits").mkdir(exist_ok=True)
Path("splits/examined.json").write_text(json.dumps(examined, indent=2))
print("written")
