#!/usr/bin/env python3
"""
任务取消检查工具模块
封装任务取消信号检查逻辑，供各种任务模块复用
"""

import asyncio
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

class TaskCancellationChecker:
    """任务取消检查器"""
    
    def __init__(self, task_id: int):
        """
        初始化取消检查器
        
        Args:
            task_id: 任务ID
        """
        self.task_id = task_id
        
    def is_cancelled(self) -> bool:
        """
        检查任务是否被取消
        
        Returns:
            bool: True表示已取消，False表示未取消
        """
        try:
            from utils.connection import active_tasks, active_advanced_tasks
            
            # 检查普通任务列表
            task_info = active_tasks.get(self.task_id)
            if task_info:
                cancel_flag = task_info.get("cancel_flag")
                if cancel_flag and hasattr(cancel_flag, 'is_set') and cancel_flag.is_set():
                    logger.info(f"[任务{self.task_id}] 在普通任务列表中检测到取消标志已设置")
                    return True
                # 如果在普通任务列表中，就不需要检查高级任务列表了
                return False
            
            # 检查高级任务列表
            advanced_task_info = active_advanced_tasks.get(self.task_id)
            if advanced_task_info:
                # 检查取消标志
                cancel_flag = advanced_task_info.get("cancel_flag")
                if cancel_flag and hasattr(cancel_flag, 'is_set') and cancel_flag.is_set():
                    logger.info(f"[任务{self.task_id}] 在高级任务列表中检测到取消标志已设置")
                    return True
                    
                # 检查执行器状态
                executor = advanced_task_info.get("executor")
                if executor and hasattr(executor, 'is_running') and not executor.is_running:
                    logger.info(f"[任务{self.task_id}] 在高级任务列表中检测到执行器is_running=False")
                    return True
                return False
            
            # 如果任务既不在普通任务列表也不在高级任务列表中，只记录一次日志
            if not hasattr(self, '_logged_not_in_any_tasks'):
                logger.debug(f"[任务{self.task_id}] 不在任何活动任务列表中，可能已完成或尚未开始")
                self._logged_not_in_any_tasks = True
            
            return False
            
        except Exception as e:
            logger.warning(f"[任务{self.task_id}] 检查取消状态时出现异常: {e}")
            return False
    
    def check_and_exit_if_cancelled(self, context: str = "", return_value: Any = None) -> bool:
        """
        检查取消状态，如果已取消则记录日志并返回指定值
        
        Args:
            context: 上下文描述，用于日志记录
            return_value: 取消时的返回值
            
        Returns:
            bool: True表示已取消需要退出，False表示可以继续
        """
        if self.is_cancelled():
            logger.info(f"[任务{self.task_id}] ❌ 任务已被取消: {context}")
            self._update_task_status_to_paused()
            return True
        return False
    
    def check_and_return_if_cancelled(self, context: str = "", return_value: Any = None) -> tuple[bool, Any]:
        """
        检查取消状态，如果已取消则返回指定值
        
        Args:
            context: 上下文描述
            return_value: 取消时的返回值
            
        Returns:
            tuple: (是否已取消, 返回值)
        """
        if self.is_cancelled():
            logger.info(f"[任务{self.task_id}] ❌ 任务已被取消: {context}")
            self._update_task_status_to_paused()
            return True, return_value
        return False, None
    
    async def sleep_with_cancel_check(self, total_seconds: float, check_interval: float = 5.0) -> bool:
        """
        分段睡眠并检查取消状态
        
        Args:
            total_seconds: 总等待时间（秒）
            check_interval: 检查间隔（秒）
            
        Returns:
            bool: True表示成功完成等待，False表示被取消
        """
        if total_seconds <= 0:
            return True
            
        segments = max(1, int(total_seconds / check_interval))
        segment_time = total_seconds / segments
        
        for i in range(segments):
            await asyncio.sleep(segment_time)
            
            if self.is_cancelled():
                logger.info(f"[任务{self.task_id}] ❌ 任务在等待期间被取消（{i+1}/{segments}段）")
                self._update_task_status_to_paused()
                return False
                
        return True
    
    def _update_task_status_to_paused(self):
        """更新任务状态为已暂停"""
        try:
            # 动态导入避免循环依赖
            from tasks_api import update_task_status
            update_task_status(self.task_id, '已暂停')
        except Exception as e:
            logger.warning(f"[任务{self.task_id}] 更新任务状态失败: {e}")


# 便捷函数
def create_cancellation_checker(task_id: int) -> TaskCancellationChecker:
    """
    创建任务取消检查器
    
    Args:
        task_id: 任务ID
        
    Returns:
        TaskCancellationChecker: 取消检查器实例
    """
    return TaskCancellationChecker(task_id)


def quick_cancel_check(task_id: int, context: str = "") -> bool:
    """
    快速取消检查（适用于不需要实例化的场景）
    
    Args:
        task_id: 任务ID
        context: 上下文描述
        
    Returns:
        bool: True表示已取消，False表示未取消
    """
    checker = TaskCancellationChecker(task_id)
    return checker.check_and_exit_if_cancelled(context)


async def sleep_with_cancel_check(task_id: int, total_seconds: float, check_interval: float = 5.0, context: str = "") -> bool:
    """
    带取消检查的异步睡眠（便捷函数）- 修复：添加进度打印
    
    Args:
        task_id: 任务ID
        total_seconds: 总等待时间（秒）
        check_interval: 检查间隔（秒）
        context: 上下文描述
        
    Returns:
        bool: True表示成功完成等待，False表示被取消
    """
    checker = TaskCancellationChecker(task_id)
    
    if context:
        logger.info(f"[任务{task_id}] ⏰ 开始等待{total_seconds}秒: {context}")
    
    # 修复：添加进度打印的睡眠逻辑
    if total_seconds <= 0:
        return True
        
    segments = max(1, int(total_seconds / check_interval))
    segment_time = total_seconds / segments
    elapsed_time = 0
    
    for i in range(segments):
        await asyncio.sleep(segment_time)
        elapsed_time += segment_time
        remaining_time = total_seconds - elapsed_time
        
        # 检查取消状态
        if checker.is_cancelled():
            if context:
                logger.info(f"[任务{task_id}] ❌ 等待期间被取消: {context}")
            return False
        
        # 打印进度（只有在有上下文时才打印）
        if context and remaining_time > 0:
            logger.info(f"[任务{task_id}] ⏰ 剩余{remaining_time:.0f}秒: {context}")
    
    if context:
        logger.info(f"[任务{task_id}] ✅ 等待完成: {context}")
    
    return True 