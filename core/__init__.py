"""
核心模块包
重构后的核心业务模块集合
"""

# 核心管理器
from .device_manager import DeviceManager
from .account_manager import AccountManager
from .task_manager import TaskManager
from .database_handler import DatabaseHandler
from .api_client import ApiClient
from .batch_processor import BatchProcessor
from .nurture_processor import NurtureProcessor

# 操作工具
from .operation_tools import (
    OperationTools,
    optimized_delayed_login_only,
    optimized_delayed_backup_only,
    optimized_cleanup_container,
    perform_real_time_suspension_check,
    execute_single_batch_operation,
    get_dynamic_ports,
    cleanup_container,
    smart_rpc_restart_if_needed
)

__all__ = [
    # 核心管理器
    'DeviceManager',
    'AccountManager', 
    'TaskManager',
    'DatabaseHandler',
    'ApiClient',
    'BatchProcessor',
    'NurtureProcessor',
    
    # 操作工具
    'OperationTools',
    'optimized_delayed_login_only',
    'optimized_delayed_backup_only',
    'optimized_cleanup_container',
    'perform_real_time_suspension_check',
    'execute_single_batch_operation',
    'get_dynamic_ports',
    'cleanup_container',
    'smart_rpc_restart_if_needed'
]

# 版本信息
__version__ = "2.0.0"
__description__ = "重构后的Twitter应用核心模块架构"

# 模块信息
CORE_MODULES = {
    'DeviceManager': '设备和容器管理',
    'AccountManager': '账号管理和验证',
    'TaskManager': '任务状态和进度管理',
    'DatabaseHandler': '数据库操作封装',
    'ApiClient': 'HTTP请求客户端',
    'BatchProcessor': '批量处理器',
    'NurtureProcessor': '自动养号处理器',
    'OperationTools': '操作工具集'
} 