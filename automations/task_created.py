# automations/task_created.py
import json
from datetime import datetime
from pathlib import Path

LOG_PATH = Path("logs/task_created.json")

async def handle_task_created(task: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    data_to_log = {
        "timestamp": datetime.utcnow().isoformat(),
        "task": task
    }

    # Append to file (or create new list if file doesn't exist)
    if LOG_PATH.exists():
        with LOG_PATH.open("r+") as file:
            try:
                existing = json.load(file)
            except json.JSONDecodeError:
                existing = []

            existing.append(data_to_log)
            file.seek(0)
            json.dump(existing, file, indent=2)
    else:
        with LOG_PATH.open("w") as file:
            json.dump([data_to_log], file, indent=2)
