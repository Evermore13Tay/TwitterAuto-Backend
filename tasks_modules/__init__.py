"""
Tasks modules package
模块化任务管理包
"""

from .models import TaskCreate, TaskStatusUpdate
from .api_handlers import *
from .batch_operations import execute_batch_login_backup_task, execute_single_batch_operation

# 以下模块为可选导入，如果不存在则跳过
try:
    from .device_utils import perform_real_time_suspension_check
except ImportError:
    async def perform_real_time_suspension_check(*args, **kwargs):
        return False

try:
    from .login_backup import execute_single_login_backup
except ImportError:
    async def execute_single_login_backup(*args, **kwargs):
        return False

try:
    from .rpc_repair import (
        smart_rpc_restart_if_needed,
        get_rpc_repair_stats,
        is_in_rpc_blacklist,
        add_to_rpc_blacklist
    )
except ImportError:
    def smart_rpc_restart_if_needed(*args, **kwargs):
        return True
    def get_rpc_repair_stats(*args, **kwargs):
        return {"total_repairs": 0}
    def is_in_rpc_blacklist(*args, **kwargs):
        return False
    def add_to_rpc_blacklist(*args, **kwargs):
        pass

# 为了向后兼容，保留 get_dynamic_ports 的引用
def get_dynamic_ports(*args, **kwargs):
    """[已弃用] 请使用 backend.utils.port_manager.get_container_ports"""
    from utils.port_manager import calculate_default_ports
    if len(args) >= 2:
        slot_num = args[1] if isinstance(args[1], int) else 1
        return calculate_default_ports(slot_num)
    return (5001, 7101)  # 🔧 修正：使用正确的默认HOST_RPA端口

__version__ = "1.0.0"

__all__ = [
    # Models
    'TaskCreate', 'TaskStatusUpdate',
    
    # Batch operations
    'execute_batch_login_backup_task',
    'execute_single_batch_operation',
    
    # Device utils
    'perform_real_time_suspension_check',
    
    # Login backup
    'execute_single_login_backup',
    
    # RPC repair
    'smart_rpc_restart_if_needed',
    'get_rpc_repair_stats',
    'is_in_rpc_blacklist',
    'add_to_rpc_blacklist',
]
