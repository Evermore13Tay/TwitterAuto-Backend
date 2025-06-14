"""
批量处理器核心模块 - 重构版本
使用模块化架构，将复杂逻辑拆分到子模块中，提高代码可维护性
"""

import logging
from typing import Dict, Any

from .batch_login import BatchManager

logger = logging.getLogger("TwitterAutomationAPI")

class BatchProcessor:
    """
    批量处理器核心类 - 重构版本
    
    这是一个轻量级的包装器，将实际的处理逻辑委托给模块化的BatchManager
    主要职责：
    1. 初始化和配置管理
    2. 提供统一的接口给上层调用
    3. 将具体业务逻辑委托给专门的子模块
    """
    
    def __init__(self, task_manager, device_manager, account_manager, database_handler):
        """
        初始化批量处理器
        
        Args:
            task_manager: 任务管理器
            device_manager: 设备管理器  
            account_manager: 账号管理器
            database_handler: 数据库处理器
        """
        self.task_manager = task_manager
        self.device_manager = device_manager
        self.account_manager = account_manager
        self.database_handler = database_handler
        
        # 初始化模块化的批量管理器
        self.batch_manager = BatchManager(
            task_manager=task_manager,
            device_manager=device_manager,
            account_manager=account_manager,
            database_handler=database_handler
        )
        
        logger.info("✅ 批量处理器已初始化 - 使用模块化架构")
    
    def configure_login_mode(self, mode: str = "efficient"):
        """
        配置登录模式
        
        Args:
            mode: "efficient" 高效模式 或 "conservative" 保守模式 或 "ultra_fast" 极速模式
        """
        return self.batch_manager.configure_login_mode(mode)
    
    def get_current_efficiency_stats(self) -> dict:
        """获取当前效率配置统计"""
        return self.batch_manager.get_current_efficiency_stats()
    
    async def execute_batch_login_backup(self, task_params: Dict[str, Any]) -> bool:
        """
        执行完整的批量登录备份流程
        
        这是主要的入口方法，会调用模块化的BatchManager来处理具体的业务逻辑。
        
        Args:
            task_params: 任务参数，包含：
                - batchLoginBackupParams: 批量参数配置
                - selectedAccountGroup: 选择的账号分组ID
                - 其他相关配置参数
            
        Returns:
            bool: 是否成功执行
        """
        try:
            logger.info(f"[任务{self.task_manager.task_id}] 🚀 开始执行批量登录备份流程 (模块化架构)")
            
            # 委托给模块化的批量管理器执行
            result = await self.batch_manager.execute_batch_login_backup(task_params)
            
            if result:
                logger.info(f"[任务{self.task_manager.task_id}] ✅ 批量登录备份流程执行成功")
            else:
                logger.warning(f"[任务{self.task_manager.task_id}] ❌ 批量登录备份流程执行失败")
            
            return result
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 批量处理器异常: {e}", exc_info=True)
            self.task_manager.fail_task(f"批量处理器异常: {e}")
            return False 