# import json, time
# from pathlib import Path

# class CallLogger:
#     def __init__(self, path):
#         self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
#         self.run_info = {}          # runner sets policy, k, user_task, ... here
#     def log(self, **record):
#         record = {"ts": time.time(), **self.run_info, **record}
#         with self.path.open("a") as f:
#             f.write(json.dumps(record, default=str) + "\n")
