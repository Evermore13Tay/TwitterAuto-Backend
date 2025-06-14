#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
模块化的任务路由文件
整合所有任务相关的API端点
"""

from fastapi import APIRouter, Query, HTTPException, BackgroundTasks, Request
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
    execute_single_login_backup
)
# 注意：container_management模块已删除，相关函数现在是batch_operations内的嵌套函数
try:
    from tasks_modules.rpc_repair import (
        smart_rpc_restart_if_needed,
        get_rpc_repair_stats,
        is_in_rpc_blacklist,
        add_to_rpc_blacklist
    )
except ImportError:
    # 如果rpc_repair模块不存在，使用占位符
    def smart_rpc_restart_if_needed(*args, **kwargs):
        return True
    def get_rpc_repair_stats(*args, **kwargs):
        return {"total_repairs": 0}
    def is_in_rpc_blacklist(*args, **kwargs):
        return False
    def add_to_rpc_blacklist(*args, **kwargs):
        pass

try:
    from tasks_modules.device_utils import perform_real_time_suspension_check
except ImportError:
    # 占位符函数
    async def perform_real_time_suspension_check(*args, **kwargs):
        return False

# 导入原有的依赖 - 增强路径处理
import sys
import os

# 确保项目根目录在Python路径中
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
project_root = os.path.dirname(backend_dir)

# 添加backend目录到Python路径（如果不存在）
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

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
    print(f"[tasks.py] ✅ 所有模块导入成功")
except ImportError as e:
    print(f"[tasks.py] ❌ 模块导入失败: {e}")
    print(f"[tasks.py] Python路径: {sys.path[:3]}")
    print(f"[tasks.py] 当前目录: {current_dir}")
    print(f"[tasks.py] 后端目录: {backend_dir}")
    
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
async def api_get_devices():
    """获取设备列表"""
    try:
        db = SessionLocal()
        devices = db.query(DeviceUser).all()
        
        devices_list = []
        for device in devices:
            devices_list.append({
                'id': device.id,
                'device_name': device.device_name,
                'device_ip': device.device_ip,
                'box_ip': device.box_ip,
                'u2_port': device.u2_port,
                'myt_rpc_port': device.myt_rpc_port,
                'username': device.username,
                'password': device.password,
                'secret_key': device.secret_key,
                'is_busy': device.is_busy
            })
        
        db.close()
        return {'success': True, 'devices': devices_list}
    except Exception as e:
        logger.error(f"获取设备列表失败: {e}")
        return {'success': False, 'message': str(e)}

@router.get("/api/custom-devices")
async def api_get_custom_devices():
    """获取用户自定义的设备IP列表（向后兼容接口）"""
    try:
        db = SessionLocal()
        # 从新的BoxIP表查询活跃的IP地址
        from db.models import BoxIP
        box_ips = db.query(BoxIP.ip_address).filter(
            BoxIP.status == "active"
        ).order_by(BoxIP.created_at.desc()).all()
        
        # 提取IP地址列表
        ip_list = [ip.ip_address for ip in box_ips]
        
        db.close()
        return {'success': True, 'devices': ip_list}
    except Exception as e:
        logger.error(f"获取自定义设备列表失败: {e}")
        return {'success': False, 'message': str(e)}

@router.post("/api/custom-devices")
async def api_add_custom_device(request: Request):
    """添加用户自定义设备IP（向后兼容接口）"""
    try:
        data = await request.json()
        device_ip = data.get('device_ip', '').strip()
        
        if not device_ip:
            return {'success': False, 'message': '设备IP不能为空'}
        
        # 简单的IP格式验证
        import re
        ip_pattern = r'^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        if not re.match(ip_pattern, device_ip):
            return {'success': False, 'message': '无效的IP地址格式'}
        
        db = SessionLocal()
        
        # 检查是否已存在
        from db.models import BoxIP
        existing_box_ip = db.query(BoxIP).filter(
            BoxIP.ip_address == device_ip
        ).first()
        
        if existing_box_ip:
            db.close()
            return {'success': False, 'message': '该设备IP已存在'}
        
        # 创建新的盒子IP记录
        import uuid
        new_box_ip = BoxIP(
            id=str(uuid.uuid4()),
            ip_address=device_ip,
            name=f"自定义设备-{device_ip}",
            status='active'
        )
        
        db.add(new_box_ip)
        db.commit()
        db.close()
        
        return {'success': True, 'message': '设备IP添加成功'}
        
    except Exception as e:
        logger.error(f"添加自定义设备失败: {e}")
        return {'success': False, 'message': str(e)}

@router.delete("/api/custom-devices/{device_ip}")
async def api_delete_custom_device(device_ip: str):
    """删除用户自定义设备IP（向后兼容接口）"""
    try:
        db = SessionLocal()
        
        # 查找并删除盒子IP记录
        from db.models import BoxIP
        box_ip = db.query(BoxIP).filter(
            BoxIP.ip_address == device_ip
        ).first()
        
        if not box_ip:
            db.close()
            return {'success': False, 'message': '设备不存在'}
        
        db.delete(box_ip)
        db.commit()
        db.close()
        
        return {'success': True, 'message': '设备删除成功'}
        
    except Exception as e:
        logger.error(f"删除自定义设备失败: {e}")
        return {'success': False, 'message': str(e)}

@router.get("/api/positions")
async def get_positions_endpoint():
    """获取位置列表"""
    return await api_get_positions()

# @router.get("/api/proxies")
# async def get_proxies_endpoint():
#     """获取代理列表 - 已被新的代理管理系统替代"""
#     return await api_get_proxies()

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
    
    # RPC修复
    'smart_rpc_restart_if_needed',
    'get_rpc_repair_stats',
    'is_in_rpc_blacklist',
    'add_to_rpc_blacklist',
    
    # 设备工具
    'perform_real_time_suspension_check',
    
    # 路由器
    'router'
]

# 为了向后兼容，保留 get_dynamic_ports 的引用
def get_dynamic_ports(*args, **kwargs):
    """[已弃用] 请使用 backend.utils.port_manager.get_container_ports"""
    from utils.port_manager import calculate_default_ports
    if len(args) >= 2:
        slot_num = args[1] if isinstance(args[1], int) else 1
        return calculate_default_ports(slot_num)
    return (5001, 7101)  # 🔧 修正：使用正确的默认HOST_RPA端口 