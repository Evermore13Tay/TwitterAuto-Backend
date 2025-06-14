import logging
import asyncio
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
import sys
import os

from utils.callbacks import WebSocketStatusCallback
from utils.connection import active_tasks, manager
from schemas.models import InteractionRequest, BatchInteractionRequest
from services.interaction_service import run_interaction_task

logger = logging.getLogger("TwitterAutomationAPI")

router = APIRouter(tags=["interaction"])
executor = ThreadPoolExecutor(max_workers=10)

# 添加automation目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
automation_dir = os.path.join(backend_dir, 'automation')
sys.path.insert(0, automation_dir)

@router.post("/api/run-interaction")
async def run_interaction_endpoint(request: InteractionRequest):
    current_loop = asyncio.get_event_loop()
    task_id_str = str(uuid.uuid4())
    active_tasks[task_id_str] = {
        "status": "pending", 
        "future": None, 
        "websocket": None, 
        "callback": None, 
        "type": "interaction", # Single interaction
        "start_time": datetime.now(),
        "cancel_flag": asyncio.Event()
    }
    logger.info(f"Received single interaction request for device {request.device_ip}. Task ID: {task_id_str}")
    ws_callback = WebSocketStatusCallback(websocket=None, task_id=task_id_str, loop=current_loop)
    active_tasks[task_id_str]["callback"] = ws_callback
    try:
        future = executor.submit(
            run_interaction_task,
            ws_callback, 
            request.device_ip,
            request.u2_port,
            request.myt_rpc_port,
            request.params.duration_seconds,
            request.params.enable_liking,
            request.params.enable_commenting,
            request.params.comment_text
        )
        active_tasks[task_id_str]["future"] = future
        active_tasks[task_id_str]["status"] = "running"
        logger.info(f"Single interaction task {task_id_str} submitted for device {request.device_ip}.")
        return {"task_id": task_id_str, "message": f"Single interaction task started for device {request.device_ip}. Connect to WebSocket ws/{task_id_str} for updates."}
    except Exception as e:
        logger.error(f"Failed to submit single interaction task {task_id_str} for device {request.device_ip}: {e}", exc_info=True)
        active_tasks.pop(task_id_str, None) 
        raise HTTPException(status_code=500, detail=f"Failed to start single interaction task: {str(e)}")

