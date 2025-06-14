import logging
import asyncio
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List

from utils.callbacks import SynchronousStatusCallback, WebSocketStatusCallback
from utils.connection import active_tasks, manager
from schemas.models import LoginRequest, LoginResponse, BatchLoginRequest
from services.login_service import run_login_task

logger = logging.getLogger("TwitterAutomationAPI")

router = APIRouter(tags=["login"])
executor = ThreadPoolExecutor(max_workers=10)

@router.post("/api/single-account-login", response_model=LoginResponse)
async def single_account_login(request: LoginRequest):
    logger.info(f"Received single account login request for user: {request.username} on device: {request.deviceIp}")
    
    status_collector = SynchronousStatusCallback()

    try:
        # Ensure ports are integers
        u2_port_int = int(request.u2Port)
        myt_rpc_port_int = int(request.mytRpcPort)
    except ValueError:
        logger.error("Invalid port number provided. Ports must be integers.")
        return LoginResponse(success=False, message="Invalid port number. Ports must be integers.", status="Error")

    try:
        success, error_message = await run_login_task(
            status_collector,
            request.deviceIp,
            u2_port_int,
            myt_rpc_port_int,
            request.username,
            request.password,
            request.secretKey
        )
        
        all_messages = status_collector.get_all_messages()
        final_progress = status_collector.thread.progress_value if hasattr(status_collector.thread, 'progress_value') else status_collector.progress

        if success:
            logger.info(f"Single account login successful for {request.username}")
            return LoginResponse(
                success=True, 
                message=f"Login successful for {request.username}.", 
                status=all_messages,
                progress=final_progress
            )
        else:
            logger.warning(f"Single account login failed for {request.username}")
            return LoginResponse(
                success=False, 
                message=error_message or f"Login failed for {request.username}.", 
                status=all_messages + (f"\n详细错误: {error_message}" if error_message else ""),
                progress=final_progress
            )
    except Exception as e:
        logger.error(f"Exception during single account login for {request.username}: {e}", exc_info=True)
        return LoginResponse(
            success=False, 
            message=f"An unexpected error occurred: {str(e)}", 
            status=status_collector.get_all_messages() + f"\nException: {str(e)}",
            progress=status_collector.thread.progress_value if hasattr(status_collector.thread, 'progress_value') else status_collector.progress
        )

