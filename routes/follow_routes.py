import os
import logging
import time
import json
import uuid
import asyncio
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

# Import backend modules
from db import models
from db.database import get_db
from utils.connection import manager, active_tasks
from utils.callbacks import WebSocketStatusCallback
from automation.followTest import run_follow_user

logger = logging.getLogger("TwitterAutomationAPI")

# Device User Manager
from db.database import SessionLocal
db = SessionLocal()
devices_query = db.query(models.DeviceUser).all()
db.close()

# Global variables
active_workers = []  # Store active worker instances

router = APIRouter(
    prefix="/api/follow",
    tags=["follow"],
)

class DeviceData(BaseModel):
    device_ip: str
    u2_port: int
    myt_rpc_port: Optional[int] = None
    username: Optional[str] = None
    device_name: Optional[str] = None

class FollowRequest(BaseModel):
    device_data: Dict[str, Any]
    username_to_follow: str

# Get devices endpoint
@router.get("/devices")
async def get_devices():
    """Get all available devices"""
    try:
        # Open a new database session
        db = SessionLocal()
        devices = db.query(models.DeviceUser).all()
        db.close()
        
        # Convert devices to a list of dictionaries
        devices_list = []
        for device in devices:
            devices_list.append({
                "id": device.id,
                "device_name": device.device_name,
                "device_ip": device.device_ip,
                "u2_port": device.u2_port,
                "myt_rpc_port": device.myt_rpc_port,
                "username": device.username
            })
        
        logger.info(f"Fetched {len(devices_list)} devices with full information")
        return {"devices": devices_list}
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Single device follow user
@router.post("/single")
async def follow_user_single(
    request: FollowRequest,
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Follow a user for a single device
    """
    try:
        # Process device data
        device_data = request.device_data
        
        # Create task ID
        device_id = f"{device_data['device_ip']}:{device_data['u2_port']}"
        task_id = f"follow_{device_id}_{uuid.uuid4().hex[:8]}"
        logger.info(f"Created task ID: {task_id}")
        
        # Store the current event loop to pass to the worker thread
        current_loop = asyncio.get_running_loop()
        
        # Create callback for status updates with the current event loop
        callback = WebSocketStatusCallback(task_id, loop=current_loop)
        
        # Add task to background tasks
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        executor.submit(run_follow_task, device_data, request.username_to_follow, callback, task_id, current_loop)
        
        return {"success": True, "task_id": task_id, "message": f"Follow user task started for device {device_id}"}
    except Exception as e:
        logger.error(f"Error in follow_user_single: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error starting follow user task: {str(e)}")

# Stop ongoing tasks
@router.post("/stop")
async def stop_follow(task_id: Optional[str] = None):
    """Stop all ongoing follow tasks or a specific task"""
    try:
        global active_workers
        
        if task_id:
            # Stop specific task
            if task_id in active_tasks:
                task_info = active_tasks[task_id]
                
                if "callback" in task_info and hasattr(task_info["callback"], "set_stopping"):
                    task_info["callback"].set_stopping(True)
                    await manager.broadcast_to_task(task_id, f"Stopping task {task_id}")
                    await manager.broadcast_to_status(f"Stopping task {task_id}")
                    return {"status": "success", "message": f"Stopping task {task_id}"}
            
            return {"status": "error", "message": f"Task {task_id} not found or cannot be stopped"}
        
        # Stop all tasks if no specific task_id provided
        if not active_workers:
            return {"status": "info", "message": "No active follow tasks to stop"}
        
        for worker in active_workers:
            if hasattr(worker, 'set_stopping') and callable(worker.set_stopping):
                worker.set_stopping(True)
        
        await manager.broadcast_to_status("Stopping all follow tasks")
        
        return {"status": "success", "message": "Stopping all follow tasks"}
    except Exception as e:
        logger.error(f"Error in stop_follow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Helper functions
def run_follow_task(device_data, username_to_follow, callback, task_id, main_loop):
    """Run the follow task for a single device"""
    try:
        device_id = f"{device_data['device_ip']}:{device_data['u2_port']}"
        logger.info(f"Starting follow task for device {device_id} to follow {username_to_follow}")
        
        # Register this task
        active_tasks[task_id] = {
            "type": "follow",
            "device_id": device_id,
            "status": "running",
            "callback": callback,
            "messages": [f"Starting follow task for device {device_id} to follow {username_to_follow}"]
        }
        
        # 检查设备数据是否完整
        if 'myt_rpc_port' not in device_data or device_data['myt_rpc_port'] is None:
            # 尝试从数据库获取设备信息
            try:
                db = SessionLocal()
                device = db.query(models.DeviceUser).filter(
                    models.DeviceUser.device_ip == device_data['device_ip'],
                    models.DeviceUser.u2_port == device_data['u2_port']
                ).first()
                db.close()
                
                if device and device.myt_rpc_port:
                    myt_rpc_port = device.myt_rpc_port
                    logger.info(f"Retrieved myt_rpc_port {myt_rpc_port} from database for device {device_id}")
                else:
                    myt_rpc_port = 11060  # 使用默认值作为最后的备选
                    logger.warning(f"Using default myt_rpc_port 11060 for device {device_id} as it was not found in database")
            except Exception as e:
                logger.error(f"Error retrieving device from database: {e}")
                myt_rpc_port = 11060
                logger.warning(f"Using default myt_rpc_port 11060 for device {device_id} due to error")
        else:
            myt_rpc_port = device_data['myt_rpc_port']
            logger.info(f"Using provided myt_rpc_port {myt_rpc_port} for device {device_id}")
        
        # Call the follow user function
        result = run_follow_user(
            callback,
            device_data['device_ip'],
            device_data['u2_port'],
            myt_rpc_port,
            username_to_follow
        )
        
        # Use the main loop passed from the calling function instead of trying to get a new one
        try:
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_to_task(task_id, f"Follow task for device {device_id} completed with result: {result}"),
                main_loop
            )
            
            # Update task status
            if task_id in active_tasks:
                active_tasks[task_id]["status"] = "completed"
                
            # Emit completion message
            asyncio.run_coroutine_threadsafe(
                manager.emit_to_task(task_id, "completed", {
                    "message": f"Follow task for device {device_id} {'succeeded' if result else 'failed'}"
                }),
                main_loop
            )
        except Exception as ws_e:
            logger.error(f"Error sending status to WebSocket: {ws_e}")
            
        return result
    except Exception as e:
        logger.error(f"Error in run_follow_task: {e}", exc_info=True)
        # Send error message via WebSocket
        try:
            # Use the main loop passed from the calling function
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_to_task(task_id, f"Error following user for device {device_id}: {str(e)}"),
                main_loop
            )
            # Update task status
            if task_id in active_tasks:
                active_tasks[task_id]["status"] = "failed"
                active_tasks[task_id]["error"] = str(e)
        except Exception as ws_e:
            logger.error(f"Error sending websocket error message: {ws_e}")
        return False 
