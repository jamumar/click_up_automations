# automations/status_changed.py
from services.clickup import get_subtasks_from_task_details, update_task_status
from datetime import datetime
import asyncio
import os
import logging

LOG_FILE = "webhook_logs/status_update.log"
os.makedirs("webhook_logs", exist_ok=True)

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def log(msg: str):
    logger.info(msg)
    print(msg)

async def handle_status_change(task: dict, history_items: list):
    try:
        log("\U0001F680 handle_status_change() triggered.")

        task_id = task.get("id")
        new_status = task.get("status", {}).get("status")

        if not task_id or not new_status:
            log("\u26A0\uFE0F Missing task ID or new status in payload.")
            return

        log(f"\U0001F4CC Parent Task {task_id} changed status to '{new_status}'")

        # Get subtasks
        log(f"\U0001F4E1 Fetching subtasks for task ID {task_id}")
        subtasks = await get_subtasks_from_task_details(task_id)
        if not subtasks:
            log("\u2139\uFE0F No subtasks found.")
            return

        log(f"\U0001F501 Found {len(subtasks)} subtasks.")

        update_tasks = []
        for subtask in subtasks:
            subtask_id = subtask.get("id")
            log(f"\u27A1\uFE0F Updating subtask {subtask_id} to '{new_status}'")
            update_tasks.append(update_task_status(subtask_id, new_status))

        results = await asyncio.gather(*update_tasks)

        for i, result in enumerate(results):
            sub_id = subtasks[i].get("id")
            if result:
                log(f"\u2705 Subtask {sub_id} updated successfully.")
            else:
                log(f"\u274C Subtask {sub_id} update failed.")

    except Exception as e:
        log(f"\u274C Exception in handle_status_change: {str(e)}")
