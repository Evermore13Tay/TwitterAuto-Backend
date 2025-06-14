#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块化的任务路由文件
整合所有任务相关的API端点
"""

from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
import sys
import os

# 添加项目根目录到sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# 导入模块化的组件
from tasks_modules.models import TaskCreate, TaskStatusUpdate
from tasks_modules.api_handlers import (
    api_get_tasks,
    api_create_task,
    api_delete_task,
    api_get_task_templates,
    api_get_task_statistics,
    api_get_devices,
    api_get_positions,
    api_get_proxies,
    api_get_rpc_repair_stats,
    api_clear_rpc_blacklist,
    api_execute_task,
    api_test_execute_task,
    api_stop_task
)
from tasks_modules.batch_operations import (
    execute_batch_login_backup_task,
    execute_single_batch_operation
)
from tasks_modules.login_backup import (
    execute_single_login_backup,
    optimized_delayed_login_only,
    optimized_delayed_backup_only
)

from tasks_modules.rpc_repair import (
    smart_rpc_restart_if_needed,
    get_dynamic_ports,
    get_rpc_repair_stats,
    is_in_rpc_blacklist,
    add_to_rpc_blacklist
)
from tasks_modules.device_utils import perform_real_time_suspension_check

# 导入原有的依赖
try:
    from mysql_tasks_api import (
        get_tasks, 
        create_task, 
        update_task_status, 
        delete_task, 
        get_task_templates, 
        get_task_statistics
    )
    from db.database import SessionLocal
    from db.models import DeviceUser
    from utils.advanced_task_executor import AdvancedAutoNurtureTaskExecutor
    from utils.connection import manager
except ImportError as e:
    print(f"Warning: Some legacy modules could not be imported: {e}")
    # 创建占位符函数
    def get_tasks(*args, **kwargs):
        return {'success': False, 'message': 'Legacy API not available'}
    def create_task(*args, **kwargs):
        return {'success': False, 'message': 'Legacy API not available'}
    def update_task_status(*args, **kwargs):
        return {'success': False, 'message': 'Legacy API not available'}
    def delete_task(*args, **kwargs):
        return {'success': False, 'message': 'Legacy API not available'}
    def get_task_templates(*args, **kwargs):
        return {'success': False, 'message': 'Legacy API not available'}
    def get_task_statistics(*args, **kwargs):
        return {'success': False, 'message': 'Legacy API not available'}
    
    class AdvancedAutoNurtureTaskExecutor:
        def __init__(self, *args, **kwargs):
            pass
        async def execute_auto_nurture_task(self, *args, **kwargs):
            return False
    
    class manager:
        @staticmethod
        async def send_message(*args, **kwargs):
            pass

import logging
logger = logging.getLogger("TwitterAutomationAPI")

# 创建路由器
router = APIRouter(tags=["tasks"])

# === 📋 任务管理 API ===

@router.get("/api/tasks")
async def get_tasks_endpoint(
    search: str = Query("", description="搜索关键词"),
    status: str = Query("全部", description="状态筛选"),
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(10, ge=1, le=100, description="每页数量")
):
    """获取任务列表"""
    return await api_get_tasks(search, status, page, per_page)

@router.post("/api/tasks")
async def create_task_endpoint(task: TaskCreate, background_tasks: BackgroundTasks):
    """创建新任务"""
    return await api_create_task(task, background_tasks)

@router.delete("/api/tasks/{task_id}")
async def delete_task_endpoint(task_id: int):
    """删除任务"""
    return await api_delete_task(task_id)

@router.get("/api/tasks/templates")
async def get_task_templates_endpoint():
    """获取任务模板"""
    return await api_get_task_templates()

@router.get("/api/tasks/statistics")
async def get_task_statistics_endpoint():
    """获取任务统计"""
    return await api_get_task_statistics()

# === 📋 任务执行 API ===

@router.post("/api/tasks/{task_id}/execute")
async def execute_task_endpoint(task_id: int, background_tasks: BackgroundTasks):
    """执行任务"""
    return await api_execute_task(task_id, background_tasks)

@router.post("/api/tasks/{task_id}/test-execute")
async def test_execute_task_endpoint(task_id: int):
    """测试执行任务"""
    return await api_test_execute_task(task_id)

@router.post("/api/tasks/{task_id}/stop")
async def stop_task_endpoint(task_id: int):
    """停止任务"""
    return await api_stop_task(task_id)

# === 📋 资源管理 API ===

@router.get("/api/devices")
async def get_devices_endpoint():
    """获取设备列表"""
    return await api_get_devices()

@router.get("/api/positions")
async def get_positions_endpoint():
    """获取位置列表"""
    return await api_get_positions()

@router.get("/api/proxies")
async def get_proxies_endpoint():
    """获取代理列表"""
    return await api_get_proxies()

# === 📡 RPC管理 API ===

@router.get("/api/rpc/repair-stats")
async def get_rpc_repair_stats_endpoint():
    """获取RPC修复统计"""
    return await api_get_rpc_repair_stats()

@router.post("/api/rpc/clear-blacklist")
async def clear_rpc_blacklist_endpoint():
    """清除RPC修复黑名单"""
    return await api_clear_rpc_blacklist()

# === 📋 兼容性函数（保持向后兼容） ===

# 导出模块化函数供其他模块使用
__all__ = [
    # 模型
    'TaskCreate', 'TaskStatusUpdate',
    
    # 批量操作
    'execute_batch_login_backup_task',
    'execute_single_batch_operation',
    
    # 登录备份
    'execute_single_login_backup',
    'optimized_delayed_login_only',
    'optimized_delayed_backup_only',
    
    # 容器管理
    'optimized_cleanup_container',
    'reboot_device',
    'set_proxy_device',
    'set_language_device',
    
    # RPC修复
    'smart_rpc_restart_if_needed',
    'get_dynamic_ports',
    'get_rpc_repair_stats',
    'is_in_rpc_blacklist',
    'add_to_rpc_blacklist',
    
    # 设备工具
    'perform_real_time_suspension_check',
    
    # 路由器
    'router'
] 