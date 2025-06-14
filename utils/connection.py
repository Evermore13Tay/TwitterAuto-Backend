import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Union, Optional
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("TwitterAutomationAPI")

# --- Global State ---
active_websockets: Dict[WebSocket, str] = {}  # WebSocket -> task_id mapping
active_tasks: Dict[str, Dict[str, Any]] = {}  # task_id -> task info mapping
active_advanced_tasks: Dict[str, Dict[str, Any]] = {}  # advanced task_id -> advanced task info mapping

# --- WebSocket Helper Functions ---
async def send_status_message(ws: WebSocket, message: str, task_id: str = "N/A", level: str = "INFO"):
    if ws is None: # Add check for None websocket
        logger.warning(f"WebSocket for task {task_id} is None. Cannot send status: {message}")
        return
    try:
        await ws.send_json({
            "type": "status", 
            "message": f"[Task {task_id}] {message}", 
            "level": level,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error sending status message to WebSocket for task {task_id}: {e}")

async def send_progress_update(ws: WebSocket, value: int, task_id: str = "N/A"):
    if ws is None:
        logger.warning(f"WebSocket for task {task_id} is None. Cannot send progress update: {value}")
        return
    try:
        await ws.send_json({
            "type": "progress", 
            "task_id": task_id, 
            "value": value,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error sending progress update to WebSocket for task {task_id}: {e}")

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.task_websockets: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        self.active_connections[task_id] = websocket
        self.task_websockets[task_id] = websocket
        logger.info(f"WebSocket connected for task {task_id}")

    def disconnect(self, task_id: str):
        if task_id in self.active_connections:
            self.active_connections.pop(task_id)
            logger.info(f"WebSocket disconnected for task {task_id}")
        if task_id in self.task_websockets:
            self.task_websockets.pop(task_id)

    async def send_message(self, task_id: str, message: str, level: str = "INFO"):
        if task_id in self.active_connections:
            websocket = self.active_connections[task_id]
            await send_status_message(websocket, message, task_id, level)
        else:
            # 减少WebSocket警告日志，仅记录DEBUG级别
            logger.debug(f"No active WebSocket for task {task_id} to send message: {message}")
            # Store message for later delivery if task exists
            if task_id in active_tasks:
                if "messages" not in active_tasks[task_id]:
                    active_tasks[task_id]["messages"] = []
                active_tasks[task_id]["messages"].append(message)
                logger.debug(f"Stored message for task {task_id} for later delivery")

    async def broadcast(self, message: str, exclude_task_id: str = None):
        """
        Broadcast a message to all connected WebSockets except the excluded one
        """
        for task_id, websocket in self.active_connections.items():
            if task_id != exclude_task_id:
                try:
                    await send_status_message(websocket, message, task_id)
                except Exception as e:
                    logger.error(f"Error broadcasting to {task_id}: {e}")

    async def broadcast_to_task(self, task_id: str, message: Union[str, Dict[str, Any]]):
        """
        Send a message to a specific task's WebSocket
        
        Args:
            task_id: The task ID to send the message to
            message: The message to send (string or dict)
        """
        if task_id in self.active_connections:
            websocket = self.active_connections[task_id]
            if websocket is None:
                logger.warning(f"WebSocket for task {task_id} is None. Cannot send message.")
                return
            
            try:
                if isinstance(message, str):
                    await send_status_message(websocket, message, task_id)
                else:
                    await websocket.send_json({
                        **message,
                        "task_id": task_id,
                        "timestamp": datetime.now().isoformat()
                    })
            except Exception as e:
                logger.error(f"Error broadcasting to task {task_id}: {e}")
        else:
            logger.debug(f"No active WebSocket for task {task_id} to broadcast message")
            # Store message for later delivery if task exists
            if task_id in active_tasks:
                if "messages" not in active_tasks[task_id]:
                    active_tasks[task_id]["messages"] = []
                active_tasks[task_id]["messages"].append(
                    message if isinstance(message, str) else f"JSON message: {message}"
                )
                logger.debug(f"Stored message for task {task_id} for later delivery")
    
    async def send_task_completed(self, task_id: str, device_ip: Optional[str] = None):
        """
        发送任务完成消息，包含设备信息
        
        Args:
            task_id: 任务ID
            device_ip: 设备IP地址
        """
        if task_id in self.active_connections:
            websocket = self.active_connections[task_id]
            if websocket is None:
                logger.warning(f"WebSocket for task {task_id} is None. Cannot send completion message.")
                return
            
            try:
                message = "发布推文任务已完成"
                await websocket.send_json({
                    "type": "completed",
                    "message": message,
                    "task_id": task_id,
                    "device_ip": device_ip,
                    "timestamp": datetime.now().isoformat()
                })
                logger.info(f"Sent completion message for task {task_id} (device: {device_ip})")
            except Exception as e:
                logger.error(f"Error sending completion message to task {task_id}: {e}")
        else:
            logger.debug(f"No active WebSocket for task {task_id} to send completion message")
    
    async def send_task_error(self, task_id: str, error_message: str, device_ip: Optional[str] = None):
        """
        发送任务错误消息，包含设备信息
        
        Args:
            task_id: 任务ID
            error_message: 错误消息
            device_ip: 设备IP地址
        """
        if task_id in self.active_connections:
            websocket = self.active_connections[task_id]
            if websocket is None:
                logger.warning(f"WebSocket for task {task_id} is None. Cannot send error message.")
                return
            
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": error_message,
                    "task_id": task_id,
                    "device_ip": device_ip,
                    "timestamp": datetime.now().isoformat()
                })
                logger.info(f"Sent error message for task {task_id} (device: {device_ip}): {error_message}")
            except Exception as e:
                logger.error(f"Error sending error message to task {task_id}: {e}")
        else:
            logger.debug(f"No active WebSocket for task {task_id} to send error message")
    
    async def emit_to_task(self, task_id: str, event: str, data: Union[Dict, str]):
        """
        Emit an event to a specific task's WebSocket
        
        Args:
            task_id: The task ID to send the event to
            event: The event type/name
            data: The event data (dict or string)
        """
        if task_id in self.active_connections:
            websocket = self.active_connections[task_id]
            if websocket is None:
                logger.warning(f"WebSocket for task {task_id} is None. Cannot emit event {event}.")
                return
            
            try:
                if isinstance(data, str):
                    data = {"message": data}
                
                await websocket.send_json({
                    "type": event,
                    **data,
                    "task_id": task_id,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Error emitting event {event} to task {task_id}: {e}")
        else:
            logger.debug(f"No active WebSocket for task {task_id} to emit event {event}")

    async def emit_to_status(self, event: str, data: Union[Dict, str]):
        """以 socket.io 风格发送消息到 /ws/status WebSocket"""
        websocket = self.active_connections.get("status")
        if websocket:
            try:
                if isinstance(data, str):
                    data = {"message": data}
                
                await websocket.send_json({
                    "type": event,
                    **data,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Error emitting to status WebSocket: {e}")
        else:
            logger.warning("Attempted to emit to status WebSocket, but no active connection found.")

    async def broadcast_to_status(self, message: str, level: str = "INFO"):
        """
        Send a status message to the status WebSocket endpoint
        """
        websocket = self.active_connections.get("status")
        if websocket:
            try:
                await websocket.send_json({
                    "type": "status_update",
                    "message": message,
                    "level": level,
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"Error broadcasting to status WebSocket: {e}")
        else:
            logger.debug("No status WebSocket connection to broadcast to")

    async def broadcast_task_status_change(self, task_id: str, new_status: str, task_name: str = None):
        """
        向所有连接的客户端广播任务状态变化
        
        Args:
            task_id: 任务ID
            new_status: 新的任务状态
            task_name: 任务名称（可选）
        """
        broadcast_message = {
            "type": "task_status_change", 
            "task_id": task_id,
            "status": new_status,
            "task_name": task_name,
            "timestamp": datetime.now().isoformat()
        }
        
        # 优先发送给task_status WebSocket连接（前端任务管理页面）
        task_status_websocket = self.active_connections.get("task_status")
        if task_status_websocket:
            try:
                await task_status_websocket.send_json(broadcast_message)
                logger.info(f"✅ 向任务状态监听器广播: 任务{task_id} -> {new_status}")
            except Exception as e:
                logger.warning(f"向任务状态监听器广播失败: {e}")
                # 如果发送失败，从连接列表中移除
                self.active_connections.pop("task_status", None)
        
        # 广播给所有其他连接的WebSocket客户端
        disconnected_clients = []
        for connection_id, websocket in self.active_connections.items():
            # 跳过task_status连接，因为已经单独处理了
            if connection_id == "task_status":
                continue
                
            try:
                await websocket.send_json(broadcast_message)
                logger.info(f"向客户端 {connection_id} 广播任务状态变化: 任务{task_id} -> {new_status}")
            except Exception as e:
                logger.warning(f"向客户端 {connection_id} 广播失败: {e}")
                disconnected_clients.append(connection_id)
        
        # 清理断开的连接
        for client_id in disconnected_clients:
            self.disconnect(client_id)
    
    async def broadcast_global_status(self, message: str, level: str = "INFO", data: Dict = None):
        """
        向所有连接的客户端广播全局状态消息
        
        Args:
            message: 消息内容
            level: 消息级别 (INFO, WARNING, ERROR, SUCCESS)
            data: 额外数据
        """
        broadcast_message = {
            "type": "global_status",
            "message": message,
            "level": level,
            "data": data or {},
            "timestamp": datetime.now().isoformat()
        }
        
        disconnected_clients = []
        for connection_id, websocket in self.active_connections.items():
            try:
                await websocket.send_json(broadcast_message)
            except Exception as e:
                logger.warning(f"向客户端 {connection_id} 广播全局状态失败: {e}")
                disconnected_clients.append(connection_id)
        
        # 清理断开的连接
        for client_id in disconnected_clients:
            self.disconnect(client_id)

# Create a global connection manager instance
manager = ConnectionManager() 