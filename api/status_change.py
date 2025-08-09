from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from automations.status_changed import handle_status_change
import logging
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

@router.post("/webhook/status-change")
async def status_change_webhook(request: Request):
    raw_body: Dict[str, Any] = {}
    try:
        raw_body = await request.json()

        # Save full raw payload
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        filename = f"{LOG_DIR}/status_change_{timestamp}.json"
        _save_json(filename, raw_body)

        # Extract nested payload (ClickUp webhook style)
        payload = raw_body.get("payload", {}) or {}
        task_id: Optional[str] = payload.get("id")
        status = payload.get("status", {}).get("status")

        if not task_id or not status:
            logging.warning("⚠️ Missing task_id or status in webhook.")
            return JSONResponse(content={"status": "skipped"}, status_code=200)

        logging.info(f"🚨 Status Change Detected: Task {task_id} ➡ {status}")

        async def job():
            await handle_status_change(payload, history_items=[])

        await queue.enqueue(key=str(task_id), job_factory=job)

        return JSONResponse(content={"status": "scheduled", "task_id": task_id, "new_status": status, "timestamp": timestamp}, status_code=200)

    except Exception as e:
        error_filename = f"{LOG_DIR}/error_{datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')}.json"
        _save_json(error_filename, {"error": str(e), "payload": raw_body})
        logging.error(f"❌ Error: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)