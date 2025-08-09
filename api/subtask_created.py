from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from automations.subtask_created import handle_subtask_creation
import logging
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional

from core.queue import queue

router = APIRouter()

LOG_DIR = "webhook_logs"
os.makedirs(LOG_DIR, exist_ok=True)

def setup_logger():
    logger = logging.getLogger("webhook")
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

def _save_json(path: str, data: Dict[str, Any]):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

@router.post("/webhook/subtask-created")
async def subtask_created_webhook(request: Request):
    raw_body: Dict[str, Any] = {}
    try:
        # Parse and log incoming request
        raw_body = await request.json()
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        
        # Save raw payload for debugging
        _save_json(f"{LOG_DIR}/subtask_created_{timestamp}.json", raw_body)
        
        # Extract required data
        payload = raw_body.get("payload", {}) or {}
        subtask_id: Optional[str] = payload.get("id")
        parent_task_id: Optional[str] = payload.get("parent")
        
        if not subtask_id or not parent_task_id:
            error_msg = "Missing subtask_id or parent_task_id in payload"
            webhook_logger.warning(error_msg)
            return JSONResponse(
                content={
                    "status": "skipped",
                    "reason": error_msg,
                    "received_data": {
                        "subtask_id": subtask_id,
                        "parent_task_id": parent_task_id
                    }
                },
                status_code=200
            )
        
        webhook_logger.info(f"[QUEUE] Subtask created {subtask_id} (Parent: {parent_task_id})")
        
        # Enqueue coalesced by parent to avoid duplicate copy attempts
        async def job():
            await handle_subtask_creation(subtask_id, parent_task_id)
        
        await queue.enqueue(key=str(parent_task_id), job_factory=job)
        
        return JSONResponse(
            content={
                "status": "scheduled",
                "subtask_id": subtask_id,
                "parent_task_id": parent_task_id,
                "timestamp": timestamp
            },
            status_code=200
        )
        
    except json.JSONDecodeError:
        error_msg = "Invalid JSON payload"
        webhook_logger.error(error_msg)
        return JSONResponse(
            content={"status": "error", "message": error_msg},
            status_code=400
        )
        
    except Exception as e:
        error_msg = str(e)
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
        
        webhook_logger.error(f"Webhook error: {error_msg}")
        
        # Save error details
        _save_json(f"{LOG_DIR}/error_{timestamp}.json", {
            "error": error_msg,
            "payload": raw_body,
            "timestamp": timestamp
        })
        
        return JSONResponse(
            content={
                "status": "error",
                "message": error_msg,
                "timestamp": timestamp
            },
            status_code=500
        )