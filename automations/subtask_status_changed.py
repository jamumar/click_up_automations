import logging
import os
import asyncio
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import List, Dict, Any, Optional, Tuple

from services.clickup import get_subtasks_from_task_details
from services.field_update import (
    get_task_details,
    update_single_field,
    verify_field_updates,
)

LOG_FILE = "webhook_logs/subtask_status_sum.log"
os.makedirs("webhook_logs", exist_ok=True)

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.FileHandler(LOG_FILE)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

def log(msg: str, level: str = "info"):
    getattr(logger, level)(msg)

# Custom Field IDs (from your workspace)
PARTS_COST_FIELD_ID = "bad587f3-e81b-45dc-9f38-28eed14c9e6e"        # "Parts cost" (currency)
TOTAL_PARTS_COST_FIELD_ID = "7ba61d6a-6b79-49c3-9e6d-1fd1e30310cc"   # "Total Parts Cost" (currency)

def _safe_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")

def _format_currency_str(amount: Decimal) -> str:
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantized:.2f}"

async def _fetch_subtask_parts_costs(subtask_ids: List[str], team_id: str) -> List[Decimal]:
    results: List[Decimal] = []

    sem = asyncio.Semaphore(6)  # limit concurrency to avoid rate limits

    async def fetch_and_extract(sub_id: str) -> Decimal:
        async with sem:
            data = await get_task_details(sub_id, team_id)
        if not data:
            log(f"Could not fetch details for subtask {sub_id}", "warning")
            return Decimal("0")
        for cf in data.get("custom_fields", []):
            if cf.get("id") == PARTS_COST_FIELD_ID:
                return _safe_decimal(cf.get("value"))
        return Decimal("0")

    fetched = await asyncio.gather(*(fetch_and_extract(sid) for sid in subtask_ids), return_exceptions=True)
    for idx, item in enumerate(fetched):
        if isinstance(item, Exception):
            log(f"Error fetching subtask {subtask_ids[idx]} parts cost: {str(item)}", "warning")
            results.append(Decimal("0"))
        else:
            results.append(item)

    return results

async def handle_subtask_status_changed(subtask_id: str, parent_task_id: str, team_id: str = "20420318") -> Tuple[bool, Dict[str, Any]]:
    """
    On subtask status change:
      1) Get all subtasks of the parent via include_subtasks=true (+ team_id).
      2) Sum their 'Parts cost' currency field.
      3) Update the parent's 'Total Parts Cost' currency field with the sum.
      4) Verify the update and retry once if needed.
    """
    try:
        log(f"Starting parts cost aggregation. parent={parent_task_id}, triggered_by_subtask={subtask_id}, team_id={team_id}")

        # 1) Collect subtasks using include_subtasks=true and team_id
        subtasks = await get_subtasks_from_task_details(parent_task_id, team_id=team_id)  # each subtask has 'id'
        subtask_ids = [t.get("id") for t in subtasks if t.get("id")]
        log(f"Found {len(subtask_ids)} subtasks for parent {parent_task_id}")

        # If the parent has no subtasks, set total to 0.00
        if not subtask_ids:
            total_cost_str = _format_currency_str(Decimal("0"))
            update_ok = await update_single_field(
                task_id=parent_task_id,
                field_id=TOTAL_PARTS_COST_FIELD_ID,
                value=total_cost_str,
                field_type="currency",
                team_id=team_id
            )
            verify_ok, _ = await verify_field_updates(
                task_id=parent_task_id,
                expected_fields=[{
                    "id": TOTAL_PARTS_COST_FIELD_ID,
                    "value": total_cost_str,
                    "name": "Total Parts Cost",
                    "type": "currency"
                }],
                team_id=team_id
            )
            if not update_ok or not verify_ok:
                log(f"Failed to update/verify Total Parts Cost=0.00 on parent {parent_task_id}", "error")
            return update_ok and verify_ok, {
                "parent_task_id": parent_task_id,
                "subtask_count": 0,
                "total_parts_cost": total_cost_str,
                "verified": update_ok and verify_ok
            }

        # 2) Fetch each subtask and extract Parts cost
        parts_costs = await _fetch_subtask_parts_costs(subtask_ids, team_id)
        total = sum(parts_costs, start=Decimal("0"))
        total_cost_str = _format_currency_str(total)
        log(f"Computed Total Parts Cost from {len(parts_costs)} subtasks: {total_cost_str}")

        # 3) Update parent Total Parts Cost
        update_ok = await update_single_field(
            task_id=parent_task_id,
            field_id=TOTAL_PARTS_COST_FIELD_ID,
            value=total_cost_str,
            field_type="currency",
            team_id=team_id
        )

        # 4) Verify with a small retry if needed
        verify_ok, failed = await verify_field_updates(
            task_id=parent_task_id,
            expected_fields=[{
                "id": TOTAL_PARTS_COST_FIELD_ID,
                "value": total_cost_str,
                "name": "Total Parts Cost",
                "type": "currency"
            }],
            team_id=team_id,
            return_failed=True
        )

        if not verify_ok:
            log("Verification failed. Retrying update once after short delay...", "warning")
            await asyncio.sleep(0.8)
            retry_ok = await update_single_field(
                task_id=parent_task_id,
                field_id=TOTAL_PARTS_COST_FIELD_ID,
                value=total_cost_str,
                field_type="currency",
                team_id=team_id
            )
            verify_ok, failed = await verify_field_updates(
                task_id=parent_task_id,
                expected_fields=[{
                    "id": TOTAL_PARTS_COST_FIELD_ID,
                    "value": total_cost_str,
                    "name": "Total Parts Cost",
                    "type": "currency"
                }],
                team_id=team_id,
                return_failed=True
            )
            if not verify_ok:
                log(f"Final verification failed for parent {parent_task_id} total={total_cost_str}", "error")
                return False, {
                    "parent_task_id": parent_task_id,
                    "total_parts_cost": total_cost_str,
                    "verified": False,
                    "failed_fields": [f.get("id") for f in failed]
                }

        log(f"Successfully updated and verified Total Parts Cost on parent {parent_task_id} = {total_cost_str}")
        return True, {
            "parent_task_id": parent_task_id,
            "subtask_count": len(subtask_ids),
            "total_parts_cost": total_cost_str,
            "verified": True
        }

    except Exception as e:
        log(f"Exception in handle_subtask_status_changed: {str(e)}", "error")
        return False, {"error": str(e), "parent_task_id": parent_task_id, "subtask_id": subtask_id}