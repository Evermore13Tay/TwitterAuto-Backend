"""
养号互动处理模块
负责处理推特互动相关功能
"""

import os
import sys
import time
import random
import asyncio
import logging
import requests
import urllib.parse
import concurrent.futures
from typing import List, Dict, Any, Callable

try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class NurtureInteractionHandler:
    """养号互动处理器"""
    
    def __init__(self, device_manager, database_handler, config_manager, task_manager, status_callback: Callable[[str], None] = None):
        self.device_manager = device_manager
        self.database_handler = database_handler
        self.config_manager = config_manager
        self.task_manager = task_manager
        self.status_callback = status_callback or (lambda x: logger.info(x))
    
    async def batch_setup_and_interaction(self, reboot_results: List[Dict[str, Any]], device_ip: str) -> List[Dict[str, Any]]:
        """批量设置和互动 - 简化版本，避免过于复杂的并发逻辑"""
        try:
            logger.info(f"[任务{self.task_manager.task_id}] 🚀 开始批量设置和互动 (设备: {device_ip})")
            
            # 验证输入数据完整性
            valid_results = []
            for result in reboot_results:
                if 'position' not in result:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 重启结果缺少 position 字段: {result}")
                    continue
                if not result.get('reboot_success', False):
                    logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 跳过重启失败的结果: position={result.get('position')}")
                    continue
                valid_results.append(result)
            
            if not valid_results:
                self.status_callback("❌ 没有可执行的互动任务")
                return []
            
            # 简化版本：顺序处理每个账号
            all_final_results = []
            success_count = 0
            
            for i, result in enumerate(valid_results):
                if self.task_manager.check_if_cancelled():
                    self.status_callback("任务已取消，停止执行")
                    break
                
                account = result['account']
                position = result['position']
                username = account['username']
                container_name = result['container_name']
                
                self.status_callback(f"🎮 处理账号 {i+1}/{len(valid_results)}: {username}")
                
                # 设置语言和代理
                setup_success = await self.setup_language_and_proxy(device_ip, container_name, username)
                
                # 账号验证
                verify_success = await self.verify_account_status(device_ip, position, account)
                
                # 执行互动（简化版本）
                interaction_success = False
                if setup_success and verify_success:
                    interaction_success = await self.perform_simple_interaction(device_ip, position)
                
                # 记录结果
                final_result = {
                    **result,
                    'setup_success': setup_success,
                    'interaction_success': interaction_success,
                    'success': setup_success and verify_success and interaction_success,
                    'message': '简化版本互动完成' if interaction_success else '简化版本互动失败'
                }
                
                all_final_results.append(final_result)
                
                if final_result['success']:
                    success_count += 1
                    logger.info(f"[任务{self.task_manager.task_id}] ✅ 账号处理成功: {username}")
                else:
                    logger.warning(f"[任务{self.task_manager.task_id}] ❌ 账号处理失败: {username}")
                
                # 账号间隔
                if i < len(valid_results) - 1:
                    await asyncio.sleep(5)
            
            self.status_callback(f"🎮 批量互动完成: {success_count}/{len(valid_results)} 成功")
            return all_final_results
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 批量设置和互动异常: {e}", exc_info=True)
            return []
    
    async def setup_language_and_proxy(self, device_ip: str, container_name: str, username: str) -> bool:
        """设置语言和代理"""
        try:
            logger.info(f"[任务{self.task_manager.task_id}] 🌐 开始设置代理和语言: {container_name}")
            
            # 获取代理配置（从数据库）
            proxy_config = self.database_handler.get_proxy_config_for_account(username)
            
            # 设置代理
            proxy_success = await self.device_manager.set_device_proxy(
                device_ip, container_name, proxy_config, self.task_manager.task_id
            )
            
            # 间隔等待
            await asyncio.sleep(5)
            
            # 设置语言
            language_success = await self.device_manager.set_device_language(
                device_ip, container_name, self.config_manager.language_code, self.task_manager.task_id
            )
            
            setup_success = proxy_success and language_success
            
            if setup_success:
                logger.info(f"[任务{self.task_manager.task_id}] ✅ {container_name} 代理语言设置成功")
            else:
                logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ {container_name} 代理语言设置部分失败")
            
            return setup_success
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 设置代理语言异常: {e}")
            return False
    
    async def verify_account_status(self, device_ip: str, position: int, account: Dict[str, Any]) -> bool:
        """验证账号状态"""
        try:
            username = account.get('username', '')
            
            if username:
                logger.info(f"[任务{self.task_manager.task_id}] ✅ 账号验证通过: {username}")
                return True
            else:
                logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 账号缺少用户名: {account}")
                return False
                
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 账号验证异常: {e}")
            return False
    
    async def perform_simple_interaction(self, device_ip: str, position: int) -> bool:
        """执行简化的互动"""
        try:
            duration = self.config_manager.interaction_duration
            self.status_callback(f"🎮 开始 {duration} 秒的简化互动...")
            
            # 简化版本：只是等待指定时间
            steps = duration // 30  # 每30秒一个步骤
            
            for step in range(steps):
                if self.task_manager.check_if_cancelled():
                    self.status_callback("🚨 互动已取消")
                    return False
                
                # 模拟不同的互动活动
                if step % 3 == 0 and self.config_manager.enable_liking:
                    self.status_callback(f"👍 模拟点赞操作...")
                elif step % 3 == 1 and self.config_manager.enable_following:
                    self.status_callback(f"➕ 模拟关注操作...")
                else:
                    self.status_callback(f"📱 模拟浏览操作...")
                
                from utils.task_cancellation import sleep_with_cancel_check
                success = await sleep_with_cancel_check(self.task_manager.task_id, 30, 5.0, f"简化互动步骤{step+1}")
                if not success:
                    self.status_callback("🚨 简化互动被取消")
                    return False
            
            self.status_callback(f"🎉 简化互动完成!")
            return True
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 简化互动异常: {e}")
            return False 