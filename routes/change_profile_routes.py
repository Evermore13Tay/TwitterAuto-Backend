import os
import logging
import time
import json
import uuid
import shutil
import asyncio
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, BackgroundTasks

# Import backend modules
from db import models
from db.database import get_db
from utils.connection import manager, active_tasks
from utils.callbacks import WebSocketStatusCallback
from utils.task_executor import ParallelBatchTaskExecutor, Worker
from automation.changeProfileTest import run_change_profile_photo

logger = logging.getLogger("TwitterAutomationAPI")

# Device User Manager
from db.database import SessionLocal
db = SessionLocal()
devices_query = db.query(models.DeviceUser).all()
db.close()

# Global variables
active_workers = []  # Store active worker instances

router = APIRouter(
    prefix="/api/change-profile",
    tags=["change-profile"],
)

class ProfileStatusCallback:
    """Status callback for profile change operations that sends updates via WebSocket"""
    def __init__(self, device_id: str, task_id: str, loop: asyncio.AbstractEventLoop):
        self.device_id = device_id
        self.task_id = task_id
        self.loop = loop
        self.messages = []
        self._is_stopping = False
        self.progress = 0
        
        # Create a mock thread object with progress_updated.emit() interface
        class MockThread:
            def __init__(self, parent):
                self._parent = parent
                self.progress_updated = self.MockProgressSignal(parent)
                
            class MockProgressSignal:
                def __init__(self, parent):
                    self._parent = parent
                def emit(self, value: int):
                    self._parent.progress_updated_emit(value)
            
            @property
            def is_stopping(self):
                return self._parent.is_stopping
        
        self.thread = MockThread(self)
    
    def __call__(self, message: str):
        """Handle status message from the profile change operation"""
        logger.info(f"Device {self.device_id} Profile Status: {message}")
        self.messages.append(message)
        
        # Send message via WebSocket
        asyncio.run_coroutine_threadsafe(
            manager.broadcast_to_task(self.task_id, f"[Device {self.device_id}] {message}"),
            self.loop
        )
        
        # Also broadcast to status for legacy clients
        asyncio.run_coroutine_threadsafe(
            manager.broadcast_to_status(f"[Device {self.device_id}] {message}"),
            self.loop
        )
    
    def progress_updated_emit(self, value: int):
        """Update progress value and emit via WebSocket"""
        self.progress = value
        logger.info(f"Device {self.device_id} Profile Progress: {value}%")
        
        # Send progress via WebSocket to task-specific endpoint
        asyncio.run_coroutine_threadsafe(
            manager.emit_to_task(self.task_id, "progress_update", {
                "device_id": self.device_id,
                "progress": value,
                "message": f"Device {self.device_id} progress: {value}%"
            }),
            self.loop
        )
        
        # Also emit to status for legacy clients
        asyncio.run_coroutine_threadsafe(
            manager.emit_to_status("progress_update", {
                "device_id": self.device_id,
                "progress": value,
                "message": f"Device {self.device_id} progress: {value}%"
            }),
            self.loop
        )
    
    @property
    def is_stopping(self):
        """Check if the operation is being stopped"""
        return self._is_stopping
    
    def set_stopping(self, value: bool = True):
        """Set the stopping flag"""
        self._is_stopping = value
        logger.info(f"Device {self.device_id} Profile stopping flag set to {value}")

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
                "myt_rpc_port": device.myt_rpc_port,  # 直接使用数据库值
                "username": device.username
            })
        
        logger.info(f"Fetched {len(devices_list)} devices with full information")
        return {"devices": devices_list}
    except Exception as e:
        logger.error(f"Error fetching devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Single device profile change
@router.post("/single")
async def change_profile_single(
    device_data: str = Form(...),
    photo: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Change profile photo for a single device
    """
    try:
        # Parse device_data from JSON string
        device_data = json.loads(device_data)
        
        # Create task ID
        device_id = f"{device_data['device_ip']}:{device_data['u2_port']}"
        task_id = f"profile_{device_id}_{uuid.uuid4().hex[:8]}"
        logger.info(f"Created task ID: {task_id}")
        
        # Save photo to temp directory
        photo_dir = "temp/profile_photos"
        os.makedirs(photo_dir, exist_ok=True)
        
        # Create filename with device info to avoid conflicts
        photo_filename = f"{device_id}_{photo.filename}"
        photo_path = os.path.join(photo_dir, photo_filename)
        
        # Write photo to file
        with open(photo_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        
        logger.info(f"Saved photo for device {device_id} to {photo_path}")
        
        # Create callback for status updates
        callback = WebSocketStatusCallback(task_id)
        
        # Add task to background tasks
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        executor.submit(run_profile_change_task, device_data, photo_path, callback, task_id)
        
        return {"success": True, "task_id": task_id, "message": f"Profile change task started for device {device_id}"}
    except Exception as e:
        logger.error(f"Error in change_profile_single: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error starting profile change: {str(e)}")

# Batch profile change
@router.post("/batch")
async def change_profile_batch(
    devices: str = Form(...),
    max_concurrent: int = Form(5),
    photos: List[UploadFile] = File(...)
):
    """Change profile photos for multiple devices in batch"""
    try:
        devices_data = json.loads(devices)
        device_count = len(devices_data)
        
        if device_count == 0:
            raise HTTPException(status_code=400, detail="No devices provided")
        
        if len(photos) != device_count:
            raise HTTPException(status_code=400, detail=f"Number of photos ({len(photos)}) doesn't match number of devices ({device_count})")
        
        # Generate a unique batch task ID
        task_id = f"batch_profile_{str(uuid.uuid4())[:8]}"
        
        # Save photos temporarily
        temp_dir = os.path.join("temp", "profile_photos", "batch")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Map devices to their photos
        device_photo_map = {}
        
        for i, device in enumerate(devices_data):
            device_id = f"{device['device_ip']}:{device['u2_port']}"
            photo = photos[i]
            
            # Extract the device ID from the filename if it has the format deviceID_filename
            filename = photo.filename
            if "_" in filename and filename.split("_")[0] == device_id:
                filename = filename.split("_", 1)[1]
            
            temp_file_path = os.path.join(temp_dir, f"{device_id}_{filename}")
            
            with open(temp_file_path, "wb") as f:
                shutil.copyfileobj(photo.file, f)
            
            device_photo_map[device_id] = {
                "device": device,
                "photo_path": temp_file_path
            }
            
            logger.info(f"Saved photo for device {device_id} to {temp_file_path}")
        
        # Get the event loop
        loop = asyncio.get_event_loop()
        
        # Create and start the batch executor
        executor = ProfileChangeBatchExecutor(
            device_photo_map,
            max_concurrent,
            loop,
            task_id
        )
        
        # Register the task
        active_tasks[task_id] = {
            "type": "batch_profile_change",
            "device_count": device_count,
            "max_concurrent": max_concurrent,
            "status": "starting",
            "executor": executor,
            "messages": [f"Starting batch profile photo change for {device_count} devices with max concurrency {max_concurrent}"]
        }
        
        # Store the executor for potential cancellation
        global active_workers
        active_workers.append(executor)
        
        # Start the batch execution
        background_tasks = BackgroundTasks()
        background_tasks.add_task(executor.start)
        
        # Broadcast start message via WebSocket
        await manager.broadcast_to_status(f"Starting batch profile photo change for {device_count} devices with max concurrency {max_concurrent}")
        
        return {
            "status": "success",
            "message": f"Batch profile change started for {device_count} devices",
            "max_concurrent": max_concurrent,
            "task_id": task_id
        }
    except Exception as e:
        logger.error(f"Error in change_profile_batch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Stop ongoing tasks
@router.post("/stop")
async def stop_profile_change(task_id: Optional[str] = None):
    """Stop all ongoing profile change tasks or a specific task"""
    try:
        global active_workers
        
        if task_id:
            # Stop specific task
            if task_id in active_tasks:
                task_info = active_tasks[task_id]
                
                if task_info["type"] == "batch_profile_change" and "executor" in task_info:
                    task_info["executor"].stop()
                    await manager.broadcast_to_task(task_id, f"Stopping task {task_id}")
                    await manager.broadcast_to_status(f"Stopping task {task_id}")
                    return {"status": "success", "message": f"Stopping task {task_id}"}
                else:
                    # Single profile change task
                    if "callback" in task_info and hasattr(task_info["callback"], "set_stopping"):
                        task_info["callback"].set_stopping(True)
                        await manager.broadcast_to_task(task_id, f"Stopping task {task_id}")
                        await manager.broadcast_to_status(f"Stopping task {task_id}")
                        return {"status": "success", "message": f"Stopping task {task_id}"}
            
            return {"status": "error", "message": f"Task {task_id} not found or cannot be stopped"}
        
        # Stop all tasks if no specific task_id provided
        if not active_workers:
            return {"status": "info", "message": "No active profile change tasks to stop"}
        
        for worker in active_workers:
            worker.stop()
        
        await manager.broadcast_to_status("Stopping all profile change tasks")
        
        return {"status": "success", "message": "Stopping all profile change tasks"}
    except Exception as e:
        logger.error(f"Error in stop_profile_change: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Helper functions and classes
def run_profile_change_task(device_data, photo_path, callback, task_id):
    """Run the profile change task for a single device"""
    try:
        device_id = f"{device_data['device_ip']}:{device_data['u2_port']}"
        logger.info(f"Starting profile change for device {device_id}")
        
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
        
        # Call the profile change function
        result = run_change_profile_photo(
            callback,
            device_data['device_ip'],
            device_data['u2_port'],
            myt_rpc_port,
            photo_path
        )
        
        # Use asyncio.run_coroutine_threadsafe to send completion message
        loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(
            manager.broadcast_to_task(task_id, f"Profile change for device {device_id} completed with result: {result}"),
            loop
        )
        
        # Clean up the temporary photo file
        try:
            if os.path.exists(photo_path):
                os.remove(photo_path)
        except Exception as e:
            logger.error(f"Error removing temporary file {photo_path}: {e}")
            
        return result
    except Exception as e:
        logger.error(f"Error in run_profile_change_task: {e}", exc_info=True)
        # Send error message via WebSocket
        loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(
            manager.broadcast_to_task(task_id, f"Error changing profile for device {device_id}: {str(e)}"),
            loop
        )
        return False

class ProfileChangeBatchExecutor:
    """Executor for batch profile changes"""
    def __init__(self, device_photo_map, max_concurrent, loop, task_id):
        self.device_photo_map = device_photo_map
        self.max_concurrent = max_concurrent
        self.loop = loop
        self.task_id = task_id
        self.is_stopping = False
        self.completed_count = 0
        self.total_count = len(device_photo_map)
        self.workers = []
    
    async def start(self):
        """Start the batch execution"""
        try:
            logger.info(f"Starting batch profile change for {self.total_count} devices")
            
            # Create a queue of devices to process
            devices_queue = list(self.device_photo_map.items())
            
            # Process devices in batches
            while devices_queue and not self.is_stopping:
                current_batch = devices_queue[:self.max_concurrent]
                devices_queue = devices_queue[self.max_concurrent:]
                
                tasks = []
                for device_id, data in current_batch:
                    # Create callback for this device
                    callback = ProfileStatusCallback(device_id, self.task_id, self.loop)
                    
                    # Create task
                    task = asyncio.create_task(
                        run_profile_change_task(
                            data["device"],
                            data["photo_path"],
                            callback,
                            self.task_id
                        )
                    )
                    
                    tasks.append(task)
                
                # Wait for all tasks in this batch to complete
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Update completion count
                for result in results:
                    if not isinstance(result, Exception):
                        self.completed_count += 1
                
                # Send progress update
                progress = int((self.completed_count / self.total_count) * 100)
                await manager.emit_to_task(self.task_id, "batch_progress", {
                    "completed": self.completed_count,
                    "total": self.total_count,
                    "progress": progress,
                    "message": f"Batch progress: {self.completed_count}/{self.total_count} devices completed ({progress}%)"
                })
            
            # Send completion message
            if self.is_stopping:
                await manager.broadcast_to_task(self.task_id, f"Batch profile change stopped after completing {self.completed_count}/{self.total_count} devices")
            else:
                await manager.broadcast_to_task(self.task_id, f"Batch profile change completed for all {self.total_count} devices")
        except Exception as e:
            logger.error(f"Error in batch profile change: {e}")
            await manager.broadcast_to_task(self.task_id, f"Error in batch profile change: {str(e)}")
        finally:
            # Remove self from active workers
            global active_workers
            if self in active_workers:
                active_workers.remove(self)
    
    def stop(self):
        """Stop the batch execution"""
        logger.info("Stopping batch profile change")
        self.is_stopping = True
        
        # Stop all workers
        for worker in self.workers:
            if hasattr(worker, 'set_stopping') and callable(worker.set_stopping):
                worker.set_stopping(True) 