@router.post("/batch-login")
async def batch_login(request: BatchLoginRequest):
    if not request.device_users:
        raise HTTPException(status_code=400, detail="没有选择设备")
    
    task_id = str(uuid.uuid4())
    active_tasks[task_id] = {
        "status": "starting", 
        "cancel_flag": asyncio.Event(), 
        "start_time": datetime.now(),
        "total_devices": len(request.device_users),
        "completed_devices": 0,
        "successful_devices": 0,
        "failed_devices": 0,
        "suspended_accounts": 0,  # New counter for suspended accounts
        "device_results": []
    }
    logger.info(f"Starting batch login task {task_id} for {len(request.device_users)} devices. (active_tasks keys: {list(active_tasks.keys())})")
    loop = asyncio.get_running_loop()

    async def process_single_device_login(device_data, task_id_str, loop_ref):
        device_id_for_log = getattr(device_data, 'device_name', None) or getattr(device_data, 'device_ip', None)
        await manager.send_message(task_id_str, f"开始处理设备: {device_id_for_log}")
        websocket_for_task = manager.active_connections.get(task_id_str)
        current_device_callback = WebSocketStatusCallback(websocket_for_task, task_id_str, loop_ref)
        try:
            success, error_message = await run_login_task(
                current_device_callback, 
                device_data.device_ip,
                device_data.u2_port,
                device_data.myt_rpc_port,
                device_data.username,
                device_data.password,
                device_data.secret_key
            )
            return device_id_for_log, success, error_message
        except Exception as e_device_task:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Batch task {task_id_str}, device {device_id_for_log}: Error during login - {e_device_task}\n{tb}", exc_info=True)
            await manager.send_message(task_id_str, f"设备 {device_id_for_log} 处理时发生内部错误: {e_device_task}", "status")
            return device_id_for_log, False, f"Exception: {e_device_task}\n{tb}"

    async def process_batch_concurrently():
        try:
            login_coroutines = []
            for device_data in request.device_users:
                if active_tasks[task_id]["cancel_flag"].is_set():
                    logger.info(f"Batch task {task_id} cancelled before starting all devices.")
                    await manager.send_message(task_id, f"任务 {task_id} 已取消，跳过剩余设备。")
                    break
                login_coroutines.append(process_single_device_login(device_data, task_id, loop))
            results = await asyncio.gather(*login_coroutines, return_exceptions=True)
            for i, result in enumerate(results):
                original_device_data = request.device_users[i]
                device_id_for_result = getattr(original_device_data, 'id', None)
                device_name_for_result = getattr(original_device_data, 'device_name', None) or getattr(original_device_data, 'device_ip', None)
                success_flag = False
                error_msg = ""
                if isinstance(result, Exception):
                    logger.error(f"Batch task {task_id}, device {device_name_for_result} (ID: {device_id_for_result}): Exception during login - {result}", exc_info=True)
                    error_msg = str(result)
                elif isinstance(result, tuple) and (len(result) == 3):
                    _logged_identifier, success_flag, error_msg = result
                elif isinstance(result, tuple) and len(result) == 2:
                    _logged_identifier, success_flag = result
                else:
                    logger.error(f"Batch task {task_id}, device {device_name_for_result} (ID: {device_id_for_result}): Unexpected result format - {result}")
                    error_msg = "Unexpected result format from login task"
                # Check if the error message indicates a suspended account
                is_suspended_account = any(word in error_msg.lower() for word in ["suspend", "封停"]) if error_msg else False
                
                # If account is suspended, mark with a specific flag but count as failure
                login_status = "success" if success_flag else ("suspended" if is_suspended_account else "failed")
                
                active_tasks[task_id]["device_results"].append({
                    "device_id": device_id_for_result,
                    "device_name": device_name_for_result,
                    "login_status": login_status,
                    "error_message": error_msg if not success_flag else "",
                    "account_status": "suspended" if is_suspended_account else ("active" if success_flag else "unknown")
                })
                active_tasks[task_id]["completed_devices"] += 1
                current_device_result = active_tasks[task_id]["device_results"][i]
                login_status = current_device_result["login_status"]
                device_id_for_log_from_details = current_device_result["device_name"]
                
                # Only count 'success' as success; 'suspended' and 'failed' are both failures
                success_flag_from_details = login_status == "success"
                
                if success_flag_from_details:
                    active_tasks[task_id]["successful_devices"] += 1
                else:
                    active_tasks[task_id]["failed_devices"] += 1
                    # Track suspended accounts separately
                    if login_status == "suspended":
                        active_tasks[task_id]["suspended_accounts"] += 1
                
                # Customize status message based on login status
                status_message = "登录成功"
                if login_status == "suspended":
                    status_message = "账户已封停 (登录失败)"
                elif login_status == "failed":
                    status_message = "登录失败"
                    
                status_msg_device = f"设备 {device_id_for_log_from_details}: {status_message}"
                logger.info(f"Batch task {task_id}: {status_msg_device}")
                await manager.send_message(task_id, status_msg_device, "status")
                await manager.send_message(task_id, status_msg_device, "device_completed") 
            final_status_msg_key = "completed"
            final_status_text = f"批量登录处理完成. 总数: {active_tasks[task_id]['total_devices']}, 成功: {active_tasks[task_id]['successful_devices']}, 失败: {active_tasks[task_id]['failed_devices']}."
            if active_tasks[task_id]["cancel_flag"].is_set():
                final_status_msg_key = "status"
                final_status_text = "批量登录已中途取消. " + final_status_text
            logger.info(f"Batch task {task_id}: {final_status_text}")
            await manager.send_message(task_id, final_status_text, final_status_msg_key)
        except Exception as e:
            logger.error(f"Error in batch processing task {task_id}: {e}", exc_info=True)
            await manager.send_message(task_id, f"批处理任务 {task_id} 发生严重错误: {e}", "failed")
        finally:
            logger.info(f"Batch login task {task_id} processing loop finished.")

    asyncio.create_task(process_batch_concurrently())    
    return {"task_id": task_id, "message": f"Batch login task {task_id} started for {len(request.device_users)} devices."}

