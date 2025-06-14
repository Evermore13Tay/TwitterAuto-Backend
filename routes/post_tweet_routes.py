import os
import logging
import time
import json
import uuid
import asyncio
import shutil
import traceback
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form
from pydantic import BaseModel

# Import backend modules
from db import models
from db.database import get_db
from utils.connection import manager, active_tasks
from utils.callbacks import WebSocketStatusCallback
from automation.postTweetTest import run_post_tweet

logger = logging.getLogger("TwitterAutomationAPI")

# Device User Manager
from db.database import SessionLocal
db = SessionLocal()
devices_query = db.query(models.DeviceUser).all()
db.close()

# Global variables
active_workers = []  # Store active worker instances

router = APIRouter(
    prefix="/api/post-tweet",
    tags=["post-tweet"],
)

class DeviceData(BaseModel):
    device_ip: str
    u2_port: int
    myt_rpc_port: Optional[int] = None
    username: Optional[str] = None
    device_name: Optional[str] = None

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

# Single device post tweet
@router.post("/single")
async def post_tweet_single(
    device_data: str = Form(...),
    tweet_text: str = Form(...),
    attach_image: str = Form(...),
    image_count: Optional[str] = Form(None),
    image_0: Optional[UploadFile] = File(None),
    image_1: Optional[UploadFile] = File(None),
    image_2: Optional[UploadFile] = File(None),
    image_3: Optional[UploadFile] = File(None),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Post a tweet for a single device
    """
    try:
        # Parse device data
        device_data = json.loads(device_data)
        attach_image = attach_image.lower() == "true"
        
        # Create task ID
        device_id = f"{device_data['device_ip']}:{device_data['u2_port']}"
        task_id = f"post_tweet_{device_id}_{uuid.uuid4().hex[:8]}"
        logger.info(f"Created task ID: {task_id}")
        
        # Handle image uploads if attached
        image_paths = []
        if attach_image:
            # Create directory for uploads if it doesn't exist
            uploads_dir = os.path.join("static", "uploads")
            os.makedirs(uploads_dir, exist_ok=True)
            
            # Handle multiple images
            for i in range(4):  # Support up to 4 images
                img_key = f'image_{i}'
                img = locals().get(img_key)
                if img and hasattr(img, 'file') and img.filename:
                    image_name = f"{uuid.uuid4().hex}_{img.filename}"
                    image_path = os.path.join(uploads_dir, image_name)
                    
                    with open(image_path, "wb") as buffer:
                        shutil.copyfileobj(img.file, buffer)
                    
                    logger.info(f"Image {i} saved at {image_path}")
                    image_paths.append(image_path)
        
        logger.info(f"Total images to attach: {len(image_paths)}")
        
        # Store the current event loop to pass to the worker thread
        current_loop = asyncio.get_running_loop()
        
        # Create callback for status updates with the current event loop and device info
        callback = WebSocketStatusCallback(
            task_id, 
            loop=current_loop,
            extra_data={
                "device_ip": device_data["device_ip"],
                "u2_port": device_data["u2_port"],
                "username": device_data.get("username", "未知用户"),
                "image_count": len(image_paths) if attach_image else 0
            }
        )
        
        # Add task to background tasks
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            run_post_tweet_task, 
            device_data, 
            tweet_text, 
            attach_image, 
            image_paths, 
            callback, 
            task_id, 
            current_loop
        )
        
        # 监控任务执行并处理异常
        def handle_task_completion(future):
            try:
                result = future.result()
                # 任务正常完成
                asyncio.run_coroutine_threadsafe(
                    manager.send_task_completed(task_id, device_data["device_ip"]), 
                    current_loop
                )
            except Exception as e:
                # 任务执行出错
                error_message = f"Post tweet task failed: {str(e)}"
                logger.error(f"Task {task_id} failed: {error_message}")
                logger.error(traceback.format_exc())
                
                # 发送错误消息到WebSocket
                asyncio.run_coroutine_threadsafe(
                    manager.send_task_error(task_id, error_message, device_data["device_ip"]),
                    current_loop
                )
                
                # 更新任务状态
                if task_id in active_tasks:
                    active_tasks[task_id]["status"] = "failed"
                    active_tasks[task_id]["error"] = error_message
        
        # 添加回调来处理任务完成
        future.add_done_callback(handle_task_completion)
        
        return {"success": True, "task_id": task_id, "message": f"Post tweet task started for device {device_id}"}
    except Exception as e:
        logger.error(f"Error in post_tweet_single: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error starting post tweet task: {str(e)}")

# Stop ongoing tasks
@router.post("/stop")
async def stop_post_tweet(task_id: Optional[str] = None):
    """Stop all ongoing post tweet tasks or a specific task"""
    try:
        global active_workers
        stopped_tasks = []
        
        if task_id:
            # Stop specific task
            if task_id in active_tasks:
                task_info = active_tasks[task_id]
                
                if "callback" in task_info and hasattr(task_info["callback"], "set_stopping"):
                    task_info["callback"].set_stopping(True)
                    await manager.broadcast_to_task(task_id, f"Stopping task {task_id}")
                    await manager.broadcast_to_status(f"Stopping task {task_id}")
                    
                    # 添加设备信息到响应
                    device_info = {}
                    if "device_id" in task_info:
                        parts = task_info["device_id"].split(":")
                        if len(parts) > 0:
                            device_info["device_ip"] = parts[0]
                    
                    stopped_tasks.append({
                        "task_id": task_id, 
                        "device_info": device_info
                    })
                    
                    return {
                        "status": "success", 
                        "message": f"Stopping task {task_id}",
                        "stopped_tasks": stopped_tasks
                    }
            
            return {"status": "error", "message": f"Task {task_id} not found or cannot be stopped"}
        
        # Stop all tasks if no specific task_id provided
        if not any(task for task in active_tasks.values() if task["type"] == "post_tweet" and task["status"] == "running"):
            return {"status": "info", "message": "No active post tweet tasks to stop"}
        
        # 寻找所有活动的发布推文任务并停止它们
        for task_id, task_info in active_tasks.items():
            if task_info["type"] == "post_tweet" and task_info["status"] == "running":
                if "callback" in task_info and hasattr(task_info["callback"], "set_stopping"):
                    task_info["callback"].set_stopping(True)
                    await manager.broadcast_to_task(task_id, f"Stopping task {task_id}")
                    
                    # 添加设备信息到响应
                    device_info = {}
                    if "device_id" in task_info:
                        parts = task_info["device_id"].split(":")
                        if len(parts) > 0:
                            device_info["device_ip"] = parts[0]
                    
                    stopped_tasks.append({
                        "task_id": task_id, 
                        "device_info": device_info
                    })
        
        await manager.broadcast_to_status("Stopping all post tweet tasks")
        
        return {
            "status": "success", 
            "message": f"Stopping {len(stopped_tasks)} post tweet tasks",
            "stopped_tasks": stopped_tasks
        }
    except Exception as e:
        logger.error(f"Error in stop_post_tweet: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Helper functions
def run_post_tweet_task(device_data, tweet_text, attach_image, image_paths, callback, task_id, main_loop):
    """Run the post tweet task for a single device"""
    try:
        device_id = f"{device_data['device_ip']}:{device_data['u2_port']}"
        logger.info(f"Starting post tweet task for device {device_id}")
        
        # Register this task
        active_tasks[task_id] = {
            "type": "post_tweet",
            "device_id": device_id,
            "status": "running",
            "callback": callback,
            "messages": [f"Starting post tweet task for device {device_id}"],
            "start_time": time.time(),
            "device_ip": device_data["device_ip"],
            "images": len(image_paths) if attach_image else 0
        }
        
        # 检查设备数据是否完整
        if 'myt_rpc_port' not in device_data or device_data['myt_rpc_port'] is None:
            # 尝试从数据库获取设备信息
            db = SessionLocal()
            device = db.query(models.DeviceUser).filter(
                models.DeviceUser.device_ip == device_data['device_ip'],
                models.DeviceUser.u2_port == device_data['u2_port']
            ).first()
            db.close()
            
            if device and device.myt_rpc_port:
                device_data['myt_rpc_port'] = device.myt_rpc_port
                logger.info(f"Retrieved myt_rpc_port from database: {device.myt_rpc_port}")
            else:
                error_msg = f"Missing myt_rpc_port for device {device_id}"
                logger.error(error_msg)
                
                # 发送错误消息
                asyncio.run_coroutine_threadsafe(
                    manager.send_task_error(task_id, error_msg, device_data["device_ip"]),
                    main_loop
                )
                
                active_tasks[task_id]["status"] = "failed"
                active_tasks[task_id]["error"] = error_msg
                return False
        
        # 执行发布推文操作
        result = run_post_tweet(
            callback,
            device_data['device_ip'],
            device_data['u2_port'],
            device_data['myt_rpc_port'],
            tweet_text,
            attach_image,
            image_paths
        )
        
        # 更新任务状态
        if result:
            active_tasks[task_id]["status"] = "completed"
            logger.info(f"Task {task_id} completed successfully")
        else:
            active_tasks[task_id]["status"] = "failed"
            logger.error(f"Task {task_id} failed")
            
            # 发送任务失败消息
            error_msg = "发布推文任务执行失败"
            asyncio.run_coroutine_threadsafe(
                manager.send_task_error(task_id, error_msg, device_data["device_ip"]),
                main_loop
            )
        
        return result
    except Exception as e:
        # 处理任务执行中的异常
        error_msg = f"Post tweet task error: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        
        # 更新任务状态
        if task_id in active_tasks:
            active_tasks[task_id]["status"] = "failed"
            active_tasks[task_id]["error"] = error_msg
        
        # 发送错误消息
        try:
            asyncio.run_coroutine_threadsafe(
                manager.send_task_error(task_id, error_msg, device_data["device_ip"]),
                main_loop
            )
        except Exception as ws_err:
            logger.error(f"Error sending WebSocket error message: {ws_err}")
        
        # 重新抛出异常以便上层处理
        raise 
