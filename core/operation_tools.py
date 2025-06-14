"""
操作工具模块
包含独立的操作功能，如登录、备份、容器清理等
"""

import asyncio
import aiohttp
import logging
import time
from typing import Dict, Any, Optional

try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

class OperationTools:
    """操作工具集"""
    
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        if self.session:
            await self.session.close()
    
    async def delayed_login_operation(self, slot_num: int, account: dict, container_name: str, 
                                    target_ip: str, task_id: int, delay: int = 0) -> dict:
        """延迟登录操作"""
        try:
            if delay > 0:
                logger.info(f"[任务{task_id}] ⏱️ 登录延迟 {delay} 秒...")
                await asyncio.sleep(delay)
            
            # 检查任务取消状态
            try:
                from utils.task_cancellation import quick_cancel_check
                if quick_cancel_check(task_id, f"登录操作前 - 容器{container_name}"):
                    return {"success": False, "message": "任务已取消"}
            except ImportError:
                logger.debug("未找到任务取消检查模块")
            
            logger.info(f"[任务{task_id}] 🔑 开始登录操作: {account['username']} (容器: {container_name})")
            
            session = None
            try:
                session = aiohttp.ClientSession()
                # 🔧 修复：使用正确的登录API路径，通过自建API服务
                login_url = "http://127.0.0.1:8000/api/single-account-login"
                
                # 🔧 修复：使用正确的登录参数格式，需要设备信息和端口
                from utils.port_manager import calculate_default_ports
                u2_port, myt_rpc_port = calculate_default_ports(slot_num)
                
                login_data = {
                    "deviceIp": target_ip,
                    "u2Port": str(u2_port),
                    "mytRpcPort": str(myt_rpc_port),
                    "username": account['username'],
                    "password": account.get('password', ''),
                    "secretKey": account.get('secretkey', '')
                }
                
                async with session.post(login_url, json=login_data, timeout=aiohttp.ClientTimeout(total=240)) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        if response_data.get('code') == 200:
                            logger.info(f"[任务{task_id}] ✅ 账号 {account['username']} 登录成功")
                            return {
                                "success": True,
                                "message": "登录成功",
                                "account": account['username'],
                                "container": container_name
                            }
                        else:
                            message = response_data.get('message', '未知错误')
                            logger.error(f"[任务{task_id}] ❌ 账号 {account['username']} 登录失败: {message}")
                            return {
                                "success": False,
                                "message": f"登录失败: {message}",
                                "account": account['username'],
                                "container": container_name
                            }
                    else:
                        logger.error(f"[任务{task_id}] ❌ 账号 {account['username']} 登录失败: HTTP {response.status}")
                        return {
                            "success": False,
                            "message": f"HTTP错误: {response.status}",
                            "account": account['username'],
                            "container": container_name
                        }
            finally:
                if session and not session.closed:
                    await session.close()
                    await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 登录操作异常: {e}")
            return {
                "success": False,
                "message": f"登录异常: {str(e)}",
                "account": account.get('username', '未知'),
                "container": container_name
            }
    
    async def delayed_backup_operation(self, slot_num: int, account: dict, container_name: str,
                                     target_ip: str, task_id: int, delay: int = 0) -> dict:
        """延迟备份操作"""
        try:
            if delay > 0:
                logger.info(f"[任务{task_id}] ⏱️ 备份延迟 {delay} 秒...")
                await asyncio.sleep(delay)
            
            # 检查任务取消状态
            try:
                from utils.task_cancellation import quick_cancel_check
                if quick_cancel_check(task_id, f"备份操作前 - 容器{container_name}"):
                    return {"success": False, "message": "任务已取消"}
            except ImportError:
                logger.debug("未找到任务取消检查模块")
            
            logger.info(f"[任务{task_id}] 💾 开始备份操作: {account['username']} (容器: {container_name})")
            
            session = None
            try:
                session = aiohttp.ClientSession()
                # 🔧 修复：使用正确的备份API路径
                backup_url = f"http://127.0.0.1:5000/dc_api/v1/batch_export/{target_ip}"
                
                # 生成备份文件名
                timestamp = int(time.time())
                backup_filename = f"{account['username']}_{timestamp}_backup.pac"
                
                # 🔧 修复：使用正确的备份参数格式
                backup_path = f"D:/mytBackUp/{backup_filename}"
                backup_params = {
                    'name': container_name,
                    'localPath': backup_path
                }
                
                async with session.get(backup_url, params=backup_params, timeout=aiohttp.ClientTimeout(total=300)) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        if response_data.get('code') == 200:
                            logger.info(f"[任务{task_id}] ✅ 账号 {account['username']} 备份成功: {backup_filename}")
                            
                            # 更新数据库备份状态
                            try:
                                from core.database_handler import DatabaseHandler
                                db_handler = DatabaseHandler()
                                account_id = db_handler.get_account_id_by_username(account['username'])
                                if account_id:
                                    db_handler.update_account_backup_status(account_id, 1)
                            except Exception as db_error:
                                logger.warning(f"更新备份状态失败: {db_error}")
                            
                            return {
                                "success": True,
                                "message": "备份成功",
                                "account": account['username'],
                                "container": container_name,
                                "backup_file": backup_filename
                            }
                        else:
                            message = response_data.get('message', '未知错误')
                            logger.error(f"[任务{task_id}] ❌ 账号 {account['username']} 备份失败: {message}")
                            return {
                                "success": False,
                                "message": f"备份失败: {message}",
                                "account": account['username'],
                                "container": container_name
                            }
                    else:
                        logger.error(f"[任务{task_id}] ❌ 账号 {account['username']} 备份失败: HTTP {response.status}")
                        return {
                            "success": False,
                            "message": f"HTTP错误: {response.status}",
                            "account": account['username'],
                            "container": container_name
                        }
            finally:
                if session and not session.closed:
                    await session.close()
                    await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 备份操作异常: {e}")
            return {
                "success": False,
                "message": f"备份异常: {str(e)}",
                "account": account.get('username', '未知'),
                "container": container_name
            }
    
    async def cleanup_container_operation(self, container_name: str, target_ip: str, task_id: int) -> dict:
        """清理容器操作"""
        try:
            logger.info(f"[任务{task_id}] 🗑️ 开始清理容器: {container_name}")
            
            session = None
            try:
                session = aiohttp.ClientSession()
                
                # 首先停止容器
                stop_url = f"http://127.0.0.1:5000/stop/{target_ip}/{container_name}"
                async with session.get(stop_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        logger.info(f"[任务{task_id}] ✅ 容器 {container_name} 停止成功")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ 容器 {container_name} 停止失败: HTTP {response.status}")
                
                # 等待一下确保容器完全停止
                await asyncio.sleep(2)
                
                # 删除容器
                remove_url = f"http://127.0.0.1:5000/remove/{target_ip}/{container_name}"
                async with session.get(remove_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        if response_data.get('code') == 200:
                            logger.info(f"[任务{task_id}] ✅ 容器 {container_name} 清理成功")
                            return {
                                "success": True,
                                "message": "容器清理成功",
                                "container": container_name
                            }
                        else:
                            message = response_data.get('message', '未知错误')
                            logger.warning(f"[任务{task_id}] ⚠️ 容器 {container_name} 清理失败: {message}")
                            return {
                                "success": False,
                                "message": f"清理失败: {message}",
                                "container": container_name
                            }
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ 容器 {container_name} 清理失败: HTTP {response.status}")
                        return {
                            "success": False,
                            "message": f"HTTP错误: {response.status}",
                            "container": container_name
                        }
            finally:
                if session and not session.closed:
                    await session.close()
                    await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 容器清理异常: {e}")
            return {
                "success": False,
                "message": f"清理异常: {str(e)}",
                "container": container_name
            }
    
    async def perform_real_time_suspension_check(self, task_id: int, device_ip: str, 
                                                instance_slot: int, account: dict, 
                                                is_suspended: bool, container_name: str = None) -> bool:
        """实时封号检测"""
        try:
            # 尝试导入设备工具模块
            try:
                from tasks_modules.device_utils import perform_real_time_suspension_check as device_utils_check
                return await device_utils_check(task_id, device_ip, instance_slot, account, is_suspended, container_name)
            except ImportError:
                logger.debug("未找到device_utils模块，使用内置检测")
            
            # 简单的内置检测逻辑
            if is_suspended:
                logger.warning(f"[任务{task_id}] ⚠️ 账号 {account.get('username', '未知')} 已被标记为封号")
                return True
            
            # 这里可以添加更复杂的封号检测逻辑
            # 例如：检查账号状态、API调用等
            
            logger.debug(f"[任务{task_id}] ✅ 账号 {account.get('username', '未知')} 封号检测通过")
            return False
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 封号检测异常: {e}")
            # 检测异常时，保守地返回原状态
            return is_suspended
    
    async def execute_single_batch_operation(self, task_params: dict) -> dict:
        """执行单轮批量操作"""
        try:
            task_id = task_params.get('task_id', 0)
            logger.info(f"[任务{task_id}] 🚀 开始执行单轮批量操作")
            
            # 检查任务取消状态
            try:
                from utils.task_cancellation import quick_cancel_check, sleep_with_cancel_check
                if quick_cancel_check(task_id, "单轮批量操作"):
                    return {"success": False, "message": "单轮批量操作被取消"}
            except ImportError:
                logger.debug("未找到任务取消检查模块")
                sleep_with_cancel_check = None
            
            # 这里可以添加单轮批量操作的具体逻辑
            operation_count = 0
            
            # 模拟一些操作
            operations = task_params.get('operations', [])
            for i, operation in enumerate(operations):
                logger.info(f"[任务{task_id}] 执行操作 {i+1}/{len(operations)}: {operation.get('type', '未知')}")
                
                # 检查取消状态
                if sleep_with_cancel_check:
                    success = await sleep_with_cancel_check(task_id, 1, 0.5, f"操作{i+1}等待")
                    if not success:
                        return {"success": False, "message": "单轮批量操作被取消"}
                else:
                    await asyncio.sleep(1)
                
                operation_count += 1
            
            logger.info(f"[任务{task_id}] ✅ 单轮批量操作完成，共执行 {operation_count} 个操作")
            
            return {
                "success": True,
                "message": "单轮批量操作完成",
                "operations_count": operation_count
            }
            
        except Exception as e:
            logger.error(f"❌ 单轮批量操作失败: {e}")
            return {
                "success": False,
                "message": f"单轮批量操作失败: {str(e)}"
            }

# 为了向后兼容，提供独立的函数接口
async def optimized_delayed_login_only(slot_num: int, account: dict, container_name: str, 
                                     target_ip: str, task_id: int, delay: int = 0):
    """优化的延迟登录（独立函数版本）"""
    async with OperationTools() as tools:
        return await tools.delayed_login_operation(slot_num, account, container_name, target_ip, task_id, delay)

async def optimized_delayed_backup_only(slot_num: int, account: dict, container_name: str,
                                      target_ip: str, task_id: int, delay: int = 0):
    """优化的延迟备份（独立函数版本）"""
    async with OperationTools() as tools:
        return await tools.delayed_backup_operation(slot_num, account, container_name, target_ip, task_id, delay)

async def optimized_cleanup_container(container_name: str, target_ip: str, task_id: int):
    """优化的容器清理（独立函数版本）"""
    async with OperationTools() as tools:
        return await tools.cleanup_container_operation(container_name, target_ip, task_id)

async def perform_real_time_suspension_check(task_id: int, device_ip: str, instance_slot: int, 
                                           account: dict, is_suspended: bool, container_name: str = None):
    """实时封号检测（独立函数版本）"""
    async with OperationTools() as tools:
        return await tools.perform_real_time_suspension_check(task_id, device_ip, instance_slot, account, is_suspended, container_name)

async def execute_single_batch_operation(task_params: dict):
    """执行单轮批量操作（独立函数版本）"""
    async with OperationTools() as tools:
        return await tools.execute_single_batch_operation(task_params)

async def get_dynamic_ports(target_ip: str, container_name: str, slot_num: int, task_id: int) -> tuple:
    """获取动态端口信息（独立函数版本）"""
    try:
        from core.device_manager import DeviceManager
        async with DeviceManager() as device_manager:
            return await device_manager.get_dynamic_ports(target_ip, container_name, slot_num, task_id)
    except Exception as e:
        logger.error(f"❌ 获取端口信息异常: {e}")
        # 返回默认端口
        return (5000 + slot_num, 7100 + slot_num)

async def cleanup_container(container_name: str, device_ip: str, task_id: int):
    """清理容器（独立函数版本）"""
    async with OperationTools() as tools:
        result = await tools.cleanup_container_operation(container_name, device_ip, task_id)
        return result["success"]

async def smart_rpc_restart_if_needed(target_ip: str, slot_num: int, container_name: str, task_id: int, repair_level: str = "full") -> bool:
    """智能RPC重启（独立函数版本）"""
    try:
        from core.device_manager import DeviceManager
        async with DeviceManager() as device_manager:
            return await device_manager.smart_rpc_restart_if_needed(target_ip, slot_num, container_name, task_id, repair_level)
    except Exception as e:
        logger.error(f"❌ 智能RPC重启异常: {e}")
        return False 