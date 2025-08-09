from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from automations.task_created import handle_task_created

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional

from core.queue import queue

router = APIRouter()

LOG_DIR = "webhook_logs"
os.makedirs(LOG_DIR, exist_ok=True)

def _save_json(path: str, data: Dict[str, Any]):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

@router.post("/webhook/task-created")
async def task_created_webhook(request: Request):
    raw: Dict[str, Any] = {}
    try:
        raw = await request.json()

        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        filename = f"{LOG_DIR}/task_created_{timestamp}.json"
        _save_json(filename, raw)

        event: Optional[str] = raw.get("event")
        task: Dict[str, Any] = raw.get("task", {}) or {}

        # Only run for top-level tasks (no parent)
        if event == "taskCreated" and not task.get("parent"):
            task_id = str(task.get("id") or "")
            if not task_id:
                return JSONResponse(content={"status": "skipped", "reason": "missing task id"}, status_code=200)

            async def job():
                await handle_task_created(task)

            await queue.enqueue(key=task_id, job_factory=job)

            return JSONResponse(content={"status": "scheduled", "task_id": task_id, "timestamp": timestamp}, status_code=200)

        return JSONResponse(content={"status": "received"}, status_code=200)

    except Exception as e:
        error_filename = f"{LOG_DIR}/error_{datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')}.json"
        _save_json(error_filename, {"error": str(e), "payload": raw})
        return JSONResponse(content={"error": str(e)}, status_code=500)