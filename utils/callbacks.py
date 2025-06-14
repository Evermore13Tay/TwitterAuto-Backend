import asyncio
import logging
import threading
from typing import Dict, Any, Optional
from fastapi import WebSocket # Assuming FastAPI is used, though not directly in this snippet for WebSocket type hint
from datetime import datetime

logger = logging.getLogger("TwitterAutomationAPI") # Or a more generic logger name

# --- Status Callback Base Class ---
class StatusCallback:
    def __init__(self, task_id=None):
        self.task_id = task_id
        self.messages = []
        self.is_stopping = False # Should be a boolean
        self.progress = 0

    def __call__(self, message):
        logger.info(f"Task {self.task_id}: {message}")
        self.messages.append(message)

    def progress_updated_emit(self, value):
        self.progress = value
        # Potentially, this base class method could also log or store progress
        # logger.info(f"Task {self.task_id} Progress (base): {value}")


# --- WebSocket Status Callback ---
class WebSocketStatusCallback:
    # Event loop thread local storage to ensure we don't create multiple loops per thread
    _thread_local = threading.local()
    
    def __init__(self, task_id_or_websocket, task_id_or_none=None, loop=None, extra_data=None):
        """
        WebSocket Status Callback for sending status updates via WebSocket
        
        Supports two initialization patterns:
        1. WebSocketStatusCallback(task_id, loop=None, extra_data=None) - Used in change_signature_routes.py
        2. WebSocketStatusCallback(websocket, task_id, loop, extra_data=None) - Used in login_routes.py and interaction_routes.py
        
        Args:
            task_id_or_websocket: Either task_id (str) or websocket (WebSocket) object
            task_id_or_none: Either task_id (if first arg is websocket) or None (if first arg is task_id)
            loop: Optional event loop to use for sending messages from worker threads
            extra_data: Optional dictionary with extra data to include in messages (e.g. device info)
        """
        # Determine which constructor pattern was used
        if isinstance(task_id_or_websocket, WebSocket) or task_id_or_websocket is None: # Added check for None
            # Pattern 2: WebSocketStatusCallback(websocket, task_id, loop)
            self.websocket: Optional[WebSocket] = task_id_or_websocket # Type hint
            self.task_id: Optional[str] = task_id_or_none
            self.loop: Optional[asyncio.AbstractEventLoop] = loop
        else:
            # Pattern 1: WebSocketStatusCallback(task_id, loop=None)
            self.websocket: Optional[WebSocket] = None # Explicitly None
            self.task_id: Optional[str] = task_id_or_websocket
            # In pattern 1, task_id_or_none is actually the loop if provided, or None
            self.loop: Optional[asyncio.AbstractEventLoop] = task_id_or_none if isinstance(task_id_or_none, asyncio.AbstractEventLoop) else loop

        self._is_stopping = False
        self.pending_messages = []
        self._futures = []  # 追踪所有创建的future，以便清理
        
        # Store extra data (like device information)
        self.extra_data: Dict[str, Any] = extra_data or {}
        
        # Store the event loop explicitly during initialization
        if self.loop is None:
            # 使用更安全的方式获取事件循环
            self.loop = self._get_or_create_event_loop()
            if self.loop:
                logger.info(f"Task {self.task_id} using existing or new event loop: {id(self.loop)}")
            else:
                logger.error(f"Task {self.task_id} failed to get or create event loop")
        else:
            logger.info(f"Task {self.task_id} initialized with provided event loop: {id(self.loop)}")
            
        # Add a mock thread object to be compatible with existing code
        class MockThread:
            def __init__(self, parent_callback_instance):
                self._parent_callback = parent_callback_instance
                self.progress_updated = self.MockProgressSignal(parent_callback_instance)

            class MockProgressSignal:
                def __init__(self, parent_callback_instance):
                    self._parent_callback = parent_callback_instance
                def emit(self, value: int):
                    self._parent_callback.progress_updated_emit(value)

            @property
            def is_stopping(self):
                return self._parent_callback.is_stopping

        self.thread = MockThread(self)
    
    def _get_or_create_event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """
        安全地获取或创建事件循环，避免在多线程环境中创建多个循环
        
        Returns:
            asyncio.AbstractEventLoop or None: 事件循环实例，若创建失败则返回None
        """
        try:
            # 尝试获取当前线程的事件循环
            return asyncio.get_event_loop()
        except RuntimeError:
            # 如果当前线程没有事件循环
            current_thread = threading.current_thread()
            thread_id = current_thread.ident
            
            # 检查是否已经为此线程创建了循环
            if hasattr(WebSocketStatusCallback._thread_local, 'loop') and \
               hasattr(WebSocketStatusCallback._thread_local, 'thread_id') and \
               WebSocketStatusCallback._thread_local.thread_id == thread_id:
                logger.debug(f"Task {self.task_id} Reusing event loop {id(WebSocketStatusCallback._thread_local.loop)} for thread {thread_id}")
                return WebSocketStatusCallback._thread_local.loop
            
            try:
                # 仅在主线程才创建新的事件循环
                if current_thread is threading.main_thread():
                    logger.info(f"Creating new event loop in main thread for task {self.task_id}")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    # 存储线程ID和循环的引用
                    WebSocketStatusCallback._thread_local.loop = loop
                    WebSocketStatusCallback._thread_local.thread_id = thread_id
                    return loop
                else:
                    # 在非主线程中，我们不创建新的事件循环
                    # 尝试获取主线程的循环（如果FastAPI在主线程运行其循环）
                    # 这是一个复杂的问题，通常从非主线程向主线程的asyncio循环提交任务需要特殊处理
                    # 例如使用 call_soon_threadsafe 或 run_coroutine_threadsafe
                    # 如果没有主循环或无法安全访问，则返回None
                    logger.warning(f"Task {self.task_id} in non-main thread ({thread_id}). Cannot reliably create a new event loop here. Ensure a loop is passed or available via asyncio.get_event_loop() if this thread should manage one.")
                    # Attempt to get any running loop, might be risky if not managed properly
                    try:
                        return asyncio.get_running_loop()
                    except RuntimeError:
                        logger.error(f"Task {self.task_id} No running loop in non-main thread {thread_id} and cannot create one.")
                        return None
            except Exception as e:
                logger.error(f"Error creating or getting event loop: {e}")
                return None

    def __call__(self, message: Any): # Allow dict or str
        """
        Handle status message
        
        Args:
            message: The status message to broadcast (str or dict)
        """
        log_message = message if isinstance(message, str) else message.get("message", str(message))
        logger.info(f"Task {self.task_id} Status: {log_message}")
        
        # Store message locally first in case of connection issues
        self.pending_messages.append(message) # Store original message
        
        # If there's no event loop, we can't send the message right now
        if self.loop is None:
            logger.error(f"Task {self.task_id} No event loop available: loop was not set during initialization or failed to get.")
            return
        
        try:
            # Import the manager here to avoid circular imports at module level
            # This is generally not a good practice. Consider passing manager or using a different structure.
            from utils.connection import manager 
            
            # Check if the loop is running
            if not self.loop.is_running():
                logger.warning(f"Task {self.task_id} Event loop is not running, message will be queued: {message}")
                return
            
            # Create message with device info if available
            msg_data_to_send: Dict[str, Any] = {}
            if isinstance(message, str):
                msg_data_to_send = {"type": "status", "message": message} # Ensure a type for client
            elif isinstance(message, dict):
                msg_data_to_send = message.copy() # Use a copy
                if "type" not in msg_data_to_send:
                    msg_data_to_send["type"] = "status" # Default type
            else:
                logger.warning(f"Task {self.task_id} received message of unexpected type: {type(message)}. Converting to string.")
                msg_data_to_send = {"type": "status", "message": str(message)}

            # Add timestamp if not present
            if "timestamp" not in msg_data_to_send:
                msg_data_to_send["timestamp"] = datetime.now().isoformat()

            # Add task_id if not present
            if "task_id" not in msg_data_to_send:
                 msg_data_to_send["task_id"] = self.task_id

            # Add device info from extra_data if available
            if self.extra_data:
                # Create message with device data if available
                if "device_ip" in self.extra_data:
                    msg_data_to_send["device_ip"] = self.extra_data["device_ip"]
                    
                # Add other relevant extra data
                for key in ["u2_port", "username", "image_count"]: # Example keys
                    if key in self.extra_data:
                        msg_data_to_send[key] = self.extra_data[key]
            
            # Use the stored event loop to run the coroutine with more robust error handling
            try:
                # 使用更安全的方式运行协程
                future = self._run_coroutine_threadsafe(
                    manager.broadcast_to_task(self.task_id, msg_data_to_send)
                )
                
                if future:
                # Wait for the result with a timeout
                    try:
                        future.result(timeout=1.0) # Short timeout, sending should be fast
                        # If successful, remove from pending messages
                        if message in self.pending_messages: # Check original message
                            self.pending_messages.remove(message)
                    except asyncio.TimeoutError:
                        logger.warning(f"Task {self.task_id} Timeout sending message via WebSocket: {msg_data_to_send}")
                    except asyncio.CancelledError:
                        logger.warning(f"Task {self.task_id} WebSocket message sending was cancelled: {msg_data_to_send}")
                    except Exception as e_result: # Catch specific exceptions from broadcast_to_task if any
                        logger.error(f"Task {self.task_id} Error in future.result() for message {msg_data_to_send}: {e_result}")
            except Exception as e_run_coro:
                logger.error(f"Task {self.task_id} Error running coroutine for message {msg_data_to_send}: {e_run_coro}")
        except ImportError as e_import:
            logger.error(f"Task {self.task_id} Error importing 'manager' from 'utils.connection': {e_import}")
        except Exception as e_send_status:
            logger.error(f"Task {self.task_id} Error sending status for message {message}: {e_send_status}")
    
    def _run_coroutine_threadsafe(self, coro) -> Optional[asyncio.Future]:
        """
        安全地在事件循环中运行协程，处理可能的错误
        
        Args:
            coro: 要运行的协程
            
        Returns:
            asyncio.Future or None: 如果成功创建Future则返回，否则返回None
        """
        if self.loop is None:
            logger.error(f"Task {self.task_id} Cannot run coroutine: no event loop available")
            return None
        
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            # 追踪future以便清理
            self._futures.append(future)
            return future
        except RuntimeError as e_runtime: # e.g., event loop is closed or not running
            logger.error(f"Task {self.task_id} RuntimeError submitting coroutine to loop {id(self.loop)} (running: {self.loop.is_running()}): {e_runtime}")
            if not self.loop.is_running(): # If loop stopped, it's a problem
                self.loop = None # Invalidate loop
            return None
        except Exception as e_unexpected: # Catch any other unexpected errors
            logger.error(f"Task {self.task_id} Unexpected error running coroutine: {e_unexpected}")
            return None

    def progress_updated_emit(self, value: int):
        """
        Send progress update via WebSocket
        
        Args:
            value: The progress value (0-100)
        """
        logger.info(f"Task {self.task_id} Progress: {value}")
        
        # If there's no event loop, we can't send the message right now
        if self.loop is None:
            logger.error(f"Task {self.task_id} No event loop available for progress update: loop was not set during initialization or failed to get.")
            return
            
        try:
            # Import the manager here to avoid circular imports
            from utils.connection import manager
        
            # Check if the loop is running
            if not self.loop.is_running():
                logger.warning(f"Task {self.task_id} Event loop is not running, progress update ({value}%) will be queued")
                return
            
            # Create progress message with device info
            progress_data: Dict[str, Any] = {
                "type": "progress", 
                "value": value,
                "task_id": self.task_id, # Ensure task_id is in the message
                "timestamp": datetime.now().isoformat()
            }
            
            # Add device info from extra_data if available
            if self.extra_data and "device_ip" in self.extra_data:
                progress_data["device_ip"] = self.extra_data["device_ip"]
            
            # 使用更安全的方式运行协程
            future = self._run_coroutine_threadsafe(
                manager.broadcast_to_task(self.task_id, progress_data)
            )
            
            if future:
            # Wait for the result with a timeout
                try:
                    future.result(timeout=1.0)
                except asyncio.TimeoutError:
                    logger.warning(f"Task {self.task_id} Timeout sending progress update ({value}%) via WebSocket")
                except asyncio.CancelledError:
                    logger.warning(f"Task {self.task_id} Progress update ({value}%) was cancelled")
                except Exception as e_result:
                    logger.error(f"Task {self.task_id} Error in future.result() for progress update ({value}%): {e_result}")
        except ImportError as e_import:
            logger.error(f"Task {self.task_id} Error importing 'manager' for progress update: {e_import}")
        except Exception as e_send_progress:
            logger.error(f"Task {self.task_id} Error sending progress ({value}%): {e_send_progress}")

    @property
    def is_stopping(self) -> bool: # Added type hint
        """Check if the task is being stopped"""
        try:
            # Import here to avoid circular imports at module level
            from utils.connection import active_tasks # Assuming active_tasks is a dict like {task_id: {"cancel_flag": asyncio.Event()}}
            if self.task_id and self.task_id in active_tasks and \
               "cancel_flag" in active_tasks[self.task_id] and \
               active_tasks[self.task_id]["cancel_flag"].is_set():
                logger.info(f"Task {self.task_id} stopping signal detected via cancel_flag.")
                self._is_stopping = True # Update internal state as well
                return True
        except ImportError as e_import:
            logger.error(f"Task {self.task_id} Error importing 'active_tasks' from 'utils.connection': {e_import}")
        except Exception as e_check_stop: # Catch more generic exceptions
            logger.error(f"Task {self.task_id} Error checking stopping status: {e_check_stop}")
            
        return self._is_stopping # Return internal state if check fails or no flag
    
    def set_stopping(self, value: bool = True):
        """Explicitly set the stopping flag"""
        self._is_stopping = value
        logger.info(f"Task {self.task_id} stopping flag explicitly set to {value}")
        
        # 如果设置为停止状态，取消所有挂起的future
        if value and self._futures:
            logger.info(f"Task {self.task_id} Cancelling {len(self._futures)} pending futures due to stopping.")
            for future in self._futures: # Iterate over a copy if modifying list, but here just cancelling
                if not future.done() and not future.cancelled():
                    try:
                        future.cancel()
                    except Exception as e_cancel_future: # More specific exception if possible
                        logger.error(f"Task {self.task_id} Error cancelling future: {e_cancel_future}")
            
            # 清空future列表 (optional, or let them be garbage collected after cancellation attempt)
            # self._futures.clear() 
    
    def update_extra_data(self, new_data: Dict[str, Any]):
        """
        更新额外的设备数据信息
        
        Args:
            new_data: 要添加的新数据字典
        """
        if not isinstance(new_data, dict):
            logger.warning(f"Task {self.task_id} Attempted to update extra_data with a non-dict value: {new_data}")
            return
            
        self.extra_data.update(new_data)
        logger.info(f"Task {self.task_id} Updated extra_data: {self.extra_data}")
    
    def cleanup(self):
        """清理所有资源，取消挂起的future"""
        logger.info(f"Task {self.task_id} 开始清理资源...")
        
        # 取消所有未完成的future
        if self._futures:
            logger.info(f"Task {self.task_id} Cleaning up {len(self._futures)} futures.")
            for future in list(self._futures):  # 创建副本以避免在迭代过程中修改
                try:
                    if not future.done() and not future.cancelled():
                        future.cancel()
                        # 记录取消状态
                        logger.info(f"Task {self.task_id} 取消了一个未完成的future")
                    elif future.cancelled():
                        logger.info(f"Task {self.task_id} 检测到一个已被取消的future")
                    elif future.done():
                        # 检查是否有异常
                        try:
                            # 使用非阻塞方式检查结果
                            if future.exception(timeout=0): # Check immediately
                                logger.warning(f"Task {self.task_id} future完成但有异常: {future.exception()}")
                            else:
                                logger.info(f"Task {self.task_id} future已正常完成")
                        except (asyncio.InvalidStateError, asyncio.CancelledError, asyncio.TimeoutError) as e_check_exc:
                            logger.info(f"Task {self.task_id} 检查future结果时出现异常（可能正常）: {e_check_exc}")
                except Exception as e_cleanup_future:
                    logger.error(f"Task {self.task_id} 取消future时出错: {e_cleanup_future}")
            
            # 清空future列表
            self._futures.clear()
        
        # 主动设置停止标志
        self._is_stopping = True
        
        # 清理事件循环引用
        if hasattr(self, 'loop') and self.loop:
            # 我们不要关闭循环，因为它可能被其他任务共享
            # 但可以放弃对它的引用
            logger.info(f"Task {self.task_id} 清理事件循环引用")
            self.loop = None # Allow garbage collection if no other references
        
        # 清理额外数据
        if hasattr(self, 'extra_data'):
            self.extra_data.clear()
        
        # 清理消息缓存
        if hasattr(self, 'pending_messages'):
            self.pending_messages.clear()
        
        logger.info(f"Task {self.task_id} 资源清理完成")

