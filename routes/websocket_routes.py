import logging
import json
import asyncio
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException

# 假设 utils.connection 和 utils.callbacks 存在且可导入
from utils.connection import manager, active_tasks
from utils.callbacks import WebSocketStatusCallback

logger = logging.getLogger("TwitterAutomationAPI") # 根据上下文，这可能是另一个项目的日志记录器名

router = APIRouter(tags=["websocket"])

# Global list of log WebSocket connections
log_connections = []

@router.websocket("/ws/logs")
async def logs_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for receiving all log messages.
    This is used by the dashboard to show a consolidated log view.
    """
    ping_timeout_task = None
    heartbeat_task = None
    try:
        # Accept the connection
        await websocket.accept()
        logger.info("Logs WebSocket connected")
        
        # Add to global logs connections
        log_connections.append(websocket)
        
        # Send welcome message
        await websocket.send_json({
            "type": "log",
            "message": "WebSocket logs connection established",
            "timestamp": datetime.now().isoformat()
        })
        
        # Track last ping time
        last_ping_time = datetime.now()
        
        def get_last_ping_time():
            return last_ping_time
        
        # Start the ping timeout checker and heartbeat sender in background tasks
        ping_timeout_task = asyncio.create_task(
            check_ping_timeout(websocket, "logs_connection", get_last_ping_time, timeout_seconds=60) # task_id 更具体一些
        )
        heartbeat_task = asyncio.create_task(
            send_heartbeat(websocket, "logs_connection") # task_id 更具体一些
        )
        
        try:
            # Keep connection alive until disconnect
            while True:
                try:
                    # Use a timeout to prevent blocking indefinitely
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                    try:
                        # Handle ping/pong for connection keepalive
                        message = json.loads(data)
                        if message.get("type") == "ping":
                            # Update last ping time
                            last_ping_time = datetime.now()
                            # Respond with pong
                            await websocket.send_json({
                                "type": "pong",
                                "timestamp": datetime.now().isoformat()
                            })
                    except json.JSONDecodeError:
                        logger.warning(f"Received invalid JSON from logs WebSocket: {data}")
                    except Exception as e:
                        logger.error(f"Error processing logs WebSocket message: {e}")
                except asyncio.TimeoutError:
                    # This is expected, just continue the loop
                    continue
                except WebSocketDisconnect:
                    logger.info("Logs WebSocket disconnected by client")
                    break
                except Exception as e:
                    logger.error(f"Error in logs WebSocket receive loop: {e}")
                    break
                    
        except WebSocketDisconnect: # This might be redundant if the inner one catches it first
            logger.info("Logs WebSocket disconnected (outer catch)")
    except Exception as e:
        logger.error(f"Error in logs WebSocket endpoint initial setup: {e}")
        try:
            # Try to close if an error occurs before the main loop
            if websocket.client_state != websocket.client_state.DISCONNECTED:
                await websocket.close()
        except Exception: # Ignore errors during close if already in an error state
            pass
    finally:
        # Cancel background tasks
        try:
            if ping_timeout_task and not ping_timeout_task.done():
                ping_timeout_task.cancel()
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
            
            # Await cancellation if tasks were created
            if ping_timeout_task:
                try:
                    await asyncio.wait_for(ping_timeout_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass # Expected
                except Exception as e_cancel:
                    logger.error(f"Error awaiting ping_timeout_task cancellation for logs: {e_cancel}")

            if heartbeat_task:
                try:
                    await asyncio.wait_for(heartbeat_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass # Expected
                except Exception as e_cancel:
                     logger.error(f"Error awaiting heartbeat_task cancellation for logs: {e_cancel}")

        except Exception as e:
            logger.error(f"Error canceling background tasks for logs WebSocket: {e}")
            
        # Remove from global list
        if websocket in log_connections:
            log_connections.remove(websocket)
        logger.info("Logs WebSocket connection resources cleaned up.")


@router.websocket("/ws/{task_id}")
async def task_websocket_endpoint(websocket: WebSocket, task_id: str):
    """
    WebSocket endpoint for task-specific connections.
    The task_id is used to associate this connection with a specific task.
    """
    ping_timeout_task = None
    heartbeat_task = None
    
    try:
        # Accept the connection
        await websocket.accept()
        logger.info(f"WebSocket connected for task {task_id}")
        
        # Store the connection in the manager
        manager.active_connections[task_id] = websocket
        
        # Send welcome message
        await websocket.send_json({
            "type": "connection_established",
            "task_id": task_id,
            "timestamp": datetime.now().isoformat()
        })
        
        # Track last ping time
        last_ping_time = datetime.now()
        
        def get_last_ping_time():
            return last_ping_time
        
        # Start the ping timeout checker and heartbeat sender in background tasks
        ping_timeout_task = asyncio.create_task(
            check_ping_timeout(websocket, task_id, get_last_ping_time, timeout_seconds=60)
        )
        heartbeat_task = asyncio.create_task(
            send_heartbeat(websocket, task_id)
        )
        
        # Wait for messages from the client
        while True:
            try:
                # Use a timeout to prevent blocking indefinitely
                message_text = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                
                # Handle received message
                try:
                    message_data = json.loads(message_text)
                    if isinstance(message_data, dict) and message_data.get("type") == "ping":
                        # Update last ping time
                        last_ping_time = datetime.now()
                        # Respond with pong
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        })
                    elif isinstance(message_data, dict) and message_data.get("type") == "cancel_task":
                        # Handle cancel request for a specific task (could be this task_id or another)
                        cancel_target_task_id = message_data.get("task_id_to_cancel", task_id) # Default to current task if not specified
                        logger.info(f"Cancel request received for task {cancel_target_task_id} via task WS {task_id}")
                        
                        # Set cancel flag if task exists
                        if cancel_target_task_id in active_tasks and "cancel_flag" in active_tasks[cancel_target_task_id]:
                            active_tasks[cancel_target_task_id]["cancel_flag"].set()
                            await websocket.send_json({
                                "type": "cancel_acknowledged", 
                                "task_id": cancel_target_task_id,
                                "timestamp": datetime.now().isoformat()
                            })
                        else:
                            await websocket.send_json({
                                "type": "cancel_failed",
                                "task_id": cancel_target_task_id,
                                "reason": "Task not found or not cancellable",
                                "timestamp": datetime.now().isoformat()
                            })
                    else:
                        # Handle other JSON messages
                        logger.debug(f"Received JSON message from client for task {task_id}: {message_data}")

                except json.JSONDecodeError:
                     # Handle plain text messages if necessary, or log as non-JSON
                    if message_text.lower() == "ping": # Simple text ping
                        last_ping_time = datetime.now()
                        await websocket.send_text("pong") # Simple text pong
                    else:
                        logger.debug(f"Received non-JSON text message from client for task {task_id}: {message_text}")

            except asyncio.TimeoutError:
                # This is expected, just continue the loop
                continue
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected by client for task {task_id}")
                break
            except Exception as e:
                logger.error(f"WebSocket error for task {task_id} in receive loop: {str(e)}")
                break
                
    except WebSocketDisconnect: # Outer catch if disconnect happens before main loop
        logger.info(f"WebSocket disconnected for task {task_id} (outer catch)")
    except asyncio.CancelledError:
        logger.info(f"WebSocket task for {task_id} was cancelled (likely server shutdown)")
    except Exception as e:
        logger.error(f"Error in task WebSocket endpoint {task_id} initial setup: {str(e)}")
        try:
            if websocket.client_state != websocket.client_state.DISCONNECTED:
                 await websocket.close()
        except Exception:
            pass # Ignore errors during close if already in an error state
    finally:
        # Clean up
        if task_id in manager.active_connections:
            try:
                del manager.active_connections[task_id]
                logger.info(f"Removed {task_id} from active_connections")
            except Exception as e_del:
                logger.error(f"Error removing {task_id} from active_connections: {str(e_del)}")
        
        # 确保在任务中清理任何正在运行的后台任务
        if task_id in active_tasks:
            try:
                # 设置取消标志
                if "cancel_flag" in active_tasks[task_id]:
                    active_tasks[task_id]["cancel_flag"].set()
                    logger.info(f"Set cancel flag for task {task_id} during cleanup")
                
                # 清理回调中的资源 (example, if WebSocketStatusCallback has cleanup)
                # if "callback" in active_tasks[task_id] and isinstance(active_tasks[task_id]["callback"], WebSocketStatusCallback):
                #     try:
                #         active_tasks[task_id]["callback"].cleanup_websocket_resources() # Hypothetical method
                #         logger.info(f"Cleaned up callback resources for task {task_id}")
                #     except Exception as e_cb_clean:
                #         logger.error(f"Error cleaning up callback for task {task_id}: {str(e_cb_clean)}")
            except Exception as e_task_clean:
                logger.error(f"Error cleaning up active task resources for {task_id}: {str(e_task_clean)}")
        
        # Cancel background tasks
        try:
            if ping_timeout_task and not ping_timeout_task.done():
                ping_timeout_task.cancel()
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()

            if ping_timeout_task:
                try:
                    await asyncio.wait_for(ping_timeout_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError): pass
                except Exception as e_cancel: logger.warning(f"Error awaiting ping_timeout_task cancellation for {task_id}: {e_cancel}")
            
            if heartbeat_task:
                try:
                    await asyncio.wait_for(heartbeat_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError): pass
                except Exception as e_cancel: logger.warning(f"Error awaiting heartbeat_task cancellation for {task_id}: {e_cancel}")

        except Exception as e_bg_cancel:
            logger.error(f"Error canceling background tasks for {task_id}: {str(e_bg_cancel)}")
        
        logger.info(f"WebSocket resources cleaned up for task {task_id}")


@router.websocket("/ws/status")
async def status_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for general status updates.
    This is used by the frontend to receive status updates without being tied to a specific task.
    """
    heartbeat_task = None
    ping_timeout_task = None
    status_id = f"status_{int(datetime.now().timestamp() * 1000)}" # More unique ID

    try:
        # Accept the connection
        await websocket.accept()
        logger.info(f"Status WebSocket connected: {status_id}")
        
        # Store in manager for broadcasting (if needed for status, or just keep local)
        manager.active_connections[status_id] = websocket # Example, adjust if status WS are handled differently
        
        # Send welcome message
        await websocket.send_json({
            "type": "status_update",
            "message": "WebSocket status connection established",
            "timestamp": datetime.now().isoformat(),
            "connection_id": status_id
        })
        
        # Track last ping time
        last_ping_time = datetime.now()
        
        async def update_ping_time():
            nonlocal last_ping_time
            last_ping_time = datetime.now()
            
        def get_current_last_ping_time(): # Lambda can also be used directly
            return last_ping_time

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(send_heartbeat(websocket, status_id))
        
        # Start ping timeout checker with a longer timeout (120 seconds for status connections)
        ping_timeout_task = asyncio.create_task(
            check_ping_timeout(websocket, status_id, get_current_last_ping_time, 120)
        )
        
        # Initial ping time update (client might send ping immediately or not)
        await update_ping_time() # Set initial time
            
        while True:
            try:
                # Wait for messages from client with a timeout
                data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0) # Shorter timeout to allow heartbeats
                
                try:
                    message = json.loads(data)
                    if message.get("type") == "ping":
                        # Update last ping time
                        await update_ping_time()
                        # Send pong response
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        })
                        logger.debug(f"Received ping from {status_id}, sent pong")
                except json.JSONDecodeError:
                    logger.warning(f"Received invalid JSON from status WebSocket {status_id}: {data}")
                except Exception as e:
                    logger.error(f"Error processing status WebSocket message from {status_id}: {e}")
                    
            except asyncio.TimeoutError:
                # No message received within timeout, send a heartbeat to check connection
                # This is handled by the send_heartbeat task now
                continue 
            except WebSocketDisconnect:
                logger.info(f"Status WebSocket {status_id} disconnected by client")
                break
            except Exception as e_loop:
                logger.error(f"Error in status WebSocket {status_id} receive loop: {e_loop}")
                break
                
    except WebSocketDisconnect: # Outer catch if disconnect happens before main loop
        logger.info(f"Status WebSocket {status_id} disconnected (outer catch)")
    except Exception as e_outer:
        logger.error(f"Error in status WebSocket endpoint {status_id} initial setup: {e_outer}")
        try:
            if websocket.client_state != websocket.client_state.DISCONNECTED:
                await websocket.close()
        except Exception:
            pass
    finally:
        # Cancel heartbeat and ping timeout tasks
        try:
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
            if ping_timeout_task and not ping_timeout_task.done():
                ping_timeout_task.cancel()

            if heartbeat_task:
                try: await asyncio.wait_for(heartbeat_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError): pass
                except Exception as e_cancel: logger.warning(f"Error awaiting heartbeat_task cancellation for {status_id}: {e_cancel}")
            
            if ping_timeout_task:
                try: await asyncio.wait_for(ping_timeout_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError): pass
                except Exception as e_cancel: logger.warning(f"Error awaiting ping_timeout_task cancellation for {status_id}: {e_cancel}")

        except Exception as e_bg_cancel:
             logger.error(f"Error canceling background tasks for status WebSocket {status_id}: {e_bg_cancel}")

        # Remove from manager if still there
        manager.active_connections.pop(status_id, None)
        logger.info(f"Status WebSocket connection resources cleaned up for {status_id}.")