@router.post("/api/batch-run-interaction")
async def batch_run_interaction_endpoint(request: BatchInteractionRequest):
    if not request.devices:
        raise HTTPException(status_code=400, detail="No devices selected for batch interaction.")

    batch_task_id = str(uuid.uuid4())
    active_tasks[batch_task_id] = {
        "status": "starting",
        "type": "batch_interaction_master",
        "cancel_flag": asyncio.Event(),
        "start_time": datetime.now(),
        "total_devices": len(request.devices),
        "completed_devices": 0,
        "successful_devices": 0,
        "failed_devices": 0,
        "sub_tasks": {} # To store individual device task futures if needed for granular control
    }
    logger.info(f"Starting batch interaction task {batch_task_id} for {len(request.devices)} devices.")

    current_loop = asyncio.get_running_loop()

    async def process_single_device_interaction(device_data, master_task_id: str, loop_ref: asyncio.AbstractEventLoop):
        device_id_for_log = device_data.device_name or device_data.device_ip
        # Each device interaction can be thought of as a sub-task conceptually.
        # We'll use the master_task_id for WebSocket communication.
        
        await manager.send_message(master_task_id, f"Batch Interaction: Starting for device: {device_id_for_log}")
        
        # The WebSocketStatusCallback is associated with the master_task_id's WebSocket.
        # Messages from this callback will be routed through that single WebSocket.
        websocket_for_task = manager.active_connections.get(master_task_id)
        
        # For the purpose of the callback, we create a temporary, unique ID for this specific device run
        temp_sub_task_id_for_callback = f"{master_task_id}_{device_id_for_log.replace('.', '_')}" 
        
        device_specific_callback = WebSocketStatusCallback(websocket_for_task, temp_sub_task_id_for_callback, loop_ref)
        
        active_tasks[master_task_id]["sub_tasks"][device_id_for_log] = {"status": "running"}        

        try:
            success = await asyncio.to_thread(
                run_interaction_task,
                device_specific_callback, 
                device_data.device_ip,
                device_data.u2_port,
                device_data.myt_rpc_port,
                request.params.duration_seconds,
                request.params.enable_liking,
                request.params.enable_commenting,
                request.params.comment_text
            )
            active_tasks[master_task_id]["sub_tasks"][device_id_for_log]["status"] = "completed" if success else "failed"
            return device_id_for_log, success
        except Exception as e_device_task:
            logger.error(f"Batch Interaction Task {master_task_id}, device {device_id_for_log}: Error during interaction - {e_device_task}", exc_info=True)
            await manager.send_message(master_task_id, f"Device {device_id_for_log} interaction encountered an internal error: {e_device_task}", "error")
            if master_task_id in active_tasks and device_id_for_log in active_tasks[master_task_id]["sub_tasks"]:
                 active_tasks[master_task_id]["sub_tasks"][device_id_for_log]["status"] = "error"
            return device_id_for_log, False # Indicate failure for this device

    async def process_batch_interaction_concurrently():
        master_task_info = active_tasks[batch_task_id]
        try:
            interaction_coroutines = []
            for device_data in request.devices:
                if master_task_info["cancel_flag"].is_set():
                    logger.info(f"Batch interaction task {batch_task_id} cancelled before starting all devices.")
                    await manager.send_message(batch_task_id, f"Task {batch_task_id} was cancelled, skipping remaining devices.", "status")
                    break
                interaction_coroutines.append(process_single_device_interaction(device_data, batch_task_id, current_loop))
            
            results = await asyncio.gather(*interaction_coroutines, return_exceptions=True)

            for i, result_item in enumerate(results):
                master_task_info["completed_devices"] += 1
                
                # Determine device_id_for_log more safely if possible
                device_id_for_log = "Unknown Device"
                success_flag = False

                if isinstance(result_item, Exception):
                    logger.error(f"Batch task {batch_task_id}, device at index {i}: Exception caught by gather - {result_item}", exc_info=result_item)
                    # Try to get device name if possible, otherwise use index
                    current_device_name = request.devices[i].device_name if i < len(request.devices) else f"index {i}"
                    device_id_for_log = current_device_name
                    await manager.send_message(batch_task_id, f"Device {device_id_for_log} processing caught an exception: {result_item}", "error")
                    master_task_info["failed_devices"] += 1
                elif isinstance(result_item, tuple) and len(result_item) == 2: 
                    device_id_for_log, success_flag = result_item
                    if success_flag:
                        master_task_info["successful_devices"] += 1
                    else:
                        master_task_info["failed_devices"] += 1
                else: 
                    logger.error(f"Batch task {batch_task_id}, device at index {i}: Unexpected result format from gather - {result_item}")
                    device_id_for_log = request.devices[i].device_name if i < len(request.devices) else f"index {i}"
                    master_task_info["failed_devices"] += 1
                
                status_msg_device = f"Device {device_id_for_log}: Interaction {'successful' if success_flag else 'failed'}."
                logger.info(f"Batch task {batch_task_id}: {status_msg_device}")
                await manager.send_message(batch_task_id, status_msg_device, "device_completed") 

            final_status_text = (
                f"Batch interaction processing finished. "
                f"Total: {master_task_info['total_devices']}, "
                f"Successful: {master_task_info['successful_devices']}, "
                f"Failed: {master_task_info['failed_devices']}."
            )
            if master_task_info["cancel_flag"].is_set():
                final_status_text = "Batch interaction was cancelled. " + final_status_text
            
            logger.info(f"Batch task {batch_task_id}: {final_status_text}")
            await manager.send_message(batch_task_id, final_status_text, "completed") # Send 'completed' type for batch

        except Exception as e:
            logger.error(f"Error in batch interaction processing task {batch_task_id}: {e}", exc_info=True)
            await manager.send_message(batch_task_id, f"Batch interaction task {batch_task_id} encountered a critical error: {e}", "failed")
        finally:
            master_task_info["status"] = "finished_processing_loop"
            logger.info(f"Batch interaction task {batch_task_id} processing loop finished.")

    asyncio.create_task(process_batch_interaction_concurrently())
    return {"task_id": batch_task_id, "message": f"Batch interaction task {batch_task_id} started for {len(request.devices)} devices."} 

# 预热管理API
@router.get("/warmup/status")
async def get_warmup_status():
    """获取预热状态"""
    try:
        from automation.interactTest import get_warmed_up_devices
        warmed_devices = get_warmed_up_devices()
        
        return {
            "success": True,
            "warmed_devices": warmed_devices,
            "count": len(warmed_devices)
        }
    except Exception as e:
        logger.error(f"获取预热状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/warmup/clear")
async def clear_warmup_cache():
    """清理所有设备的预热缓存"""
    try:
        from automation.interactTest import clear_warmup_cache
        clear_warmup_cache()
        
        return {
            "success": True,
            "message": "预热缓存已清理，所有设备将重新预热"
        }
    except Exception as e:
        logger.error(f"清理预热缓存失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class RemoveWarmupRequest(BaseModel):
    device_ip: str
    u2_port: int

@router.post("/warmup/remove")
async def remove_device_warmup(request: RemoveWarmupRequest):
    """移除特定设备的预热状态"""
    try:
        from automation.interactTest import remove_device_from_warmup_cache
        remove_device_from_warmup_cache(request.device_ip, request.u2_port)
        
        return {
            "success": True,
            "message": f"设备 {request.device_ip}:{request.u2_port} 已从预热缓存中移除"
        }
    except Exception as e:
        logger.error(f"移除设备预热状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) 