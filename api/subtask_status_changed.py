from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from automations.subtask_status_changed import handle_subtask_status_changed
import logging
import os
import json
from datetime import datetime
from typing import Any, Dict, Optional
from core.config import CLICKUP_TEAM_ID
from core.queue import queue

router = APIRouter()

LOG_DIR = "webhook_logs"
os.makedirs(LOG_DIR, exist_ok=True)

def setup_logger():
    logger = logging.getLogger("webhook_subtask_status_changed")
    logger.setLevel(logging.INFO)
    if not any(getattr(h, "baseFilename", "").endswith("webhook_requests.log") for h in logger.handlers if hasattr(h, "baseFilename")):
        handler = logging.FileHandler(f"{LOG_DIR}/webhook_requests.log")
        handler.setFormatter(logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(handler)
    return logger

webhook_logger = setup_logger()

def save_json(path: str, data: Dict[str, Any]):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

async def _schedule(request: Request):
    raw_body: Dict[str, Any] = {}
    try:
        raw_body = await request.json()
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        save_json(f"{LOG_DIR}/subtask_status_changed_{timestamp}.json", raw_body)

        payload = raw_body.get("payload", {})
        subtask_id: Optional[str] = payload.get("id")
        parent_task_id: Optional[str] = payload.get("parent")
        team_id: Optional[str] = payload.get("team_id") or CLICKUP_TEAM_ID or "20420318"

        if not subtask_id or not parent_task_id:
            msg = "Missing subtask_id or parent_task_id in payload"
            webhook_logger.warning(msg)
            return JSONResponse(
                content={"status": "skipped", "reason": msg, "received_data": {"subtask_id": subtask_id, "parent_task_id": parent_task_id}},
                status_code=200
            )

        webhook_logger.info(f"[QUEUE] Subtask status changed: subtask={subtask_id}, parent={parent_task_id}, team={team_id}")

        # Enqueue a coalesced job keyed by parent_task_id
        async def job():
            await handle_subtask_status_changed(subtask_id=subtask_id, parent_task_id=parent_task_id, team_id=team_id)

        await queue.enqueue(key=parent_task_id, job_factory=job)

        return JSONResponse(
            content={"status": "scheduled", "subtask_id": subtask_id, "parent_task_id": parent_task_id, "timestamp": timestamp},
            status_code=200
        )

    except json.JSONDecodeError:
        error_msg = "Invalid JSON payload"
        webhook_logger.error(error_msg)
        return JSONResponse(content={"status": "error", "message": error_msg}, status_code=400)
    except Exception as e:
        error_msg = str(e)
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        webhook_logger.error(f"Webhook error: {error_msg}")
        save_json(f"{LOG_DIR}/error_subtask_status_changed_{timestamp}.json", {"error": error_msg, "payload": raw_body, "timestamp": timestamp})
        return JSONResponse(content={"status": "error", "message": error_msg, "timestamp": timestamp}, status_code=500)

@router.post("/webhook/subtask-status-changed")
async def subtask_status_changed_webhook(request: Request):
    return await _schedule(request)

@router.post("/subtask-status-changed")
async def subtask_status_changed_webhook_alias(request: Request):
    return await _schedule(request)