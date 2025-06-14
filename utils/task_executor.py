import logging
import time
import traceback
from typing import Callable, Any, List, Optional
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("TwitterAutomationAPI")

# Worker signals
class WorkerSignals:
    """Class holding signals available from a Worker thread."""
    
    def __init__(self):
        self.status_updated = None  # Signal to update status
        self.finished = None        # Signal to indicate task completion
        self.stop = None            # Signal to stop the worker
        self._is_stopping = False   # Internal flag to track stopping state
    
    def connect_status_updated(self, callback):
        """Connect status_updated signal to a callback function."""
        self.status_updated = callback
    
    def connect_finished(self, callback):
        """Connect finished signal to a callback function."""
        self.finished = callback
    
    def connect_stop(self, callback):
        """Connect stop signal to a callback function."""
        self.stop = callback
    
    def emit_status_updated(self, message):
        """Emit status_updated signal with message."""
        if self.status_updated:
            self.status_updated(message)
    
    def emit_finished(self, success):
        """Emit finished signal with success flag."""
        if self.finished:
            self.finished(success)
    
    def emit_stop(self):
        """Emit stop signal."""
        self._is_stopping = True
        if self.stop:
            self.stop()

# Worker class
class Worker:
    """Worker thread for running tasks."""
    
    def __init__(self, task_function: Callable, *args):
        """Initialize Worker with a task function and arguments."""
        self.signals = WorkerSignals()
        self.task_function = task_function
        self.args = args
        self.is_stopping = False
        self.last_update = 0
        self._thread = None
    
    def run(self):
        """Run the task function in the current thread."""
        task_success = False
        try:
            # Pass is_stopping_callback to functions that support it
            task_args = list(self.args)
            if self.task_function.__code__.co_varnames and "is_stopping_callback" in self.task_function.__code__.co_varnames:
                task_success = self.task_function(self.status_callback, *task_args, is_stopping_callback=self.is_stopping_check)
            else:
                task_success = self.task_function(self.status_callback, *task_args)
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            self.signals.emit_status_updated(f"任务失败: {str(e)}")
        finally:
            self.signals.emit_finished(task_success)
    
    def status_callback(self, message):
        """Callback for status updates from the task function."""
        current_time = time.time()
        if current_time - self.last_update > 1:  # Update every second
            self.signals.emit_status_updated(message)
            self.last_update = current_time
    
    def is_stopping_check(self):
        """Callback for checking if the worker is stopping."""
        return self.is_stopping
    
    def stop_gracefully(self):
        """Stop the worker gracefully."""
        self.is_stopping = True
        self.signals.emit_status_updated("正在停止任务...")

# BatchTaskExecutor
class BatchTaskExecutor:
    """Base class for executing batch tasks."""
    
    def __init__(self, status_callback):
        """Initialize BatchTaskExecutor with a status callback."""
        self.status_callback = status_callback
        self.running = False
    
    def execute_batch_task(self, device_users, task_function, *extra_args, extra_args_provider=None):
        """Execute a batch task on multiple devices."""
        self.running = True
        workers = []
        
        for device_user in device_users:
            # Base arguments for the task function
            args = [
                device_user.get("device_ip") if isinstance(device_user, dict) else device_user.device_ip,
                device_user.get("u2_port") if isinstance(device_user, dict) else device_user.u2_port,
                device_user.get("myt_rpc_port") if isinstance(device_user, dict) else device_user.myt_rpc_port
            ]
            
            # Add extra arguments
            if extra_args_provider:
                args.extend(extra_args_provider(device_user))
            else:
                args.extend(extra_args)
            
            # Create and start worker
            worker = Worker(task_function, *args)
            worker.signals.connect_status_updated(self.status_callback)
            workers.append(worker)
            
            threading.Thread(target=worker.run).start()
        
        return workers
    
    def is_running(self):
        """Check if batch task is running."""
        return self.running

# ParallelBatchTaskExecutor
class ParallelBatchTaskExecutor(BatchTaskExecutor):
    """Executor for parallel batch tasks with a thread pool."""
    
    def __init__(self, status_callback, max_thread_count=5):
        """Initialize ParallelBatchTaskExecutor with status callback and thread count."""
        super().__init__(status_callback)
        self.pool = ThreadPoolExecutor(max_workers=max_thread_count)
        self.active_tasks = 0
        self.workers = []  # Store worker instances
    
    def execute_batch_task(self, device_users, task_function, *extra_args, extra_args_provider=None):
        """Execute a batch task in parallel."""
        self.running = True
        self.active_tasks = len(device_users)
        self.workers = []  # Clear previous workers
        
        for device_user in device_users:
            # Base arguments for the task function
            args = [
                device_user.get("device_ip") if isinstance(device_user, dict) else device_user.device_ip,
                device_user.get("u2_port") if isinstance(device_user, dict) else device_user.u2_port,
                device_user.get("myt_rpc_port") if isinstance(device_user, dict) else device_user.myt_rpc_port
            ]
            
            # Add extra arguments
            if extra_args_provider:
                args.extend(extra_args_provider(device_user))
            else:
                args.extend(extra_args)
            
            # Create worker
            worker = Worker(task_function, *args)
            worker.signals.connect_status_updated(self.status_callback)
            worker.signals.connect_finished(self.on_task_finished)
            
            # Store and start worker
            self.workers.append(worker)
            self.pool.submit(worker.run)
        
        return self.workers  # Return the list of created workers
    
    def on_task_finished(self, success):
        """Callback for when a task finishes."""
        self.active_tasks -= 1
        if self.active_tasks <= 0:
            self.running = False
            # Notify completion
            self.status_callback("批量任务完成")
            # Clear workers list when batch is done
            if not self.running:
                self.workers = [] 