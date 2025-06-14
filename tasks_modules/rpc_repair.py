"""
RPC修复机制模块
包含智能RPC重启、统计和黑名单管理功能
"""

import asyncio
import aiohttp
import socket
import time
from datetime import datetime, timedelta
from typing import Dict, Tuple
from common.logger import logger

# === 📡 智能RPC重启机制：全局统计和黑名单 ===

# 全局修复统计
RPC_REPAIR_STATS = {
    'total_attempts': 0,
    'successful_repairs': 0,
    'failed_repairs': 0,
    'last_reset_time': datetime.now()
}

# 修复失败黑名单 {container_name: last_attempt_time}
RPC_BLACKLIST = {}

def is_in_rpc_blacklist(container_name: str) -> bool:
    """检查容器是否在RPC修复黑名单中"""
    if container_name in RPC_BLACKLIST:
        last_attempt = RPC_BLACKLIST[container_name]
        # 30分钟后重新尝试
        if datetime.now() - last_attempt < timedelta(minutes=30):
            return True
        else:
            # 过期移除
            del RPC_BLACKLIST[container_name]
    return False

def add_to_rpc_blacklist(container_name: str):
    """将容器添加到RPC修复黑名单"""
    RPC_BLACKLIST[container_name] = datetime.now()

def get_rpc_repair_stats():
    """获取RPC修复统计信息"""
    total = RPC_REPAIR_STATS['total_attempts']
    success_rate = 0 if total == 0 else (RPC_REPAIR_STATS['successful_repairs'] / total * 100)
    
    return {
        **RPC_REPAIR_STATS,
        'success_rate': f"{success_rate:.1f}%",
        'blacklist_count': len(RPC_BLACKLIST),
        'blacklisted_containers': list(RPC_BLACKLIST.keys())
    }

# === 📡 智能RPC重启机制：通用函数 ===
async def smart_rpc_restart_if_needed(target_ip: str, slot_num: int, container_name: str, task_id: int, repair_level: str = "full") -> bool:
    """
    智能RPC重启机制：检测RPC连接失败时自动重启容器修复RPC服务
    
    Args:
        target_ip: 目标设备IP
        slot_num: 实例位编号
        container_name: 容器名称
        task_id: 任务ID
        repair_level: 修复级别 ("light"=30秒等待, "full"=60秒等待)
        
    Returns:
        bool: True表示RPC可用，False表示RPC不可用
    """
    # 🔧 检查黑名单，避免无效重复修复
    if is_in_rpc_blacklist(container_name):
        logger.warning(f"[任务{task_id}] ⚫ 容器 {container_name} 在修复黑名单中，跳过修复")
        return False
    
    # 记录修复尝试
    RPC_REPAIR_STATS['total_attempts'] += 1
    repair_start_time = time.time()
    
    # 🔧 使用统一的端口管理器获取端口信息
    from utils.port_manager import get_container_ports
    _, myt_rpc_port = await get_container_ports(target_ip, container_name, slot_num, task_id)
    
    # 快速RPC连接检测
    def check_rpc_connection(ip, port, timeout=3):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            return result == 0
        except:
            return False
    
    logger.info(f"[任务{task_id}] 🔍 检测RPC连接状态: {target_ip}:{myt_rpc_port}")
    rpc_ok = check_rpc_connection(target_ip, myt_rpc_port)
    
    if rpc_ok:
        logger.info(f"[任务{task_id}] ✅ RPC连接正常: {target_ip}:{myt_rpc_port}")
        # 无需修复，但记录成功
        RPC_REPAIR_STATS['successful_repairs'] += 1
        return True
    else:
        logger.warning(f"[任务{task_id}] ❌ RPC连接失败: {target_ip}:{myt_rpc_port}，开始智能重启")
        
        # 重启容器修复RPC服务
        restart_success = False
        try:
            logger.info(f"[任务{task_id}] 🔄 智能重启容器修复RPC: {container_name}")
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:5000/reboot/{target_ip}/{container_name}") as response:
                    if response.status == 200:
                        logger.info(f"[任务{task_id}] ✅ 容器重启成功: {container_name}")
                        restart_success = True
                    else:
                        logger.error(f"[任务{task_id}] ❌ 容器重启失败: HTTP {response.status}")
        
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 容器重启异常: {e}")
        
        if restart_success:
            # 🔧 根据修复级别调整等待时间
            if repair_level == "light":
                wait_time = 30  # 轻量修复等待30秒
                logger.info(f"[任务{task_id}] ⏰ 轻量修复，等待容器重启完成 ({wait_time}秒)...")
            else:
                wait_time = 60  # 完整修复等待60秒
                logger.info(f"[任务{task_id}] ⏰ 完整修复，等待容器重启完成和RPC服务启动 ({wait_time}秒)...")
            await asyncio.sleep(wait_time)
            
            # 🔧 重启后重新获取RPC端口信息（可能发生变化）
            _, new_myt_rpc_port = await get_container_ports(target_ip, container_name, slot_num, task_id)
            
            if new_myt_rpc_port != myt_rpc_port:
                logger.info(f"[任务{task_id}] 📝 RPC端口发生变化: {myt_rpc_port} → {new_myt_rpc_port}")
                myt_rpc_port = new_myt_rpc_port
            
            # 重新检测RPC连接
            logger.info(f"[任务{task_id}] 🔍 重新检测RPC连接: {target_ip}:{myt_rpc_port}")
            rpc_ok_after_restart = check_rpc_connection(target_ip, myt_rpc_port)
            
            if rpc_ok_after_restart:
                # 修复成功，记录统计和耗时
                repair_duration = time.time() - repair_start_time
                RPC_REPAIR_STATS['successful_repairs'] += 1
                logger.info(f"[任务{task_id}] ✅ 智能重启成功，RPC服务已恢复: {target_ip}:{myt_rpc_port} (耗时{repair_duration:.1f}秒)")
                return True
            else:
                # 修复失败，记录统计并加入黑名单
                repair_duration = time.time() - repair_start_time
                RPC_REPAIR_STATS['failed_repairs'] += 1
                add_to_rpc_blacklist(container_name)
                logger.error(f"[任务{task_id}] ❌ 智能重启后RPC仍无法连接: {target_ip}:{myt_rpc_port} (耗时{repair_duration:.1f}秒，已加入黑名单)")
                return False
        else:
            # 重启失败，记录统计并加入黑名单
            repair_duration = time.time() - repair_start_time
            RPC_REPAIR_STATS['failed_repairs'] += 1
            add_to_rpc_blacklist(container_name)
            logger.error(f"[任务{task_id}] ❌ 智能重启失败，无法修复RPC服务 (耗时{repair_duration:.1f}秒，已加入黑名单)")
            return False

# 📝 注意：原来的 get_dynamic_ports 函数已移至 backend.utils.port_manager 模块
# 现在统一使用 port_manager.get_container_ports() 来获取端口信息
