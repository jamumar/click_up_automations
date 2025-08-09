# automations/custom_field_changed.py
import json
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("webhook_logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

async def handle_custom_field_change(task: dict, history_items: list):
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    log_file = LOG_DIR / f"custom_field_change_{timestamp}.json"

    data = {
        "timestamp": timestamp,
        "task": task,
        "history_items": history_items
    }

    with open(log_file, "w") as f:
        json.dump(data, f, indent=4)