@router.get("/batch-login-status/{task_id}")
async def get_batch_login_status(task_id: str):
    task_details = active_tasks.get(task_id)
    if not task_details:
        logger.error(f"batch-login-status: Task with ID '{task_id}' not found. Existing keys: {list(active_tasks.keys())}")
        raise HTTPException(status_code=404, detail=f"Task with ID '{task_id}' not found.")

    total = task_details.get("total_devices", 0)
    completed = task_details.get("completed_devices", 0)
    successful = task_details.get("successful_devices", 0)
    failed = task_details.get("failed_devices", 0)
    current_task_status_from_dict = task_details.get("status", "processing") # status from dict like 'starting'

    response_status = "processing"
    message = f"Task {task_id} is processing. Devices processed: {completed}/{total}."

    task_overall_error = task_details.get("error_message") # For task-level errors
    
    if task_overall_error:
        response_status = "failed"
        message = f"Task {task_id} encountered an error: {task_overall_error}"
    elif task_details.get("cancel_flag") and task_details["cancel_flag"].is_set():
        response_status = "failed" # Consistent with frontend expecting 'failed' for non-success
        message = f"Task {task_id} was cancelled. Processed: {completed}/{total}, Successful: {successful}, Failed: {failed} before cancellation."
    elif completed >= total and total > 0:
        # All devices have been processed. Determine final status based on counts.
        suspended_count = task_details.get("suspended_accounts", 0)

        if successful == total:
            response_status = "succeeded"
            message = f"Task {task_id} completed. All {total} devices logged in successfully."
        # Check if we have successful devices based on the counter directly
        elif successful > 0:
            # If we have any successful devices, report success status
            if successful == total:
                response_status = "succeeded"
                message = f"Task {task_id} completed. All {total} devices logged in successfully."
            else:
                response_status = "completed"  # Partial success
                message = f"Task {task_id} completed with mixed results: {successful} succeeded, {failed} failed (of which {suspended_count} suspended) out of {total} devices."
        elif failed == total:
            # All devices failed - different handling based on suspension status
            if suspended_count > 0 and suspended_count == total: # All devices are suspended
                response_status = "completed"
                message = f"Task {task_id} completed. All {total} accounts processed were suspended."
            elif suspended_count > 0 and suspended_count < total: # All failed, some are suspended, some other failures
                 response_status = "completed" # Still 'completed' because it's not a clean sweep of 'failed'
                 message = f"Task {task_id} completed. All {total} devices failed or were suspended ({successful}s, {failed-suspended_count}f, {suspended_count}susp)."
            else: # All devices truly failed for reasons other than suspension
                response_status = "failed"
                message = f"Task {task_id} completed. All {total} devices failed to log in."
        else: # Mixed results (some succeeded, some failed/suspended)
            response_status = "completed"
            message = f"Task {task_id} completed with mixed results: {successful} succeeded, {failed} failed (of which {suspended_count} suspended) out of {total} devices."

    elif current_task_status_from_dict == "starting" and completed == 0:
        response_status = "processing" # Still in initial phase
        message = f"Task {task_id} has started and is initializing. Devices processed: {completed}/{total}."
    # Default case: still processing, message already set

    # Count suspended accounts from the task details
    suspended_count = task_details.get("suspended_accounts", 0)
    
    # If we have suspended accounts, mention them in the message
    if suspended_count > 0:
        message += f" ({suspended_count} 账户已封停但算作登录失败)"
    
    return {
        "task_id": task_id,
        "status": response_status,
        "message": message,
        "progress": {
            "total_devices": total,
            "completed_devices": completed,
            "successful_devices": successful,
            "failed_devices": failed,
            "suspended_accounts": suspended_count
        },
        "details": task_details.get("device_results", [])
    }
 