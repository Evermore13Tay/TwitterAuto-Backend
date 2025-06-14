#!/usr/bin/env python3
"""
容器端口管理模块
统一管理MyTRPC和ADB端口的动态获取逻辑
"""

import aiohttp
import asyncio
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

class ContainerPortManager:
    """容器端口管理器 - 统一处理端口获取逻辑"""
    
    def __init__(self, api_base_url: str = "http://127.0.0.1:5000"):
        self.api_base_url = api_base_url
        
    @staticmethod
    def calculate_default_ports(slot_num: int) -> Tuple[int, int]:
        """
        计算默认端口
        
        Args:
            slot_num: 实例位编号（1, 2, 3, 4, 5）
            
        Returns:
            tuple: (u2_port, myt_rpc_port)
        """
        u2_port = 5000 + slot_num        # ADB端口: 5001, 5002, 5003...
        myt_rpc_port = 7100 + slot_num   # HOST_RPA端口: 7101, 7102, 7103...
        return u2_port, myt_rpc_port
    
    async def get_container_ports(
        self, 
        target_ip: str, 
        container_name: str, 
        slot_num: int,
        timeout: int = 10,
        task_id: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        动态获取容器的U2和MyTRPC端口信息
        
        Args:
            target_ip: 目标设备IP
            container_name: 容器名称
            slot_num: 实例位编号（用于默认计算）
            timeout: 请求超时时间
            task_id: 任务ID（用于日志）
            
        Returns:
            tuple: (u2_port, myt_rpc_port)
        """
        # 获取默认端口作为fallback
        default_u2_port, default_myt_rpc_port = self.calculate_default_ports(slot_num)
        u2_port = default_u2_port
        myt_rpc_port = default_myt_rpc_port
        
        try:
            log_prefix = f"[任务{task_id}] " if task_id else ""
            logger.debug(f"{log_prefix}🔍 动态获取端口信息: {container_name}")
            
            async with aiohttp.ClientSession() as session:
                api_info_url = f"{self.api_base_url}/and_api/v1/get_api_info/{target_ip}/{container_name}"
                
                async with session.get(api_info_url, timeout=timeout) as response:
                    if response.status == 200:
                        api_data = await response.json()
                        
                        if api_data.get('code') == 200 and api_data.get('data'):
                            data = api_data['data']
                            
                            # 解析ADB端口（U2端口）
                            adb_info = data.get('ADB', '')
                            if adb_info and ':' in adb_info:
                                try:
                                    u2_port = int(adb_info.split(':')[1])
                                except (ValueError, IndexError):
                                    logger.warning(f"{log_prefix}⚠️ ADB端口解析失败: {adb_info}")
                            
                            # 解析HOST_RPA端口（真正的MyTRPC端口）
                            host_rpa_info = data.get('HOST_RPA', '')
                            if host_rpa_info and ':' in host_rpa_info:
                                try:
                                    myt_rpc_port = int(host_rpa_info.split(':')[1])
                                except (ValueError, IndexError):
                                    logger.warning(f"{log_prefix}⚠️ HOST_RPA端口解析失败: {host_rpa_info}")
                            
                            # 检查是否使用了动态端口
                            if u2_port != default_u2_port or myt_rpc_port != default_myt_rpc_port:
                                logger.debug(f"{log_prefix}🔧 使用动态端口: U2={u2_port}, MyTRPC={myt_rpc_port}")
                            else:
                                logger.debug(f"{log_prefix}🔧 使用默认端口: U2={u2_port}, MyTRPC={myt_rpc_port}")
                            
                            logger.debug(f"{log_prefix}✅ 端口信息获取完成: U2={u2_port}, MyTRPC={myt_rpc_port}")
                            
                        else:
                            logger.warning(f"{log_prefix}⚠️ API返回数据格式异常，使用默认端口")
                            
                    else:
                        logger.warning(f"{log_prefix}⚠️ 获取API信息失败: HTTP {response.status}，使用默认端口")
                        
        except asyncio.TimeoutError:
            logger.warning(f"{log_prefix}⚠️ 获取端口信息超时({timeout}s)，使用默认端口")
        except Exception as e:
            logger.warning(f"{log_prefix}⚠️ 动态获取端口异常: {e}，使用默认端口")
        
        return u2_port, myt_rpc_port
    
    async def get_container_ports_by_slot(
        self,
        target_ip: str,
        slot_num: int,
        timeout: int = 10,
        task_id: Optional[int] = None
    ) -> Tuple[int, int, Optional[str]]:
        """
        根据实例位获取端口信息（自动查找容器名称）
        
        Args:
            target_ip: 目标设备IP
            slot_num: 实例位编号
            timeout: 请求超时时间
            task_id: 任务ID（用于日志）
            
        Returns:
            tuple: (u2_port, myt_rpc_port, container_name)
        """
        log_prefix = f"[任务{task_id}] " if task_id else ""
        
        # 先获取默认端口
        default_u2_port, default_myt_rpc_port = self.calculate_default_ports(slot_num)
        
        try:
            # 获取设备容器列表
            async with aiohttp.ClientSession() as session:
                get_url = f"{self.api_base_url}/get/{target_ip}"
                
                async with session.get(get_url, timeout=timeout) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        
                        if response_data.get('code') == 200:
                            devices = response_data.get('msg', [])
                            
                            # 查找对应实例位的运行中容器
                            for device in devices:
                                if (device.get('index') == slot_num and 
                                    device.get('State') == 'running'):
                                    
                                    container_name = device.get('Names')
                                    if container_name:
                                        logger.debug(f"{log_prefix}🔍 找到实例位{slot_num}的运行容器: {container_name}")
                                        
                                        # 获取该容器的详细端口信息
                                        u2_port, myt_rpc_port = await self.get_container_ports(
                                            target_ip, container_name, slot_num, timeout, task_id
                                        )
                                        
                                        return u2_port, myt_rpc_port, container_name
                            
                            logger.warning(f"{log_prefix}⚠️ 未找到实例位{slot_num}的运行容器，使用默认端口")
                        else:
                            logger.warning(f"{log_prefix}⚠️ 获取容器列表API返回异常，使用默认端口")
                    else:
                        logger.warning(f"{log_prefix}⚠️ 获取容器列表失败: HTTP {response.status}，使用默认端口")
                        
        except asyncio.TimeoutError:
            logger.warning(f"{log_prefix}⚠️ 获取容器信息超时({timeout}s)，使用默认端口")
        except Exception as e:
            logger.warning(f"{log_prefix}⚠️ 获取容器信息异常: {e}，使用默认端口")
        
        return default_u2_port, default_myt_rpc_port, None

# 全局端口管理器实例
port_manager = ContainerPortManager()

# 便捷函数供其他模块调用
async def get_container_ports(
    target_ip: str, 
    container_name: str, 
    slot_num: int,
    task_id: Optional[int] = None
) -> Tuple[int, int]:
    """
    获取容器端口的便捷函数
    
    Args:
        target_ip: 目标设备IP
        container_name: 容器名称  
        slot_num: 实例位编号
        task_id: 任务ID（可选）
        
    Returns:
        tuple: (u2_port, myt_rpc_port)
    """
    return await port_manager.get_container_ports(target_ip, container_name, slot_num, task_id=task_id)

async def get_container_ports_by_slot(
    target_ip: str,
    slot_num: int,
    task_id: Optional[int] = None
) -> Tuple[int, int, Optional[str]]:
    """
    根据实例位获取端口信息的便捷函数
    
    Args:
        target_ip: 目标设备IP
        slot_num: 实例位编号
        task_id: 任务ID（可选）
        
    Returns:
        tuple: (u2_port, myt_rpc_port, container_name)
    """
    return await port_manager.get_container_ports_by_slot(target_ip, slot_num, task_id=task_id)

def calculate_default_ports(slot_num: int) -> Tuple[int, int]:
    """
    计算默认端口的便捷函数
    
    Args:
        slot_num: 实例位编号
        
    Returns:
        tuple: (u2_port, myt_rpc_port)
    """
    return ContainerPortManager.calculate_default_ports(slot_num) 