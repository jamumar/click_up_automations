import logging
import os
import asyncio
from typing import List, Dict, Any
from services.field_update import (
    get_task_details,
    update_task_fields,
    verify_field_updates,
    log_current_field_states
)

LOG_FILE = "webhook_logs/subtask_automation.log"
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

# Field configuration - update with your actual field IDs
FIELD_MAPPING = {
    "a3c18f71-d0ff-4a11-b086-0d441a656d35": "Parent Task Name (Auto)",
    "bad587f3-e81b-45dc-9f38-28eed14c9e6e": "Parts cost",
    "d2f1b2ca-7236-4d2c-9814-90d9a3b3e041": "SKU",
    "dbed7e4e-1995-417a-b8eb-d73e7f1d7a80": "MACHINE MODEL",
    "1bab94c1-eeff-455c-adfe-20e6079b275d": "Machine Brand"
}

def prepare_fields_for_update(parent_fields: List[Dict]) -> List[Dict]:
    """Enhanced field preparation with dynamic dropdown option resolution."""
    fields_to_update = []
    
    for field in parent_fields:
        field_id = field.get("id")
        field_name = field.get("name", "Unknown Field")
        
        if field_id not in FIELD_MAPPING:
            # Removed verbose debug logging for skipped fields
            continue
        
        value = field.get("value")
        field_type = field.get("type")
        
        # Removed verbose debug logging for processing fields
        # log(f"Processing field '{field_name}' ({field_id}, Type: {field_type}, Value: {value})", "debug")

        # Skip None values except for checkboxes (where None might mean unchecked)
        if value is None and field_type != "checkbox":
            # Removed verbose debug logging for skipped None values
            continue
        
        # Special handling for dropdown fields
        if field_type == "drop_down":
            # Get the options directly from the parent field's type_config
            options_from_parent_field = field.get("type_config", {}).get("options", [])
            
            target_option_id = None
            
            # Determine the selected option's ID from the parent task's value
            if isinstance(value, int): # Value is an orderindex
                for opt in options_from_parent_field:
                    if opt.get("orderindex") == value:
                        target_option_id = opt.get("id")
                        # Removed verbose debug logging for resolved dropdowns
                        # log(f"Resolved dropdown '{field_name}' by orderindex {value} to ID: {target_option_id}", "debug")
                        break
            elif isinstance(value, dict) and "id" in value: # Value is a dict with 'id'
                target_option_id = value["id"]
                # Removed verbose debug logging for resolved dropdowns
                # log(f"Resolved dropdown '{field_name}' by direct ID in dict: {target_option_id}", "debug")
            elif isinstance(value, str): # Value is a string (could be name or ID)
                # Try to match by ID first
                for opt in options_from_parent_field:
                    if str(opt.get("id")) == value:
                        target_option_id = opt.get("id")
                        break
                # If not found by ID, try to match by name
                if not target_option_id:
                    for opt in options_from_parent_field:
                        if opt.get("name") == value:
                            target_option_id = opt.get("id")
                            break
            
            if not target_option_id:
                log(f"Could not resolve target option ID for dropdown '{field_name}' ({field_id}) from value: {value}. This option might not exist or value format is unexpected.", "warning")
                continue
            
            value_to_set = target_option_id
        else:
            value_to_set = value

        fields_to_update.append({
            "id": field_id,
            "value": value_to_set if value_to_set is not None else False, # Default to False for checkbox if None
            "type": field_type,
            "name": FIELD_MAPPING[field_id]
        })
    
    return fields_to_update

async def handle_subtask_creation(subtask_id: str, parent_task_id: str, team_id: str = "20420318") -> bool:
    """Complete field update workflow with enhanced debugging and retry for failed dropdowns."""
    try:
        log(f"Starting field copy from parent {parent_task_id} to subtask {subtask_id}", "info")
        
        parent_task = await get_task_details(parent_task_id, team_id)
        if not parent_task:
            log(f"Parent task {parent_task_id} not found or could not be fetched.", "error")
            return False
        
        log(f"Fetched parent task {parent_task_id} details. Custom fields found: {len(parent_task.get('custom_fields', []))}", "info")
        
        fields_to_update = prepare_fields_for_update(parent_task.get("custom_fields", []))
        
        if not fields_to_update:
            log("No fields to copy after preparation.", "info")
            return True
        
        log(f"Prepared {len(fields_to_update)} fields for update on subtask {subtask_id}: {fields_to_update}", "info")
        
        await log_current_field_states(subtask_id, [f["id"] for f in fields_to_update], team_id)

        # Initial update attempt
        update_success = await update_task_fields(subtask_id, fields_to_update, team_id)
        
        if not update_success:
            log(f"Initial attempt: Failed to update some fields for subtask {subtask_id}.", "warning")
        
        # Initial verification
        initial_verify_success, failed_fields = await verify_field_updates(subtask_id, fields_to_update, team_id, return_failed=True)

        if initial_verify_success:
            log(f"All specified fields successfully verified for subtask {subtask_id} after initial attempt.", "info")
            return True
        else:
            log(f"Some field updates could not be verified for subtask {subtask_id} after initial attempt. Failed fields: {[f['name'] for f in failed_fields]}", "warning")
            
            # Retry logic for failed dropdowns
            dropdown_retries = 0
            max_dropdown_retries = 2
            retry_delay_seconds = 1 # seconds

            failed_dropdown_fields = [f for f in failed_fields if f.get("type") == "drop_down"]

            while failed_dropdown_fields and dropdown_retries < max_dropdown_retries:
                dropdown_retries += 1
                log(f"Retrying failed dropdown fields (Attempt {dropdown_retries}/{max_dropdown_retries}): {[f['name'] for f in failed_dropdown_fields]}", "info")
                await asyncio.sleep(retry_delay_seconds) # Wait before retrying

                # Only retry updating the specific failed dropdowns
                retry_update_success = await update_task_fields(subtask_id, failed_dropdown_fields, team_id)
                if not retry_update_success:
                    log(f"Retry attempt {dropdown_retries}: Failed to update some dropdown fields for subtask {subtask_id}.", "warning")
                
                # Re-verify only the retried fields
                retry_verify_success, newly_failed_fields = await verify_field_updates(subtask_id, failed_dropdown_fields, team_id, return_failed=True)
                
                if retry_verify_success:
                    log(f"All retried dropdown fields successfully verified after attempt {dropdown_retries}.", "info")
                    # Clear the list if all passed
                    failed_dropdown_fields = [] 
                else:
                    log(f"Retry attempt {dropdown_retries}: Some dropdown fields still failed verification. Remaining failed: {[f['name'] for f in newly_failed_fields]}", "warning")
                    failed_dropdown_fields = newly_failed_fields # Update list of fields that still need retry

            if not failed_dropdown_fields:
                log(f"All specified fields (including retried dropdowns) successfully verified for subtask {subtask_id}.", "info")
                return True
            else:
                log(f"Final verification failed for some fields after retries for subtask {subtask_id}. Unresolved fields: {[f['name'] for f in failed_dropdown_fields]}", "error")
                return False
        
    except Exception as e:
        log(f"Field copy failed for subtask {subtask_id}: {str(e)}", "error")
        return False
