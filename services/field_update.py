import httpx
import os
import logging
import asyncio
from core.config import CLICKUP_API_TOKEN
from typing import List, Dict, Any, Optional, Tuple

LOG_FILE = "webhook_logs/clickup_service.log"
os.makedirs("webhook_logs", exist_ok=True)

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO, # Keep INFO level for file logging of key events
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def log(msg: str, level: str = "info"):
    # Removed print statements for cleaner console output
    getattr(logger, level)(msg)

CLICKUP_API_URL = "https://api.clickup.com/api/v2"
HEADERS = {
    "Authorization": str(CLICKUP_API_TOKEN) if CLICKUP_API_TOKEN else "",
    "Content-Type": "application/json"
}

async def get_task_details(task_id: str, team_id: str = "20420318") -> Optional[Dict]:
    """Get complete task details with team_id parameter"""
    url = f"{CLICKUP_API_URL}/task/{task_id}?team_id={team_id}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=HEADERS)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        log(f"HTTP error fetching task {task_id} - {e.response.status_code} {e.response.text}", "error")
    except Exception as e:
        log(f"Error fetching task {task_id} - {str(e)}", "error")
    return None

# Removed get_custom_field_config function as it's no longer needed and was problematic.

def format_field_value(value: Any, field_type: Optional[str] = None) -> Any:
    """Format field values according to their type for sending to ClickUp.
    For dropdowns, expects the value to be the option ID (UUID string).
    """
    if value is None:
        return ""
    if field_type == "checkbox":
        return str(bool(value)).lower()
    # If the value is already a dict with 'id' (e.g., from a previous get_task_details), extract it.
    # Otherwise, assume it's already the correct ID string for dropdowns.
    if field_type == "drop_down" and isinstance(value, dict) and "id" in value:
        return value["id"]
    return value # For other types, or if dropdown value is already a string ID

async def update_single_field(task_id: str, field_id: str, value: Any, field_type: str = "", team_id: str = "20420318") -> bool:
    """Enhanced field updater with direct value handling."""
    url = f"{CLICKUP_API_URL}/task/{task_id}/field/{field_id}?team_id={team_id}"
    
    # The value passed here should already be correctly formatted by prepare_fields_for_update
    # For dropdowns, it should be the UUID of the option.
    payload = {"value": format_field_value(value, field_type)}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=HEADERS, json=payload)
            
            if response.status_code == 200:
                log(f"Successfully updated field {field_id} (Type: {field_type}) with value: {payload['value']}", "info") # Changed from debug to info
                return True
            
            log(f"Failed to update field {field_id} (Type: {field_type}) with value: {payload['value']}. Status: {response.status_code} - Response: {response.text}", "warning")
            return False
            
    except Exception as e:
        log(f"Error updating field {field_id}: {str(e)}", "error")
        return False

async def update_task_fields(task_id: str, fields: List[Dict], team_id: str = "20420318") -> bool:
    """Update multiple fields using individual field updates"""
    if not fields:
        log("No fields to update", "info")
        return True

    results = []
    for field in fields:
        success = await update_single_field(
            task_id=task_id,
            field_id=field["id"],
            value=field["value"],
            field_type=field.get("type") or "",
            team_id=team_id
        )
        results.append(success)
        
        # Small delay between updates to avoid rate limiting
        if len(fields) > 1:
            await asyncio.sleep(0.5)
    
    return all(results)

async def verify_field_updates(task_id: str, expected_fields: List[Dict], team_id: str = "20420318", return_failed: bool = False) -> Tuple[bool, List[Dict]]:
    """Enhanced verification with robust dropdown value resolution, optionally returning failed fields."""
    task_data = await get_task_details(task_id, team_id)
    if not task_data:
        log(f"Could not fetch task {task_id} for verification.", "error")
        return False, expected_fields if return_failed else []
    
    current_fields_map = {f["id"]: f for f in task_data.get("custom_fields", [])}
    all_success = True
    failed_fields_list = []
    
    for expected_field in expected_fields:
        field_id = expected_field["id"]
        field_name = expected_field.get("name", field_id)
        expected_type = expected_field.get("type")
        expected_value_for_update = expected_field["value"] # This is the UUID for dropdowns
        
        current_field = current_fields_map.get(field_id)
        
        if not current_field:
            log(f"Field {field_name} ({field_id}) not found in task after update.", "warning")
            all_success = False
            if return_failed:
                failed_fields_list.append(expected_field)
            continue
        
        current_value_raw = current_field.get("value")
        current_field_type = current_field.get("type")
        
        # Removed verbose debug logging for verification
        # log(f"DEBUG: Verifying field '{field_name}' (ID: {field_id}, Type: {expected_type}). Expected value (for update): '{expected_value_for_update}'. Current raw value from ClickUp: '{current_value_raw}' (Type: {type(current_value_raw)})", "debug")

        if expected_type == "drop_down":
            current_option_id = None
            current_field_options = current_field.get("type_config", {}).get("options", [])

            if isinstance(current_value_raw, dict) and "id" in current_value_raw:
                current_option_id = current_value_raw["id"]
            elif isinstance(current_value_raw, int): # It's an orderindex
                for opt in current_field_options:
                    if opt.get("orderindex") == current_value_raw:
                        current_option_id = opt.get("id")
                        break
            elif isinstance(current_value_raw, str): # It could be the ID or the name
                for opt in current_field_options:
                    if str(opt.get("id")) == current_value_raw:
                        current_option_id = opt.get("id")
                        break
                if not current_option_id:
                    for opt in current_field_options:
                        if opt.get("name") == current_value_raw:
                            current_option_id = opt.get("id")
                            break
            
            if str(expected_value_for_update) != str(current_option_id):
                log(f"Field {field_name} verification failed. Expected ID: '{expected_value_for_update}', Got resolved ID: '{current_option_id}' (Raw from ClickUp: {current_value_raw})", "warning")
                all_success = False
                if return_failed:
                    failed_fields_list.append(expected_field)
            else:
                log(f"Field {field_name} verified successfully. Value ID: '{current_option_id}'", "info")

        else: # For other field types (short_text, currency, etc.)
            expected_value_formatted = str(format_field_value(expected_value_for_update, expected_type))
            current_value_formatted = str(format_field_value(current_value_raw, current_field_type))
            
            if expected_value_formatted != current_value_formatted:
                log(f"Field {field_name} verification failed. Expected: '{expected_value_formatted}', Got: '{current_value_formatted}' (Raw: {current_value_raw})", "warning")
                all_success = False
                if return_failed:
                    failed_fields_list.append(expected_field)
            else:
                log(f"Field {field_name} verified successfully. Value: '{current_value_formatted}'", "info")
    
    return all_success, failed_fields_list

async def log_current_field_states(task_id: str, field_ids: List[str], team_id: str = "20420318"):
    """Log current state of specific fields for debugging"""
    task_data = await get_task_details(task_id, team_id)
    if not task_data:
        log(f"Could not fetch task {task_id} for field logging", "error")
        return
    
    log(f"Current field states for task {task_id}:", "info")
    for field in task_data.get("custom_fields", []):
        if field.get("id") in field_ids:
            log(f"  - {field.get('name')} ({field.get('id')}): {field.get('value')} (Type: {field.get('type')})", "info")
