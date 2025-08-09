# api/custom_field_changed.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from automations.custom_field_changed import handle_custom_field_change

import os
import json
from datetime import datetime
from typing import Dict, Any

from core.queue import queue

router = APIRouter()
LOG_DIR = "webhook_logs"
os.makedirs(LOG_DIR, exist_ok=True)

def _save_json(path: str, data: Dict[str, Any]):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

@router.post("/webhook/custom-field-changed")
async def custom_field_changed_webhook(request: Request):
    raw: Dict[str, Any] = {}
    try:
        raw = await request.json()

        # Save full payload
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        filename = f"{LOG_DIR}/custom_field_raw_{timestamp}.json"
        _save_json(filename, raw)

        event = raw.get("event")
        task = raw.get("task", {}) or {}
        history_items = raw.get("history_items", []) or []

        # Proceed only if event is taskUpdated AND at least one custom field was updated
        is_custom_field_change = any(item.get("field") == "custom_field" for item in history_items)

        if event == "taskUpdated" and is_custom_field_change:
            task_id = str(task.get("id") or "")
            if not task_id:
                return JSONResponse(content={"status": "skipped", "reason": "missing task id"}, status_code=200)

            async def job():
                await handle_custom_field_change(task, history_items)

            await queue.enqueue(key=task_id, job_factory=job)

            return JSONResponse(
                content={"status": "scheduled", "task_id": task_id, "timestamp": timestamp},
                status_code=200
            )

        return JSONResponse(content={"status": "received"}, status_code=200)

    except Exception as e:
        error_filename = f"{LOG_DIR}/error_customfield_{datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')}.json"
        _save_json(error_filename, {"error": str(e), "payload": raw})
        return JSONResponse(content={"error": str(e)}, status_code=500)