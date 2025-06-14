"""
养号导入处理模块
负责处理备份导入相关功能
"""

import logging
from typing import List, Dict, Any, Callable

try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class NurtureImportHandler:
    """养号导入处理器"""
    
    def __init__(self, device_manager, account_handler, config_manager, task_manager, status_callback: Callable[[str], None] = None):
        self.device_manager = device_manager
        self.account_handler = account_handler
        self.config_manager = config_manager
        self.task_manager = task_manager
        self.status_callback = status_callback or (lambda x: logger.info(x))
    
    async def batch_import_nurture(self, accounts_in_batch: List[Dict[str, Any]], 
                                   device_ip: str, backup_path: str) -> List[Dict[str, Any]]:
        """批量导入纯净备份 - 自动养号版本，支持文件夹模式"""
        results = []
        
        for account_info in accounts_in_batch:
            # 🔧 **取消检查点：每次导入前**
            if self.task_manager.check_if_cancelled():
                self.status_callback("任务已被取消")
                return results
            
            account = account_info['account']
            position = account_info['position']
            container_name = account_info['container_name']
            username = account['username']
            
            # 🔧 **自动选择对应的备份文件**
            actual_backup_file = self.account_handler.find_backup_file_for_account(backup_path, username)
            
            if not actual_backup_file:
                self.status_callback(f"❌ 未找到账号 {username} 的备份文件")
                results.append({
                    'account': account,
                    'position': position,
                    'container_name': container_name,
                    'username': username,
                    'import_success': False
                })
                continue
            
            import os
            self.status_callback(f"📦 导入实例位 {position}: {username} <- {os.path.basename(actual_backup_file)}")
            
            import_success = await self.import_backup_with_retry(device_ip, container_name, position, actual_backup_file)
            
            results.append({
                'account': account,
                'position': position,
                'container_name': container_name,
                'username': username,
                'import_success': import_success
            })
            
            # 导入间隔等待（带取消检查）
            if account_info != accounts_in_batch[-1]:  # 不是最后一个
                from utils.task_cancellation import sleep_with_cancel_check
                success = await sleep_with_cancel_check(self.task_manager.task_id, self.config_manager.import_wait_time, 1.0, "导入间隔等待")
                if not success:
                    self.status_callback("任务在导入间隔等待期间被取消")
                    return results
        
        return results
    
    async def import_backup_with_retry(self, device_ip: str, container_name: str, position: int, backup_file: str) -> bool:
        """带重试的备份导入"""
        for attempt in range(self.config_manager.max_retries):
            try:
                # 首先清理冲突的容器
                await self.device_manager.cleanup_conflict_devices(device_ip, [position], [container_name], self.task_manager.task_id)
                
                # 执行导入
                import_url = f"http://127.0.0.1:5000/import/{device_ip}/{container_name}/{position}"
                import_params = {'local': backup_file}
                
                async with self.device_manager:
                    async with self.device_manager.session.get(import_url, params=import_params) as response:
                        if response.status == 200:
                            response_data = await response.json()
                            if response_data.get('code') == 200:
                                logger.info(f"✅ 容器 {container_name} 导入成功")
                                return True
                            else:
                                logger.warning(f"❌ 容器 {container_name} 导入失败: {response_data.get('message', '未知错误')}")
                
                if attempt < self.config_manager.max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.info(f"⏱️ 导入重试等待 {wait_time} 秒 (尝试 {attempt + 1}/{self.config_manager.max_retries})")
                    # 🔧 修复：使用带取消检查的睡眠
                    from utils.task_cancellation import sleep_with_cancel_check
                    success = await sleep_with_cancel_check(self.task_manager.task_id, wait_time, 1.0, f"导入重试等待{attempt+1}")
                    if not success:
                        logger.info(f"🚨 导入重试等待被取消")
                        return False
                    
            except Exception as e:
                logger.error(f"❌ 导入尝试 {attempt + 1} 异常: {e}")
                if attempt == self.config_manager.max_retries - 1:
                    return False
                # 🔧 修复：使用带取消检查的睡眠
                from utils.task_cancellation import sleep_with_cancel_check
                success = await sleep_with_cancel_check(self.task_manager.task_id, 2, 1.0, f"导入异常重试等待{attempt+1}")
                if not success:
                    logger.info(f"🚨 导入异常重试等待被取消")
                    return False
        
        return False 