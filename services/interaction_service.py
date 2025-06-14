import logging
from typing import Dict, Any, Optional
from utils.connection import active_tasks

from automation import interactTest

logger = logging.getLogger("TwitterAutomationAPI")

def run_interaction_task(status_callback, device_ip: str, u2_port: int, myt_rpc_port: int, 
                         duration_seconds: int, enable_liking: bool, enable_commenting: bool, 
                         comment_text: str) -> bool: 
    task_id = status_callback.task_id 
    logger.info(f"Interaction task for device {device_ip} (callback task_id: {task_id}) starting.") 
    device_info_prefix = f"Device {device_ip} (Callback Task {task_id}): "

    def wrapped_status_callback(message):
        status_callback(f"{device_info_prefix}{message}")

    try:
        success = interactTest.run_interaction(
            status_callback=wrapped_status_callback, 
            device_ip_address=device_ip,
            u2_port=u2_port,
            myt_rpc_port=myt_rpc_port,
            duration_seconds=duration_seconds,
            enable_liking_param=enable_liking,
            enable_commenting_param=enable_commenting,
            comment_text_param=comment_text
        )
        logger.info(f"Interaction task for device {device_ip} (callback task_id: {task_id}) completed. Success: {success}")
        status_callback(f"Interaction task {'completed successfully' if success else 'failed or completed with issues'}.")
        
        # For single mode, active_tasks[task_id] would be updated.
        # For batch mode, this task_id is temp_sub_task_id_for_callback and not directly in active_tasks for master status.
        if not status_callback.task_id.startswith(tuple(active_tasks.keys())[0] if active_tasks else "") : 
             if status_callback.task_id in active_tasks: 
                 active_tasks[status_callback.task_id]["status"] = "completed" if success else "failed"
        return success
    except Exception as e:
        logger.error(f"Exception in interaction task for device {device_ip} (callback task_id: {task_id}): {e}", exc_info=True)
        status_callback(f"Error during interaction: {str(e)}")
        if not status_callback.task_id.startswith(tuple(active_tasks.keys())[0] if active_tasks else "") :
             if status_callback.task_id in active_tasks:
                 active_tasks[status_callback.task_id]["status"] = "error"
        return False
    finally:
        # Similar to above, status update for single task.
        if not status_callback.task_id.startswith(tuple(active_tasks.keys())[0] if active_tasks else "") :
            if status_callback.task_id in active_tasks: 
                current_status = active_tasks[status_callback.task_id].get("status", "unknown")
                if current_status not in ["completed", "failed", "error", "timeout", "cancelled"]:
                    active_tasks[status_callback.task_id]["status"] = "finished_unknown" 
                logger.info(f"Interaction task for device {device_ip} (callback task_id: {task_id}) processing finished with status: {active_tasks[status_callback.task_id].get('status', 'unknown')}.") 