# --- Synchronous Status Callback ---
class SynchronousStatusCallback:
    def __init__(self):
        self.messages = []
        self.progress = 0
        class MockThread:
            def __init__(self_mock_thread): # Renamed self to avoid conflict
                self_mock_thread.progress_value = 0
                self_mock_thread._is_stopping_flag = False
                # Assign an instance of MockProgressSignal to progress_updated
                self_mock_thread.progress_updated = self_mock_thread.MockProgressSignal(self_mock_thread) # Pass mock thread instance

            class MockProgressSignal: # Inner class for the signal-like object
                def __init__(self_signal, parent_thread_instance): # Renamed self
                    self_signal.parent_thread_instance = parent_thread_instance
                def emit(self_signal, value: int): # Renamed self
                    self_signal.parent_thread_instance.progress_value = value
                    # Use the outer class logger or pass it down
                    logger.info(f"SynchronousStatusCallback (mock thread via MockProgressSignal.emit) progress: {value}")

            @property
            def is_stopping(self_mock_thread): # Renamed self
                return self_mock_thread._is_stopping_flag

            def set_is_stopping(self_mock_thread, value: bool): # Renamed self
                self_mock_thread._is_stopping_flag = value

        self.thread = MockThread()

    def __call__(self, message: str):
        logger.debug(f"SynchronousStatusCallback Status: {message}") # Changed from info to debug
        self.messages.append(message)

    def get_all_messages(self) -> str:
        return "\n".join(self.messages)

    # Mocking progress_updated.emit for direct calls if logintest expects callback.progress_updated.emit
    def progress_updated_emit(self, value: int): # Renamed from progress_updated to match base class pattern
        self.progress = value
        logger.info(f"SynchronousStatusCallback progress_updated_emit: {value}")
        # If the intent is to call the mock thread's emit:
        if hasattr(self.thread, 'progress_updated') and hasattr(self.thread.progress_updated, 'emit'):
            self.thread.progress_updated.emit(value) 

# Import at module level to avoid circular imports
# We'll use a function to get this reference to avoid module-level circular imports
_log_connections_ref = None # Renamed to avoid conflict if original log_connections is imported elsewhere

def get_log_connections_from_routes(): # Renamed for clarity
    """Get the global log_connections list from websocket_routes module."""
    global _log_connections_ref
    if _log_connections_ref is None:
        try:
            # This import path needs to be correct relative to where this callbacks.py file is
            from routes.websocket_routes import log_connections # Assuming this is the correct path
            _log_connections_ref = log_connections
            logger.info("Successfully imported log_connections from routes.websocket_routes")
        except ImportError as e:
            logger.error(f"Could not import log_connections from routes.websocket_routes: {e}. Using empty list.")
            _log_connections_ref = [] # Default to empty list if import fails
    return _log_connections_ref
