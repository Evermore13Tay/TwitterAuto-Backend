"""
任务管理核心模块
统一管理任务状态跟踪、取消机制、进度回调、错误处理等功能
"""

import asyncio
import logging
import time
from typing import Callable, Optional, Any, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class TaskStatus:
    """任务状态数据类"""
    task_id: int
    status: str
    progress: float = 0.0
    message: str = ""
    start_time: float = 0.0
    last_update_time: float = 0.0

class TaskManager:
    """任务管理核心类"""
    
    def __init__(self, task_id: int, status_callback: Optional[Callable[[str], None]] = None):
        self.task_id = task_id
        self.status_callback = status_callback or self._default_status_callback
        self.is_running = False
        self.is_cancelled = False
        self.start_time = time.time()
        self.task_status = TaskStatus(task_id=task_id, status='初始化', start_time=self.start_time)
        self.progress_callbacks = []
        self.error_handlers = []
        
        # 重试配置
        self.max_retries = 3
        self.retry_delay = 5
        self.exponential_backoff = True
    
    def _default_status_callback(self, message: str) -> None:
        """默认状态回调函数"""
        logger.info(f"[任务{self.task_id}] {message}")
    
    def start(self) -> None:
        """启动任务"""
        self.is_running = True
        self.is_cancelled = False
        self.task_status.status = '运行中'
        self.task_status.start_time = time.time()
        self.status_callback(f"📋 任务开始执行: {self.task_id}")
        
        # 更新数据库状态
        self._update_database_status('运行中')
        
        # 🔧 **关键修复：向前端广播任务开始状态**
        self._broadcast_status_to_frontend('运行中', '任务启动')
    
    def stop(self) -> None:
        """停止任务"""
        old_running_state = self.is_running
        self.is_running = False
        self.is_cancelled = True
        self.task_status.status = '已停止'
        self.task_status.last_update_time = time.time()
        
        logger.info(f"[任务{self.task_id}] stop() 被调用，is_running从 {old_running_state} 改为 {self.is_running}")
        self.status_callback(f"🛑 任务已停止: {self.task_id}")
        
        # 设置取消标志
        self._set_cancel_flag()
        
        # 更新数据库状态
        self._update_database_status('已暂停')
    
    def check_if_cancelled(self) -> bool:
        """检查任务是否被取消"""
        if self.is_cancelled:
            return True
        
        try:
            # 🔧 **关键修复：检查全局活跃任务列表中的取消标志**
            from utils.connection import active_tasks, active_advanced_tasks
            
            # 首先检查普通活跃任务列表
            if self.task_id in active_tasks:
                task_info = active_tasks[self.task_id]
                cancel_flag = task_info.get("cancel_flag")
                if cancel_flag and hasattr(cancel_flag, 'is_set') and cancel_flag.is_set():
                    logger.info(f"[任务{self.task_id}] 检测到普通任务取消标志")
                    self.is_cancelled = True
                    return True
            
            # 然后检查高级任务列表
            if self.task_id in active_advanced_tasks:
                task_info = active_advanced_tasks[self.task_id]
                cancel_flag = task_info.get("cancel_flag")
                if cancel_flag and hasattr(cancel_flag, 'is_set') and cancel_flag.is_set():
                    logger.info(f"[任务{self.task_id}] 检测到高级任务取消标志")
                    self.is_cancelled = True
                    return True
                    
                # 额外检查执行器状态
                executor = task_info.get("executor")
                if executor and hasattr(executor, 'is_running') and not executor.is_running:
                    logger.info(f"[任务{self.task_id}] 检测到执行器已停止")
                    self.is_cancelled = True
                    return True
            
            return False
            
        except Exception as e:
            logger.warning(f"检查取消状态时异常: {e}")
            return self.is_cancelled
    
    def update_progress(self, progress: float, message: str = "") -> None:
        """
        更新任务进度
        
        Args:
            progress: 进度百分比 (0.0-100.0)
            message: 进度消息
        """
        self.task_status.progress = max(0.0, min(100.0, progress))
        self.task_status.message = message
        self.task_status.last_update_time = time.time()
        
        if message:
            self.status_callback(f"📊 进度 {progress:.1f}%: {message}")
        
        # 通知所有进度回调
        for callback in self.progress_callbacks:
            try:
                callback(self.task_id, progress, message)
            except Exception as e:
                logger.error(f"进度回调异常: {e}")
    
    def add_progress_callback(self, callback: Callable[[int, float, str], None]) -> None:
        """
        添加进度回调函数
        
        Args:
            callback: 回调函数，参数为(task_id, progress, message)
        """
        if callback not in self.progress_callbacks:
            self.progress_callbacks.append(callback)
    
    def remove_progress_callback(self, callback: Callable[[int, float, str], None]) -> None:
        """移除进度回调函数"""
        if callback in self.progress_callbacks:
            self.progress_callbacks.remove(callback)
    
    def add_error_handler(self, handler: Callable[[Exception], None]) -> None:
        """
        添加错误处理器
        
        Args:
            handler: 错误处理函数
        """
        if handler not in self.error_handlers:
            self.error_handlers.append(handler)
    
    async def handle_error_with_retry(self, operation: Callable[..., Any], *args, **kwargs) -> Any:
        """
        带重试的错误处理
        
        Args:
            operation: 要执行的操作函数
            *args, **kwargs: 操作函数的参数
        
        Returns:
            Any: 操作结果
        """
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                # 检查是否被取消
                if self.check_if_cancelled():
                    raise asyncio.CancelledError("任务已被取消")
                
                # 执行操作
                if asyncio.iscoroutinefunction(operation):
                    result = await operation(*args, **kwargs)
                else:
                    result = operation(*args, **kwargs)
                
                # 成功执行，返回结果
                if attempt > 0:
                    self.status_callback(f"✅ 操作在第 {attempt + 1} 次尝试后成功")
                
                return result
                
            except asyncio.CancelledError:
                # 取消错误不应重试
                raise
            except Exception as e:
                last_exception = e
                
                # 通知错误处理器
                for handler in self.error_handlers:
                    try:
                        handler(e)
                    except Exception as handler_error:
                        logger.error(f"错误处理器异常: {handler_error}")
                
                if attempt < self.max_retries:
                    # 计算重试延迟
                    if self.exponential_backoff:
                        delay = self.retry_delay * (2 ** attempt)
                    else:
                        delay = self.retry_delay
                    
                    self.status_callback(f"⚠️ 操作失败，{delay}秒后重试 (第 {attempt + 1}/{self.max_retries + 1} 次): {str(e)}")
                    await asyncio.sleep(delay)
                else:
                    self.status_callback(f"❌ 操作最终失败，已重试 {self.max_retries} 次: {str(e)}")
        
        # 所有重试都失败，抛出最后一个异常
        if last_exception:
            raise last_exception
    
    def get_task_info(self) -> Dict[str, Any]:
        """
        获取任务信息
        
        Returns:
            Dict[str, Any]: 任务信息字典
        """
        current_time = time.time()
        elapsed_time = current_time - self.task_status.start_time
        
        return {
            'task_id': self.task_id,
            'status': self.task_status.status,
            'progress': self.task_status.progress,
            'message': self.task_status.message,
            'is_running': self.is_running,
            'is_cancelled': self.is_cancelled,
            'start_time': self.task_status.start_time,
            'last_update_time': self.task_status.last_update_time,
            'elapsed_time': elapsed_time,
            'elapsed_time_str': self._format_duration(elapsed_time)
        }
    
    def _format_duration(self, seconds: float) -> str:
        """格式化持续时间"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}分{secs:.1f}秒"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = seconds % 60
            return f"{hours}小时{minutes}分{secs:.1f}秒"
    
    def _set_cancel_flag(self) -> None:
        """设置全局取消标志"""
        try:
            from utils.connection import active_tasks, active_advanced_tasks
            
            # 设置普通任务的取消标志
            if self.task_id in active_tasks:
                task_info = active_tasks[self.task_id]
                cancel_flag = task_info.get("cancel_flag")
                if cancel_flag and hasattr(cancel_flag, 'set'):
                    cancel_flag.set()
                    logger.info(f"[任务{self.task_id}] 已设置普通任务取消标志")
            
            # 设置高级任务的取消标志  
            if self.task_id in active_advanced_tasks:
                task_info = active_advanced_tasks[self.task_id]
                cancel_flag = task_info.get("cancel_flag")
                if cancel_flag and hasattr(cancel_flag, 'set'):
                    cancel_flag.set()
                    logger.info(f"[任务{self.task_id}] 已设置高级任务取消标志")
                    
        except Exception as e:
            logger.warning(f"设置取消标志时异常: {e}")
    
    def _update_database_status(self, status: str) -> None:
        """更新数据库中的任务状态"""
        try:
            # 根据上下文导入合适的函数
            try:
                from tasks_api import update_task_status
            except ImportError:
                try:
                    from mysql_tasks_api import update_task_status
                except ImportError:
                    logger.warning(f"[任务{self.task_id}] 无法导入任务状态更新函数")
                    return
            
            update_result = update_task_status(self.task_id, status)
            
            if isinstance(update_result, dict) and update_result.get('success'):
                logger.info(f"[任务{self.task_id}] 任务状态已更新为: {status}")
            else:
                error_msg = update_result.get('message', '未知错误') if isinstance(update_result, dict) else str(update_result)
                if "任务不存在" in error_msg:
                    logger.info(f"[任务{self.task_id}] 数据库中无此任务ID，跳过状态更新（正常情况）")
                else:
                    logger.warning(f"[任务{self.task_id}] 更新任务状态失败: {error_msg}")
                
        except Exception as e:
            logger.error(f"[任务{self.task_id}] 更新数据库状态异常: {e}")
    
    def _broadcast_status_to_frontend(self, status: str, message: str) -> None:
        """向前端广播任务状态变化"""
        try:
            # 导入异步连接管理器
            from utils.connection import manager
            import asyncio
            
            # 获取或创建事件循环
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # 如果没有运行的事件循环，创建一个新的
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 创建异步任务来广播状态
            if loop.is_running():
                # 如果循环正在运行，使用create_task
                asyncio.create_task(
                    manager.broadcast_task_status_change(
                        task_id=str(self.task_id),
                        new_status=status,
                        task_name=f"批量任务-{self.task_id}"
                    )
                )
            else:
                # 如果循环没有运行，直接运行
                loop.run_until_complete(
                    manager.broadcast_task_status_change(
                        task_id=str(self.task_id),
                        new_status=status,
                        task_name=f"批量任务-{self.task_id}"
                    )
                )
            
            logger.info(f"[任务{self.task_id}] ✅ 已向前端广播状态变化: {status}")
            
        except Exception as e:
            logger.warning(f"[任务{self.task_id}] ⚠️ 向前端广播状态失败: {e}")
    
    async def wait_with_cancellation_check(self, seconds: int, description: str = "") -> bool:
        """等待指定时间，期间检查取消状态"""
        import asyncio
        
        try:
            if description:
                self.status_callback(f"⏰ 等待 {seconds} 秒 ({description})...")
            else:
                self.status_callback(f"⏰ 等待 {seconds} 秒...")
            
            for i in range(seconds):
                # 🔧 **关键修复：每秒检查取消状态**
                if self.check_if_cancelled():
                    self.status_callback(f"任务已被取消，中断等待")
                    return False
                
                await asyncio.sleep(1)
                
                # 每10秒报告一次进度
                if (i + 1) % 10 == 0 and (i + 1) < seconds:
                    remaining = seconds - (i + 1)
                    desc_text = f" ({description})" if description else ""
                    self.status_callback(f"⏰ 还需等待 {remaining} 秒{desc_text}...")
            
            return True
            
        except Exception as e:
            logger.error(f"等待过程中出现异常: {e}")
            return False
    
    def complete_task(self, final_message: str = "任务完成") -> None:
        """
        完成任务
        
        Args:
            final_message: 最终消息
        """
        self.is_running = False
        self.task_status.status = '已完成'
        self.task_status.progress = 100.0
        self.task_status.message = final_message
        self.task_status.last_update_time = time.time()
        
        elapsed_time = self.task_status.last_update_time - self.task_status.start_time
        self.status_callback(f"✅ {final_message} (耗时: {self._format_duration(elapsed_time)})")
        
        # 更新数据库状态
        self._update_database_status('已完成')
        
        # 🔧 **关键修复：向前端广播任务完成状态**
        self._broadcast_status_to_frontend('已完成', final_message)
    
    def fail_task(self, error_message: str = "任务失败") -> None:
        """
        任务失败
        
        Args:
            error_message: 错误消息
        """
        self.is_running = False
        self.task_status.status = '失败'
        self.task_status.message = error_message
        self.task_status.last_update_time = time.time()
        
        elapsed_time = self.task_status.last_update_time - self.task_status.start_time
        self.status_callback(f"❌ {error_message} (耗时: {self._format_duration(elapsed_time)})")
        
        # 更新数据库状态
        self._update_database_status('失败')
        
        # 🔧 **关键修复：向前端广播任务失败状态**
        self._broadcast_status_to_frontend('失败', error_message) 