@router.websocket("/ws/task-status")
async def task_status_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket端点用于接收全局任务状态更新通知
    前端连接此端点可以实时收到任务状态变化
    """
    ping_timeout_task = None
    heartbeat_task = None
    
    try:
        # 接受WebSocket连接
        await websocket.accept()
        logger.info("Task status WebSocket connected")
        
        # 将连接存储到管理器中，使用特殊的"task_status"标识
        manager.active_connections["task_status"] = websocket
        
        # 发送欢迎消息
        await websocket.send_json({
            "type": "connection_established",
            "message": "任务状态监控连接已建立",
            "timestamp": datetime.now().isoformat()
        })
        
        # 跟踪最后ping时间
        last_ping_time = datetime.now()
        
        def get_last_ping_time():
            return last_ping_time
        
        # 启动心跳检测任务
        ping_timeout_task = asyncio.create_task(
            check_ping_timeout(websocket, "task_status", get_last_ping_time, timeout_seconds=60)
        )
        heartbeat_task = asyncio.create_task(
            send_heartbeat(websocket, "task_status")
        )
        
        # 等待客户端消息
        while True:
            try:
                # 设置超时防止无限阻塞
                message_text = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                
                try:
                    message_data = json.loads(message_text)
                    if isinstance(message_data, dict) and message_data.get("type") == "ping":
                        # 更新最后ping时间
                        last_ping_time = datetime.now()
                        # 响应pong
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        })
                    elif isinstance(message_data, dict) and message_data.get("type") == "request_all_tasks_status":
                        # 客户端请求获取所有任务的当前状态
                        try:
                            from tasks_api import get_tasks
                            tasks_result = get_tasks()
                            if tasks_result.get('success'):
                                await websocket.send_json({
                                    "type": "all_tasks_status",
                                    "tasks": tasks_result.get('tasks', []),
                                    "timestamp": datetime.now().isoformat()
                                })
                        except Exception as e:
                            logger.error(f"获取任务状态失败: {e}")
                            await websocket.send_json({
                                "type": "error",
                                "message": f"获取任务状态失败: {str(e)}",
                                "timestamp": datetime.now().isoformat()
                            })
                    else:
                        logger.info(f"Task status WS received message: {message_data}")
                        
                except json.JSONDecodeError:
                    logger.warning(f"Received invalid JSON from task status WebSocket: {message_text}")
                except Exception as e:
                    logger.error(f"Error processing task status WebSocket message: {e}")
                    
            except asyncio.TimeoutError:
                # 预期的超时，继续循环
                continue
            except WebSocketDisconnect:
                logger.info("Task status WebSocket disconnected by client")
                break
            except Exception as e:
                logger.error(f"Error in task status WebSocket receive loop: {e}")
                break
                
    except WebSocketDisconnect:
        logger.info("Task status WebSocket disconnected")
    except Exception as e:
        logger.error(f"Error in task status WebSocket endpoint: {e}")
    finally:
        # 取消后台任务
        try:
            if ping_timeout_task and not ping_timeout_task.done():
                ping_timeout_task.cancel()
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
            
            # 等待任务取消
            if ping_timeout_task:
                try:
                    await asyncio.wait_for(ping_timeout_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                except Exception as e:
                    logger.error(f"Error awaiting ping_timeout_task cancellation: {e}")

            if heartbeat_task:
                try:
                    await asyncio.wait_for(heartbeat_task, timeout=1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
                except Exception as e:
                    logger.error(f"Error awaiting heartbeat_task cancellation: {e}")
                    
        except Exception as e:
            logger.error(f"Error canceling background tasks for task status WebSocket: {e}")
            
        # 从管理器中移除连接
        if "task_status" in manager.active_connections:
            del manager.active_connections["task_status"]
        logger.info("Task status WebSocket connection cleaned up")


async def check_ping_timeout(websocket: WebSocket, task_id_or_conn_id: str, get_last_ping_time_func, timeout_seconds: int = 35):
    """
    检查客户端是否仍然活跃，如果超过timeout_seconds秒没有收到ping，则关闭连接
    
    Args:
        websocket: WebSocket连接
        task_id_or_conn_id: 任务ID或连接ID (用于日志)
        get_last_ping_time_func: 获取最后一次ping时间的函数
        timeout_seconds: 超时秒数
    """
    try:
        while True:
            try:
                # 检查是否有可用的websocket连接
                if websocket is None or websocket.client_state == websocket.client_state.DISCONNECTED:
                    logger.info(f"WebSocket for {task_id_or_conn_id} is already disconnected (checker exiting)")
                    break
                    
                # 计算上次ping的时间
                last_ping = get_last_ping_time_func()
                now = datetime.now()
                elapsed = (now - last_ping).total_seconds()
                
                # 如果超过超时时间，关闭连接
                if elapsed > timeout_seconds:
                    logger.warning(f"Ping timeout ({elapsed:.1f}s > {timeout_seconds}s) for {task_id_or_conn_id}, closing connection")
                    try:
                        if websocket.client_state != websocket.client_state.DISCONNECTED:
                            await websocket.close(code=1000, reason="Ping timeout")
                    except (ConnectionResetError, OSError) as e_close:
                        # 网络连接已经断开，记录DEBUG级别即可
                        logger.debug(f"Connection already closed for {task_id_or_conn_id}: {e_close}")
                    except Exception as e_close:
                        logger.error(f"Error closing WebSocket for {task_id_or_conn_id} on ping timeout: {e_close}")
                    break # Exit checker loop once closed or attempted close
                    
                # 等待一段时间再次检查
                await asyncio.sleep(5)  # 每5秒检查一次
            except asyncio.CancelledError:
                logger.info(f"Ping timeout checker for {task_id_or_conn_id} was cancelled")
                raise  # 重新抛出以便外层捕获
            except Exception as e_inner_check:
                logger.error(f"Error in ping timeout checker for {task_id_or_conn_id}: {e_inner_check}")
                await asyncio.sleep(5)  # 发生错误时，等待后重试
    except asyncio.CancelledError:
        # 预期的取消，记录并清理
        logger.info(f"Ping timeout checker task for {task_id_or_conn_id} was cancelled (outer)")
    except Exception as e_outer_check:
        logger.error(f"Unexpected error in ping timeout checker for {task_id_or_conn_id}: {e_outer_check}")
    finally:
        logger.info(f"Ping timeout checker for {task_id_or_conn_id} ended")


async def send_heartbeat(websocket: WebSocket, task_id_or_conn_id: str):
    """
    定期发送心跳消息，保持连接活跃
    
    Args:
        websocket: WebSocket连接
        task_id_or_conn_id: 任务ID或连接ID (用于日志)
    """
    try:
        while True:
            try:
                # 检查是否有可用的websocket连接
                if websocket is None or websocket.client_state == websocket.client_state.DISCONNECTED:
                    logger.info(f"WebSocket for {task_id_or_conn_id} is already disconnected (heartbeat sender exiting)")
                    break
                    
                # 发送心跳
                await websocket.send_json({
                    "type": "heartbeat",
                    "timestamp": datetime.now().isoformat()
                })
                logger.debug(f"Sent heartbeat for {task_id_or_conn_id}")
                
                # 等待一段时间再发送下一次心跳
                await asyncio.sleep(20)  # 每20秒发送一次心跳
            except asyncio.CancelledError:
                logger.info(f"Heartbeat sender for {task_id_or_conn_id} was cancelled")
                raise  # 重新抛出以便外层捕获
            except (ConnectionResetError, OSError) as e_inner_hb:
                # 网络连接已经断开，记录DEBUG级别即可
                logger.debug(f"Connection closed while sending heartbeat for {task_id_or_conn_id}: {e_inner_hb}")
                break  # 连接已断开，退出循环
            except Exception as e_inner_hb: # Catch specific errors like ConnectionClosed if send_json fails
                logger.error(f"Error sending heartbeat for {task_id_or_conn_id}: {e_inner_hb}")
                if websocket.client_state == websocket.client_state.DISCONNECTED: # If send failed due to disconnect
                    break
                await asyncio.sleep(5)  # 发生错误时，等待后重试 (if not disconnected)
    except asyncio.CancelledError:
        # 预期的取消，记录并清理
        logger.info(f"Heartbeat sender task for {task_id_or_conn_id} was cancelled (outer)")
    except Exception as e_outer_hb:
        logger.error(f"Unexpected error in heartbeat sender for {task_id_or_conn_id}: {e_outer_hb}")
    finally:
        logger.info(f"Heartbeat sender for {task_id_or_conn_id} ended")
