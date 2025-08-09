# services/clickup_client.py
import httpx
from core.config import CLICKUP_API_TOKEN

async def get_task_details(task_id: str):
    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    headers = {"Authorization": str(CLICKUP_API_TOKEN) if CLICKUP_API_TOKEN is not None else ""}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        return response.json()
