"""
设备路由工具函数
包含端口查找、缓存管理等通用功能
"""
import logging
import hashlib
import time
from typing import Optional, Set
from sqlalchemy.orm import Session
from db import models

# 配置日志
logger = logging.getLogger(__name__)

# 简单的内存缓存
_device_cache = {}
_cache_timestamps = {}

def cache_key(page: int, page_size: int, search: Optional[str]) -> str:
    """生成缓存键"""
    key_str = f"{page}:{page_size}:{search or ''}"
    return hashlib.md5(key_str.encode()).hexdigest()

def clear_device_cache():
    """清理设备缓存"""
    global _device_cache, _cache_timestamps
    _device_cache.clear()
    _cache_timestamps.clear()
    logger.debug("设备缓存已清理")

def find_unused_port(db: Session, port_type: str, start_port: int, device_ip: str, excluded_ports_in_session: Set[int]) -> Optional[int]:
    """
    查找指定IP下未使用的端口，同时排除已在当前会话中分配的端口
    
    参数:
    - db: 数据库会话
    - port_type: 端口类型 ('u2_port' 或 'myt_rpc_port')
    - start_port: 起始端口号
    - device_ip: 设备IP地址
    - excluded_ports_in_session: 当前会话中已分配的端口集合
    
    返回:
    - 可用的端口号，如果找不到则返回None
    """
    current_port = start_port
    max_attempts = 1000  # 定义合理的端口搜索尝试限制
    attempts = 0

    while attempts < max_attempts:
        if current_port in excluded_ports_in_session:
            current_port += 1
            attempts += 1
            continue

        if port_type == 'u2_port':
            existing_in_db = db.query(models.DeviceUser.id).filter(
                models.DeviceUser.device_ip == device_ip,
                models.DeviceUser.u2_port == current_port
            ).first()
        elif port_type == 'myt_rpc_port':
            existing_in_db = db.query(models.DeviceUser.id).filter(
                models.DeviceUser.device_ip == device_ip,
                models.DeviceUser.myt_rpc_port == current_port
            ).first()
        else:
            logger.error(f"Unknown port_type '{port_type}' in find_unused_port")
            return None
            
        if not existing_in_db:
            return current_port
            
        current_port += 1
        attempts += 1

    logger.warning(
        f"find_unused_port for {port_type} on device_ip {device_ip} "
        f"exceeded {max_attempts} attempts from start_port {start_port}. Returning None."
    )
    return None

def apply_exclusivity_rule(db: Session, device_index: int, current_device_id: Optional[str], 
                          logger_instance, disable_for_refresh=False):
    """
    应用设备索引排他性规则
    
    参数:
    - db: SQLAlchemy数据库会话
    - device_index: 要检查排他性的设备索引
    - current_device_id: 当前设备的ID（从检查中排除）
    - logger_instance: 用于记录操作的日志器
    - disable_for_refresh: 为True时，此函数将记录但不应用任何排他性规则
    """
    if disable_for_refresh:
        logger_instance.info(f"Exclusivity check for index {device_index} SKIPPED (disabled for refresh operation)")
        return
        
    if device_index is None or device_index <= 0:
        # 排除空或非正索引（0是特殊情况）
        logger_instance.info(f"Skipping exclusivity for index {device_index} (exempt from rules)")
        return

    logger_instance.info(f"Applying exclusivity for index {device_index}. Current device ID: {current_device_id}")
    
    query = db.query(models.DeviceUser).filter(
        models.DeviceUser.device_index == device_index,
        models.DeviceUser.status == 'online'
    )
    if current_device_id:
        query = query.filter(models.DeviceUser.id != current_device_id)
    
    others_online_same_index = query.all()

    for other_dev in others_online_same_index:
        logger_instance.info(f"Setting other device {other_dev.device_name} (ID: {other_dev.id}, Index: {device_index}) to offline due to exclusivity.")
        other_dev.status = 'offline'
        db.add(other_dev)  # 确保它是会话更改的一部分 