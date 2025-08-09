# services/clickup.py

import httpx
import os
import logging
from typing import Optional, List, Dict, Any
from core.config import CLICKUP_API_TOKEN, CLICKUP_TEAM_ID, CLICKUP_LIST_ID
import json
import requests

LOG_FILE = "webhook_logs/status_update.log"
os.makedirs("webhook_logs", exist_ok=True)

FIELDS_TO_COPY = {
    "3e1ac1d5-15ef-48c0-a666-37233c10d998": "Parent Task name",
    "bad587f3-e81b-45dc-9f38-28eed14c9e6e": "Parts cost",
    "d2f1b2ca-7236-4d2c-9814-90d9a3b3e041": "SKU",
    "dbed7e4e-1995-417a-b8eb-d73e7f1d7a80": "MACHINE MODEL",
    "1bab94c1-eeff-455c-adfe-20e6079b275d": "Machine Brand"
}
logger = logging.getLogger(__name__)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
CLICKUP_API_URL = "https://api.clickup.com/api/v2"
CLICKUP_API_BASE_URL = "https://api.clickup.com/api/v2"

def log(msg: str):
    logger.info(msg)
    print(msg)

HEADERS = {
    "Authorization": str(CLICKUP_API_TOKEN) if CLICKUP_API_TOKEN else "",
    "Content-Type": "application/json"
}

async def get_task_details(task_id: str):
    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=HEADERS)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        log(f"❌ Failed to fetch task details for {task_id}: {str(e)}")
        return {}

async def get_subtasks_from_task_details(task_id: str, team_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch the task with include_subtasks=true and return the 'subtasks' array.

    Some workspaces require a team_id to be passed for this endpoint to return subtasks.
    """
    team = team_id or CLICKUP_TEAM_ID
    url = f"{CLICKUP_API_URL}/task/{task_id}?include_subtasks=true"
    if team:
        url += f"&team_id={team}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            return data.get("subtasks", [])
    except httpx.HTTPStatusError as e:
        try:
            body = e.response.text
        except Exception:
            body = "<no body>"
        log(f"❌ Error fetching task details (with subtasks) for {task_id}: {e.response.status_code} - {body}")
        return []
    except Exception as e:
        log(f"❌ Error fetching task details (with subtasks) for {task_id}: {str(e)}")
        return []

async def get_subtasks(parent_task_id: str):
    """Fetch subtasks of a given task (may 404 for some workspaces/endpoints). Prefer get_subtasks_from_task_details."""
    url = f"https://api.clickup.com/api/v2/task/{parent_task_id}/subtask"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            return data.get("tasks", [])
    except Exception as e:
        log(f"❌ Error fetching subtasks for {parent_task_id}: {str(e)}")
        return []

async def update_task_status(task_id: str, new_status: str):
    """Update the status of a given task"""
    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    payload = {"status": new_status}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.put(url, headers=HEADERS, json=payload)
            if response.status_code == 200:
                return True
            else:
                log(f"⚠️ Failed to update status for {task_id}: {response.text}")
                return False
    except Exception as e:
        log(f"❌ Exception updating status for {task_id}: {str(e)}")
        return False