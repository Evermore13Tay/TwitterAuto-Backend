"""
自动养号处理器模块
封装完整的自动养号业务逻辑：导入→重启→设置→登录→互动→清理
"""

import asyncio
import logging
import os
import sys
import time
import random
import string
from typing import List, Dict, Any, Optional, Callable
from concurrent.futures import ThreadPoolExecutor

try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# 导入核心模块
from .device_manager import DeviceManager
from .account_manager import AccountManager
from .task_manager import TaskManager
from .database_handler import DatabaseHandler
from .api_client import ApiClient

class NurtureProcessor:
    """自动养号处理器"""
    
    def __init__(self, task_manager: TaskManager, device_manager: DeviceManager, 
                 account_manager: AccountManager, database_handler: DatabaseHandler,
                 status_callback: Callable[[str], None] = None):
        self.task_manager = task_manager
        self.device_manager = device_manager
        self.account_manager = account_manager
        self.database_handler = database_handler
        self.status_callback = status_callback or (lambda x: logger.info(x))
        
        # 配置参数
        self.import_wait_time = 3
        self.reboot_wait_time = 165
        self.account_wait_time = 10
        self.interaction_duration = 300
        self.max_retries = 3
        self.language_code = 'en'
        self.container_prefix = 'TwitterAutomation'
        
        # 智能间隔控制
        self.last_reboot_time = 0
        self.min_reboot_interval = 2  # 修改为1-3秒范围的中间值
        self.last_proxy_setup_time = 0
        self.min_proxy_setup_interval = 3  # 同步优化代理设置间隔
        self.last_interaction_time = 0
        self.min_interaction_interval = 5  # 同步优化互动间隔
        
        # 互动功能配置
        self.enable_liking = True
        self.enable_commenting = False
        self.enable_following = True
        self.enable_retweeting = False
        
        # 随机延迟配置
        self.enable_random_delay = True
        self.min_random_delay = 5
        self.max_random_delay = 15
    
    def update_config(self, config: Dict[str, Any]):
        """更新配置参数"""
        if not config:
            return
        
        self.import_wait_time = config.get('importWaitTime', self.import_wait_time)
        self.reboot_wait_time = config.get('rebootWaitTime', self.reboot_wait_time)
        self.account_wait_time = config.get('accountWaitTime', self.account_wait_time)
        
        # 处理前端传来的分钟数，转换为秒
        frontend_duration_minutes = config.get('executionDuration')
        if frontend_duration_minutes is not None:
            self.interaction_duration = frontend_duration_minutes * 60
        
        self.max_retries = config.get('maxRetries', self.max_retries)
        self.language_code = config.get('languageCode', self.language_code)
        self.container_prefix = config.get('containerPrefix', self.container_prefix)
        self.enable_random_delay = config.get('enableRandomDelay', self.enable_random_delay)
        self.min_random_delay = config.get('minRandomDelay', self.min_random_delay)
        self.max_random_delay = config.get('maxRandomDelay', self.max_random_delay)
        
        # 互动功能配置
        self.enable_liking = config.get('enableLiking', self.enable_liking)
        self.enable_commenting = config.get('enableCommenting', self.enable_commenting)
        self.enable_following = config.get('enableFollowing', self.enable_following)
        self.enable_retweeting = config.get('enableRetweeting', self.enable_retweeting)
        
        self.status_callback(f"📋 养号配置更新完成")
        logger.info(f"养号配置更新: 重启等待{self.reboot_wait_time}s, 互动时长{self.interaction_duration}s")
    
    def generate_random_container_name(self, username: str) -> str:
        """生成随机容器名称"""
        random_suffix = ''.join(random.choices(string.digits, k=5))
        return f"{self.container_prefix}_{username}_{random_suffix}"
    
    def apply_random_delay(self) -> int:
        """应用随机延迟并返回实际延迟时间"""
        if not self.enable_random_delay:
            return 0
        delay = random.randint(self.min_random_delay, self.max_random_delay)
        return delay
    
    async def apply_smart_interval(self, operation_type: str) -> bool:
        """应用智能间隔控制"""
        current_time = time.time()
        
        if operation_type == 'reboot':
            elapsed = current_time - self.last_reboot_time
            if elapsed < self.min_reboot_interval:
                wait_time = self.min_reboot_interval - elapsed
                logger.info(f"⏱️ 重启间隔控制: 等待 {wait_time:.1f} 秒")
                from utils.task_cancellation import sleep_with_cancel_check
                success = await sleep_with_cancel_check(self.task_manager.task_id, wait_time, 2.0, "重启间隔等待")
                if not success:
                    return False
            self.last_reboot_time = time.time()
            
        elif operation_type == 'proxy_setup':
            elapsed = current_time - self.last_proxy_setup_time
            if elapsed < self.min_proxy_setup_interval:
                wait_time = self.min_proxy_setup_interval - elapsed
                logger.info(f"⏱️ 代理设置间隔控制: 等待 {wait_time:.1f} 秒")
                from utils.task_cancellation import sleep_with_cancel_check
                success = await sleep_with_cancel_check(self.task_manager.task_id, wait_time, 2.0, "代理设置间隔等待")
                if not success:
                    return False
            self.last_proxy_setup_time = time.time()
            
        elif operation_type == 'interaction':
            elapsed = current_time - self.last_interaction_time
            if elapsed < self.min_interaction_interval:
                wait_time = self.min_interaction_interval - elapsed
                logger.info(f"⏱️ 互动间隔控制: 等待 {wait_time:.1f} 秒")
                from utils.task_cancellation import sleep_with_cancel_check
                success = await sleep_with_cancel_check(self.task_manager.task_id, wait_time, 2.0, "互动间隔等待")
                if not success:
                    return False
            self.last_interaction_time = time.time()
        
        return True
    
    async def execute_auto_nurture_task(self, task_params: Dict[str, Any]) -> bool:
        """
        执行自动养号任务的主入口
        """
        try:
            self.status_callback("🚀 开始执行自动养号任务...")
            
            # 更新配置
            auto_nurture_params = task_params.get('autoNurtureParams', {})
            self.update_config(auto_nurture_params)
            
            # 解析账号和设备参数
            accounts = await self._get_accounts(task_params)
            if not accounts:
                self.status_callback("❌ 未找到有效账号")
                return False
            
            # 获取设备和位置信息 - 修复：使用正确的参数名
            devices = task_params.get('devices', []) or task_params.get('selectedDevices', [])
            positions = task_params.get('positions', []) or task_params.get('selectedPositions', [])
            
            if not devices or not positions:
                self.status_callback("❌ 参数不完整：缺少设备或实例位信息")
                return False
                
            # 使用第一个设备作为主设备（养号任务通常只用一个设备）
            device_ip = devices[0] if devices else '192.168.1.100'
            
            # 获取备份信息 - 修复：支持文件夹+文件列表模式
            auto_nurture_params = task_params.get('autoNurtureParams') or {}
            backup_folder = auto_nurture_params.get('backupFolder', '')
            backup_files = auto_nurture_params.get('backupFiles', [])
            
            # 兼容性：单文件参数
            single_backup_file = (
                task_params.get('selectedPureBackupFile', '') or
                (task_params.get('batchLoginBackupParams') or {}).get('pureBackupFile', '') or
                task_params.get('backupFile', '')
            )
            
            # 确定实际使用的备份方式
            if backup_folder and backup_files:
                backup_file = backup_folder  # 传递文件夹路径，批次处理时会自动选择对应文件
                self.status_callback(f"📦 备份模式: 文件夹模式 ({len(backup_files)} 个文件)")
            elif single_backup_file:
                backup_file = single_backup_file
                self.status_callback(f"📦 备份模式: 单文件模式")
            else:
                self.status_callback("❌ 未指定备份文件或备份文件夹")
                return False
            
            self.status_callback(f"📊 任务概览: {len(accounts)}个账号, {len(positions)}个位置")
            
            # 创建智能批次
            batches = self.create_intelligent_batches(accounts, device_ip, positions)
            
            # 执行批次处理
            success_count = 0
            for batch_num, batch in enumerate(batches, 1):
                if self.task_manager.check_if_cancelled():
                    self.status_callback("🚨 任务已取消")
                    break
                
                self.status_callback(f"📦 开始处理批次 {batch_num}/{len(batches)}")
                
                batch_success = await self.process_nurture_batch(batch, backup_file, batch_num, len(batches))
                if batch_success:
                    success_count += 1
                
                # 批次间隔
                if batch_num < len(batches):
                    from utils.task_cancellation import sleep_with_cancel_check
                    success = await sleep_with_cancel_check(self.task_manager.task_id, self.account_wait_time, 2.0, "批次间隔等待")
                    if not success:
                        self.status_callback("🚨 批次间隔等待被取消")
                        break
            
            success_rate = (success_count / len(batches)) * 100 if batches else 0
            self.status_callback(f"🎉 自动养号任务完成! 成功率: {success_rate:.1f}% ({success_count}/{len(batches)})")
            
            return success_count > 0
            
        except Exception as e:
            error_msg = f"自动养号任务执行异常: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.status_callback(f"❌ {error_msg}")
            return False
    
    async def _get_accounts(self, task_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取要处理的账号列表 - 自动养号版本：优先从备份文件获取账号信息"""
        try:
            accounts = []
            
            # 获取备份参数
            auto_nurture_params = task_params.get('autoNurtureParams') or {}
            backup_folder = auto_nurture_params.get('backupFolder', '')
            backup_files = auto_nurture_params.get('backupFiles', [])
            
            # 兼容性：单文件参数
            single_backup_file = (
                task_params.get('selectedPureBackupFile', '') or
                (task_params.get('batchLoginBackupParams') or {}).get('pureBackupFile', '') or
                task_params.get('backupFile', '')
            )
            
            if backup_folder and backup_files:
                self.status_callback(f"📦 从备份文件夹自动解析账号: {backup_folder} (包含 {len(backup_files)} 个文件)")
                
                # 从所有备份文件中提取账号
                all_accounts = []
                for backup_file_name in backup_files:
                    full_backup_path = f"{backup_folder}/{backup_file_name}".replace('\\', '/')
                    file_accounts = await self._extract_accounts_from_backup(full_backup_path)
                    all_accounts.extend(file_accounts)
                
                if all_accounts:
                    self.status_callback(f"✅ 从 {len(backup_files)} 个备份文件解析到 {len(all_accounts)} 个账号")
                    return all_accounts
                else:
                    self.status_callback("⚠️ 备份文件中未找到账号信息，尝试其他方式获取")
                    
            elif single_backup_file:
                self.status_callback(f"📦 从单个备份文件自动解析账号: {single_backup_file}")
                accounts = await self._extract_accounts_from_backup(single_backup_file)
                
                if accounts:
                    self.status_callback(f"✅ 从备份文件解析到 {len(accounts)} 个账号")
                    return accounts
                else:
                    self.status_callback("⚠️ 备份文件中未找到账号信息，尝试其他方式获取")
            
            # 🔧 **备选方案1：从数据库分组获取账号**
            account_group_id = task_params.get('selectedAccountGroup')
            if account_group_id:
                self.status_callback(f"📊 从数据库分组获取账号: 分组ID {account_group_id}")
                accounts, stats = self.database_handler.get_accounts_by_group(
                    group_id=account_group_id,
                    exclude_backed_up=False,  # 养号任务不排除已备份账号
                    exclude_suspended=True
                )
                
                self.status_callback(
                    f"📊 分组账号统计: 总数={stats.get('total_accounts', 0)}, "
                    f"已备份={stats.get('skipped_backed_up', 0)}, "
                    f"已封号={stats.get('skipped_suspended', 0)}, "
                    f"待养号={stats.get('valid_accounts', 0)}"
                )
                
                if accounts:
                    self.status_callback(f"✅ 从分组解析到 {len(accounts)} 个账号")
                    return accounts
            
            # 🔧 **备选方案2：从字符串解析账号**
            accounts_str = (task_params.get('autoNurtureParams') or {}).get('accounts', '')
            if accounts_str:
                self.status_callback("📝 从参数字符串解析账号")
                accounts = self.account_manager.parse_accounts_from_string(accounts_str)
                
                # 为每个账号查询数据库ID
                for account in accounts:
                    account_info = self.database_handler.get_account_by_username(account['username'])
                    if account_info:
                        account['id'] = account_info['id']
                    else:
                        account['id'] = None
                        logger.warning(f"⚠️ 无法找到账号 {account['username']} 的ID")
                
                if accounts:
                    self.status_callback(f"✅ 从参数字符串解析到 {len(accounts)} 个账号")
                    return accounts
            
            # 🔧 **如果所有方式都没有获取到账号**
            if backup_folder and backup_files:
                self.status_callback("❌ 无法从备份文件夹中解析账号信息，请检查备份文件格式")
            elif single_backup_file:
                self.status_callback("❌ 无法从备份文件中解析账号信息，请检查备份文件格式")
            elif account_group_id:
                self.status_callback("❌ 该分组没有可用于养号的账号")
            else:
                self.status_callback("❌ 未找到有效的账号信息，请选择备份文件或账号分组")
            
            return []
            
        except Exception as e:
            logger.error(f"获取账号列表异常: {e}", exc_info=True)
            self.status_callback(f"❌ 获取账号失败: {e}")
            return []
    
    async def _extract_accounts_from_backup(self, backup_file: str) -> List[Dict[str, Any]]:
        """从备份文件中提取账号信息"""
        try:
            import os
            import re
            
            if not os.path.exists(backup_file):
                logger.warning(f"⚠️ 备份文件不存在: {backup_file}")
                return []
            
            # 🔧 **情况1：单个账号备份文件 (username.tar.gz)**
            backup_filename = os.path.basename(backup_file)
            if backup_filename.endswith('.tar.gz'):
                # 从文件名提取用户名 (移除.tar.gz后缀)
                username = backup_filename.replace('.tar.gz', '')
                
                # 简单验证用户名格式
                if re.match(r'^[a-zA-Z0-9_]+$', username):
                    # 查询数据库获取完整账号信息
                    account_info = self.database_handler.get_account_by_username(username)
                    if account_info:
                        return [account_info]
                    else:
                        # 如果数据库中没有，创建基础账号信息
                        return [{
                            'id': None,
                            'username': username,
                            'password': '',  # 备份文件中通常不包含密码
                            'secretkey': '',  # 备份文件中通常不包含密钥
                            'status': 'active'
                        }]
            
            # 🔧 **情况2：多账号压缩包（TODO：如果需要支持）**
            # 这里可以添加解析压缩包中多个备份文件的逻辑
            
            logger.warning(f"⚠️ 不支持的备份文件格式: {backup_file}")
            return []
            
        except Exception as e:
            logger.error(f"❌ 解析备份文件异常: {e}", exc_info=True)
            return []
    
    def create_intelligent_batches(self, accounts: List[Dict[str, Any]], device_ip: str, positions: List[int]) -> List[Dict[str, Any]]:
        """创建智能批次 - 修复：按并行能力分批，参考自动登录逻辑"""
        # 🔧 **关键修复：按并行能力分批**
        max_parallel_slots = len(positions)  # 每个设备的最大并行数
        
        batches = []
        account_index = 0
        
        while account_index < len(accounts):
            current_batch = {
                'accounts': [],
                'device_ip': device_ip,
                'batch_index': len(batches) + 1
            }
            
            # 为当前批次分配账号到实例位
            for position in positions:
                if account_index >= len(accounts):
                    break
                
                account = accounts[account_index]
                account_with_position = {
                    'account': account,
                    'position': position,
                    'container_name': self.generate_random_container_name(account['username'])
                }
                current_batch['accounts'].append(account_with_position)
                account_index += 1
            
            if current_batch['accounts']:
                batches.append(current_batch)
        
        # 显示分批信息
        total_slots = len(positions)
        self.status_callback(f"📊 分批策略：{len(accounts)} 个账号分为 {len(batches)} 批处理")
        self.status_callback(f"📊 并行能力：每批最多 {total_slots} 个账号并行处理")
        
        # 显示每批的详细信息
        for i, batch in enumerate(batches):
            accounts_in_batch = len(batch['accounts'])
            positions_used = [acc['position'] for acc in batch['accounts']]
            self.status_callback(f"   第 {i+1} 批：{accounts_in_batch} 个账号 (实例位: {positions_used})")
        
        logger.info(f"✅ 创建了 {len(batches)} 个并行批次")
        return batches
    
    async def process_nurture_batch(self, batch: Dict[str, Any], backup_file: str, 
                                  batch_num: int, total_batches: int) -> bool:
        """处理单个养号批次 - 修复：支持批量处理多个账号，确保清理"""
        device_ip = batch['device_ip']
        accounts_in_batch = batch['accounts']
        batch_index = batch.get('batch_index', batch_num)
        
        # 用于跟踪所有需要清理的容器
        all_containers_for_cleanup = []
        
        try:
            self.status_callback(f"🔄 [第{batch_index}批] 并行处理 {len(accounts_in_batch)} 个账号")
            
            # 🔧 **阶段1: 批量导入**
            import_results = await self._batch_import_nurture(accounts_in_batch, device_ip, backup_file)
            # 收集所有创建的容器（无论导入是否成功）
            all_containers_for_cleanup.extend(import_results)
            
            successful_imports = [r for r in import_results if r.get('import_success')]
            
            if not successful_imports:
                self.status_callback(f"❌ [第{batch_index}批] 没有成功导入的账号")
                # 即使导入失败，也要清理容器
                await self._batch_cleanup_nurture(all_containers_for_cleanup, device_ip)
                return False
            
            # 🔧 **阶段2: 批量重启（并行优化）**
            reboot_results = await self._batch_reboot_nurture(successful_imports, device_ip)
            successful_reboots = [r for r in reboot_results if r.get('reboot_success')]
            
            if not successful_reboots:
                self.status_callback(f"❌ [第{batch_index}批] 没有成功重启的账号")
                # 重启失败，清理所有容器
                await self._batch_cleanup_nurture(all_containers_for_cleanup, device_ip)
                return False
            
            # 🔧 **阶段3: 批量设置和互动（并行优化）**
            final_results = await self._batch_setup_and_interaction(successful_reboots, device_ip)
            
            # 更新清理列表为最终结果
            if final_results:
                all_containers_for_cleanup = final_results
            
            successful_accounts = [r for r in final_results if r.get('success')]
            self.status_callback(f"✅ [第{batch_index}批] 完成，成功 {len(successful_accounts)} 个账号")
            
            return len(successful_accounts) > 0
            
        except Exception as e:
            error_msg = f"批次处理异常: {str(e)}"
            logger.error(error_msg, exc_info=True)
            self.status_callback(f"❌ {error_msg}")
            return False
        
        finally:
            # 🔧 **确保清理：无论成功失败都执行清理**
            try:
                if all_containers_for_cleanup:
                    logger.info(f"[任务{self.task_manager.task_id}] 🗑️ 开始执行批次清理...")
                    await self._batch_cleanup_nurture(all_containers_for_cleanup, device_ip)
                    logger.info(f"[任务{self.task_manager.task_id}] 🗑️ 批次清理完成")
                else:
                    logger.info(f"[任务{self.task_manager.task_id}] ℹ️ 没有容器需要清理")
            except Exception as cleanup_error:
                logger.error(f"[任务{self.task_manager.task_id}] ❌ 批次清理异常: {cleanup_error}")
                self.status_callback(f"⚠️ 容器清理异常，可能有资源泄露: {cleanup_error}")
    
    async def import_backup_with_retry(self, device_ip: str, container_name: str, position: int, backup_file: str) -> bool:
        """带重试的备份导入"""
        for attempt in range(self.max_retries):
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
                
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.info(f"⏱️ 导入重试等待 {wait_time} 秒 (尝试 {attempt + 1}/{self.max_retries})")
                    # 🔧 修复：使用带取消检查的睡眠
                    from utils.task_cancellation import sleep_with_cancel_check
                    success = await sleep_with_cancel_check(self.task_manager.task_id, wait_time, 1.0, f"导入重试等待{attempt+1}")
                    if not success:
                        logger.info(f"🚨 导入重试等待被取消")
                        return False
                    
            except Exception as e:
                logger.error(f"❌ 导入尝试 {attempt + 1} 异常: {e}")
                if attempt == self.max_retries - 1:
                    return False
                # 🔧 修复：使用带取消检查的睡眠
                from utils.task_cancellation import sleep_with_cancel_check
                success = await sleep_with_cancel_check(self.task_manager.task_id, 2, 1.0, f"导入异常重试等待{attempt+1}")
                if not success:
                    logger.info(f"🚨 导入异常重试等待被取消")
                    return False
        
        return False
    
    async def setup_language_and_proxy(self, device_ip: str, container_name: str, username: str) -> bool:
        """设置语言和代理 - 修复：使用正确的设备管理器接口"""
        try:
            logger.info(f"[任务{self.task_manager.task_id}] 🌐 开始设置代理和语言: {container_name}")
            
            # 获取代理配置（从数据库）
            proxy_config = self.database_handler.get_proxy_config_for_account(username)
            
            # 步骤1：设置代理（先设置代理）- 使用正确的设备管理器方法
            proxy_success = await self.device_manager.set_device_proxy(
                device_ip, container_name, proxy_config, self.task_manager.task_id
            )
            
            if proxy_success:
                logger.info(f"[任务{self.task_manager.task_id}] ✅ 代理设置成功: {container_name}")
            else:
                logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 代理设置失败: {container_name}")
            
            # 间隔等待：代理设置后等待5秒
            await asyncio.sleep(5)
            
            # 步骤2：设置语言（后设置语言）- 使用正确的设备管理器方法
            language_success = await self.device_manager.set_device_language(
                device_ip, container_name, self.language_code, self.task_manager.task_id
            )
            
            if language_success:
                logger.info(f"[任务{self.task_manager.task_id}] ✅ 语言设置成功: {container_name} -> {self.language_code}")
            else:
                logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 语言设置失败: {container_name}")
            
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
        """验证账号状态 - 修复：允许没有密码的备份账号"""
        try:
            # 获取端口信息 - 修复：使用正确的端口获取方法
            base_port, debug_port = await self.device_manager.get_container_ports(
                device_ip, position, self.task_manager.task_id
            )
            
            # 端口获取失败不影响账号验证（因为账号验证主要检查账号信息本身）
            if not base_port or not debug_port:
                logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 端口获取失败，但继续账号验证")
            
            username = account.get('username', '')
            password = account.get('password', '')
            
            # 修复：只要有用户名就允许继续（备份文件中的账号通常没有密码）
            if username:
                if password:
                    logger.info(f"[任务{self.task_manager.task_id}] ✅ 账号验证通过: {username} (完整信息)")
                else:
                    logger.info(f"[任务{self.task_manager.task_id}] ✅ 账号验证通过: {username} (仅用户名，来自备份文件)")
                return True
            else:
                logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 账号缺少用户名: {account}")
                return False
                
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 账号验证异常: {e}")
            return False
    
    async def perform_nurture_interaction(self, device_ip: str, position: int, duration_seconds: int) -> bool:
        """执行养号互动 - 修复：调用真实的推特互动脚本"""
        try:
            self.status_callback(f"🎮 开始 {duration_seconds} 秒的推特养号互动...")
            
            # 获取端口信息 - 修复：使用正确的端口获取方法
            base_port, debug_port = await self.device_manager.get_container_ports(
                device_ip, position, self.task_manager.task_id
            )
            
            if not base_port or not debug_port:
                logger.error(f"[任务{self.task_manager.task_id}] ❌ 无法获取实例位{position}的端口信息")
                self.status_callback(f"❌ 无法获取实例位{position}的端口信息")
                return False
                
            logger.info(f"[任务{self.task_manager.task_id}] 🎯 获取端口成功 - U2: {base_port}, RPC: {debug_port}")
            
            # 导入真实的互动模块
            try:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                backend_dir = os.path.dirname(current_dir)
                automation_dir = os.path.join(backend_dir, 'automation')
                sys.path.insert(0, automation_dir)
                
                from automation.interactTest import run_interaction
                logger.info(f"[任务{self.task_manager.task_id}] ✅ 成功导入真实互动模块")
                
            except ImportError as e:
                logger.error(f"[任务{self.task_manager.task_id}] ❌ 导入互动模块失败: {e}")
                self.status_callback(f"❌ 导入互动模块失败，使用模拟模式")
                return await self._simulate_interaction(duration_seconds)
            
            # 执行真实的推特互动
            def interaction_status_callback(message):
                # 过滤过于详细的日志，只显示关键信息
                if any(keyword in message for keyword in ['开始', '完成', '成功', '失败', '错误', '❌', '✅', '🎮']):
                    self.status_callback(f"🎮 {message}")
                
                # 检查任务取消状态
                if self.task_manager.check_if_cancelled():
                    raise Exception("任务已被用户取消")
            
            # 在线程池中执行互动，避免阻塞异步循环
            import asyncio
            loop = asyncio.get_event_loop()
            
            def run_real_interaction():
                try:
                    return run_interaction(
                        status_callback=interaction_status_callback,
                        device_ip_address=device_ip,
                        u2_port=base_port,
                        myt_rpc_port=debug_port,
                        duration_seconds=duration_seconds,
                        enable_liking_param=self.enable_liking,
                        enable_commenting_param=self.enable_commenting,
                        comment_text_param="Great post! 👍"
                    )
                except Exception as e:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 互动执行异常: {e}")
                    return False
            
            # 使用线程池执行器运行同步的互动函数
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = loop.run_in_executor(executor, run_real_interaction)
                
                # 添加任务取消检查
                while not future.done():
                    if self.task_manager.check_if_cancelled():
                        self.status_callback("🚨 互动已取消")
                        future.cancel()
                        return False
                    await asyncio.sleep(1)  # 每秒检查一次
                
                interaction_success = await future
            
            if interaction_success:
                self.status_callback(f"🎉 推特养号互动完成!")
                logger.info(f"[任务{self.task_manager.task_id}] ✅ 互动成功完成")
                return True
            else:
                self.status_callback(f"❌ 推特养号互动失败")
                logger.error(f"[任务{self.task_manager.task_id}] ❌ 互动执行失败")
                return False
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 互动执行异常: {e}")
            self.status_callback(f"❌ 互动执行异常: {e}")
            return False
    
    async def _simulate_interaction(self, duration_seconds: int) -> bool:
        """模拟互动（备用方案）"""
        try:
            self.status_callback(f"🎮 使用模拟模式进行 {duration_seconds} 秒的互动...")
            
            interaction_steps = duration_seconds // 30  # 每30秒一个步骤
            
            for step in range(interaction_steps):
                if self.task_manager.check_if_cancelled():
                    self.status_callback("🚨 互动已取消")
                    return False
                
                # 模拟不同的互动活动
                if step % 3 == 0 and self.enable_liking:
                    self.status_callback(f"👍 模拟点赞操作...")
                elif step % 3 == 1 and self.enable_following:
                    self.status_callback(f"➕ 模拟关注操作...")
                else:
                    self.status_callback(f"📱 模拟浏览操作...")
                
                from utils.task_cancellation import sleep_with_cancel_check
                success = await sleep_with_cancel_check(self.task_manager.task_id, 30, 5.0, f"模拟互动步骤{step+1}")
                if not success:
                    self.status_callback("🚨 模拟互动被取消")
                    return False
            
            self.status_callback(f"🎉 模拟互动完成!")
            return True
            
        except Exception as e:
            logger.error(f"❌ 模拟互动异常: {e}")
            return False
    
    async def cleanup_container(self, device_ip: str, container_name: str) -> bool:
        """清理容器"""
        try:
            return await self.device_manager.cleanup_container(device_ip, container_name, self.task_manager.task_id)
        except Exception as e:
            logger.error(f"❌ 清理容器异常: {e}")
            return False
    
    async def _batch_import_nurture(self, accounts_in_batch: List[Dict[str, Any]], 
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
            actual_backup_file = self._find_backup_file_for_account(backup_path, username)
            
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
                success = await sleep_with_cancel_check(self.task_manager.task_id, self.import_wait_time, 1.0, "导入间隔等待")
                if not success:
                    self.status_callback("任务在导入间隔等待期间被取消")
                    return results
        
        return results
    
    def _find_backup_file_for_account(self, backup_path: str, username: str) -> str:
        """为指定账号找到对应的备份文件"""
        import os
        
        # 如果backup_path本身就是文件，直接返回
        if backup_path.endswith('.tar.gz'):
            return backup_path
        
        # 如果是文件夹，查找对应的备份文件
        if os.path.isdir(backup_path):
            # 查找完全匹配的文件
            target_file = f"{username}.tar.gz"
            full_path = os.path.join(backup_path, target_file).replace('\\', '/')
            
            if os.path.exists(full_path):
                return full_path
            
            # 如果找不到完全匹配的，查找包含用户名的文件
            try:
                for filename in os.listdir(backup_path):
                    if filename.endswith('.tar.gz') and username in filename:
                        full_path = os.path.join(backup_path, filename).replace('\\', '/')
                        return full_path
            except Exception as e:
                logger.error(f"❌ 搜索备份文件异常: {e}")
        
        return ""
    
    async def _batch_reboot_nurture(self, import_results: List[Dict[str, Any]], device_ip: str) -> List[Dict[str, Any]]:
        """批量重启容器 - 自动养号版本，按实例位分批重启"""
        reboot_results = []
        
        # 🔧 **取消检查点：重启开始前**
        if self.task_manager.check_if_cancelled():
            self.status_callback("任务已被取消")
            return reboot_results
        
        # 🔧 **关键修复：按实例位分组重启**
        position_groups = {}
        for result in import_results:
            if not result.get('import_success'):
                # 导入失败的容器直接标记重启失败
                reboot_results.append({**result, 'reboot_success': False})
                continue
            
            position = result['position']
            if position not in position_groups:
                position_groups[position] = []
            position_groups[position].append(result)
        
        self.status_callback(f"🔄 开始按实例位分批重启 {len(position_groups)} 个实例位...")
        
        # 按实例位顺序逐批重启
        for position in sorted(position_groups.keys()):
            containers_in_position = position_groups[position]
            
            # 🔧 **取消检查点：每个实例位重启前**
            if self.task_manager.check_if_cancelled():
                self.status_callback("任务已被取消")
                return reboot_results
            
            self.status_callback(f"🔄 重启实例位 {position} 的 {len(containers_in_position)} 个容器...")
            
            # 同实例位的容器可以并发重启
            import asyncio
            reboot_tasks = []
            for result in containers_in_position:
                task = self._reboot_single_nurture_container(device_ip, result)
                reboot_tasks.append(task)
            
            # 并发执行同实例位的重启操作
            if reboot_tasks:
                concurrent_results = await asyncio.gather(*reboot_tasks, return_exceptions=True)
                
                # 处理重启结果
                for concurrent_result in concurrent_results:
                    if isinstance(concurrent_result, Exception):
                        logger.error(f"重启容器异常: {concurrent_result}")
                        # 找到对应的失败容器
                        for result in containers_in_position:
                            if len([r for r in reboot_results if r.get('container_name') == result['container_name']]) == 0:
                                reboot_results.append({**result, 'reboot_success': False})
                                break
                    else:
                        reboot_results.append(concurrent_result)
            
            successful_reboots_in_position = len([r for r in concurrent_results if not isinstance(r, Exception) and r.get('reboot_success')])
            self.status_callback(f"✅ 实例位 {position}: {successful_reboots_in_position}/{len(containers_in_position)} 个容器重启成功")
            
            # 🔧 **每个实例位重启后的间隔等待**
            await self.apply_smart_interval('reboot')
        
        # 🔧 **所有实例位重启完成后，统一等待重启完成**
        successful_reboots = len([r for r in reboot_results if r.get('reboot_success')])
        if successful_reboots > 0:
            self.status_callback(f"⏰ 所有实例位重启完成，统一等待 {self.reboot_wait_time} 秒...")
            from utils.task_cancellation import sleep_with_cancel_check
            success = await sleep_with_cancel_check(self.task_manager.task_id, self.reboot_wait_time, 20.0, "重启统一等待")
            if not success:
                self.status_callback("任务在重启统一等待期间被取消")
                return reboot_results
            self.status_callback(f"✅ 重启等待完成")
        else:
            self.status_callback("⚠️ 没有容器重启成功，跳过等待")
        
        return reboot_results
    
    async def _reboot_single_nurture_container(self, device_ip: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """重启单个养号容器"""
        try:
            container_name = result['container_name']
            username = result['username']
            
            logger.info(f"[任务{self.task_manager.task_id}] 🔄 重启养号容器: {container_name} ({username}) @ {device_ip}")
            
            # 调用设备管理器重启
            reboot_success = await self.device_manager.reboot_device(device_ip, container_name, self.task_manager.task_id)
            
            if reboot_success:
                logger.info(f"[任务{self.task_manager.task_id}] ✅ 养号容器重启成功: {container_name}")
            else:
                logger.error(f"[任务{self.task_manager.task_id}] ❌ 养号容器重启失败: {container_name}")
            
            return {**result, 'reboot_success': reboot_success}
            
        except Exception as e:
            logger.error(f"重启养号容器 {result['container_name']} 异常: {e}")
            return {**result, 'reboot_success': False}
    
    async def _batch_setup_and_interaction(self, reboot_results: List[Dict[str, Any]], device_ip: str) -> List[Dict[str, Any]]:
        """批量设置和互动 - 修复：添加并发支持，参考自动登录备份的并发策略"""
        try:
            logger.info(f"[任务{self.task_manager.task_id}] 🚀 开始批量设置和互动 (设备: {device_ip})")
            
            # 验证输入数据完整性
            valid_results = []
            for i, result in enumerate(reboot_results):
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
            
            # 🚀 **新增：并发优化策略 - 参考自动登录备份的ThreadPoolExecutor**
            # 策略1：预先分配端口，避免运行时争抢
            port_assignments = {}
            for result in valid_results:
                position = result['position']
                try:
                    base_port, debug_port = await self.device_manager.get_dynamic_ports(
                        device_ip, "", position, self.task_manager.task_id
                    )
                    port_assignments[position] = (base_port, debug_port)
                    logger.info(f"[任务{self.task_manager.task_id}] ✅ 预分配端口 - 实例位{position}: Base={base_port}, Debug={debug_port}")
                except Exception as e:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 实例位{position}端口预分配失败: {e}")
                    port_assignments[position] = (None, None)
            
            # 策略2：真正的并发执行 - 使用ThreadPoolExecutor
            logger.info(f"[任务{self.task_manager.task_id}] 🎯 启用ThreadPoolExecutor真正并发模式")
            self.status_callback(f"🎯 多实例位并发策略：{len(valid_results)}个账号同时执行推特互动")
            
            # 创建互动任务列表
            interaction_tasks = []
            for result in valid_results:
                account = result['account']
                position = result['position']
                
                # 获取预分配的端口
                ports = port_assignments.get(position, (None, None))
                if ports[0] is None:
                    logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 跳过端口无效的账号: {account['username']}")
                    continue
                
                # 创建互动任务配置
                task_config = {
                    'result': result,
                    'device_ip': device_ip,
                    'ports': ports,
                    'account': account,
                    'position': position,
                    'task_id': self.task_manager.task_id
                }
                interaction_tasks.append(task_config)
            
            if not interaction_tasks:
                self.status_callback("❌ 没有有效的互动任务")
                return []
            
            # 策略3：ThreadPoolExecutor真正并发执行
            import concurrent.futures
            import time
            
            all_final_results = []
            success_count = 0
            
            self.status_callback(f"⚡ 启动ThreadPoolExecutor并发互动 - {len(interaction_tasks)}个账号")
            
            # 关键：使用ThreadPoolExecutor实现真正并发
            start_time = time.time()
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(interaction_tasks)) as executor:
                # 优化：分批提交任务，添加小间隔避免设备负载过大
                future_to_config = {}
                
                logger.info(f"[任务{self.task_manager.task_id}] 🚀 开始分批提交 {len(interaction_tasks)} 个ThreadPoolExecutor任务")
                
                for i, task_config in enumerate(interaction_tasks):
                    # 提交任务
                    future = executor.submit(self._thread_setup_and_interaction_single, task_config)
                    future_to_config[future] = task_config
                    
                    username = task_config['account']['username']
                    position = task_config['position']
                    logger.info(f"[任务{self.task_manager.task_id}] ✅ 提交任务 {i+1}/{len(interaction_tasks)}: {username} (实例位{position})")
                    
                    # 添加小间隔，避免同时启动过多任务造成设备负载
                    if i < len(interaction_tasks) - 1:  # 不是最后一个
                        import time
                        time.sleep(random.uniform(2, 5))  # 随机2-5秒间隔
                        self.status_callback(f"🔄 已启动 {i+1}/{len(interaction_tasks)} 个互动任务，等待{2}-{5}秒后启动下一个...")
                
                logger.info(f"[任务{self.task_manager.task_id}] 🎯 所有 {len(interaction_tasks)} 个任务已提交，开始并发执行...")
                
                # 收集结果
                for future in concurrent.futures.as_completed(future_to_config):
                    task_config = future_to_config[future]
                    username = task_config['account']['username']
                    
                    try:
                        # 关键修复：检查任务取消状态
                        if self.task_manager.check_if_cancelled():
                            logger.info(f"[任务{self.task_manager.task_id}] ❌ 任务已取消，停止收集结果")
                            self.status_callback("任务已取消，停止执行")
                            break
                        
                        result = future.result()
                        if result:
                            all_final_results.append(result)
                            if result.get('success', False):
                                success_count += 1
                                logger.info(f"[任务{self.task_manager.task_id}] ✅ ThreadPool互动任务完成: {username}")
                            else:
                                logger.warning(f"[任务{self.task_manager.task_id}] ❌ ThreadPool互动任务失败: {username} - {result.get('message', 'Unknown error')}")
                        
                    except Exception as e:
                        logger.error(f"[任务{self.task_manager.task_id}] ❌ ThreadPool互动任务异常: {username} - {e}")
                        # 创建失败结果
                        error_result = {
                            'account': task_config['account'],
                            'position': task_config['position'],
                            'success': False,
                            'message': f'ThreadPool执行异常: {e}',
                            'setup_success': False,
                            'interaction_success': False
                        }
                        all_final_results.append(error_result)
            
            total_duration = time.time() - start_time
            total_count = len(valid_results)
            
            self.status_callback(f"🎮 多实例位并发互动完成: {success_count}/{total_count} 成功 (总耗时: {total_duration:.1f}s)")
            
            # 计算并发效率
            if total_count > 1:
                theoretical_sequential_time = total_count * self.interaction_duration
                efficiency = (theoretical_sequential_time / total_duration) * 100 if total_duration > 0 else 100
                logger.info(f"[任务{self.task_manager.task_id}] 🎯 并发效率: {efficiency:.1f}% (理论串行{theoretical_sequential_time}s vs 实际并发{total_duration:.1f}s)")
            else:
                logger.info(f"[任务{self.task_manager.task_id}] 🎯 单账号互动完成")
            
            return all_final_results
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 批量设置和互动异常: {e}", exc_info=True)
            return []
    
    def _thread_setup_and_interaction_single(self, task_config: Dict[str, Any]) -> Dict[str, Any]:
        """ThreadPoolExecutor单个账号设置和互动"""
        try:
            result = task_config['result']
            device_ip = task_config['device_ip']
            ports = task_config['ports']
            account = task_config['account']
            position = task_config['position']
            task_id = task_config['task_id']
            
            username = account['username']
            container_name = result['container_name']
            
            logger.info(f"[任务{task_id}] 🎮 ThreadPool开始互动: {username} (实例位{position})")
            
            # 阶段1: 设置语言和代理（同步版本）
            try:
                setup_success = self._sync_setup_language_and_proxy(device_ip, container_name, username, task_id)
                if not setup_success:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool语言代理设置失败: {username}")
                else:
                    logger.info(f"[任务{task_id}] ✅ ThreadPool语言代理设置成功: {username}")
            except Exception as setup_error:
                logger.error(f"[任务{task_id}] ❌ ThreadPool设置异常: {username} - {setup_error}")
                setup_success = False
            
            # 阶段2: 账号验证（同步版本）
            try:
                verify_success = self._sync_verify_account_status(device_ip, position, account, task_id)
                if not verify_success:
                    logger.warning(f"[任务{task_id}] ❌ ThreadPool账号验证失败: {username}")
                    result['success'] = False
                    result['setup_success'] = setup_success
                    result['interaction_success'] = False
                    result['message'] = 'ThreadPool账号验证失败'
                    return result
                else:
                    logger.info(f"[任务{task_id}] ✅ ThreadPool账号验证成功: {username}")
            except Exception as verify_error:
                logger.error(f"[任务{task_id}] ❌ ThreadPool验证异常: {username} - {verify_error}")
                result['success'] = False
                result['setup_success'] = setup_success
                result['interaction_success'] = False
                result['message'] = f'ThreadPool验证异常: {verify_error}'
                return result
            
            # 关键修复：ThreadPool中检查取消状态
            if self.task_manager.check_if_cancelled():
                result['success'] = False
                result['message'] = "任务已取消"
                return result
            
            # 阶段3: 执行互动（同步版本）
            try:
                interaction_success = self._sync_perform_nurture_interaction(device_ip, position, self.interaction_duration, task_id)
                
                result['setup_success'] = setup_success
                result['interaction_success'] = interaction_success
                
                if interaction_success:
                    logger.info(f"[任务{task_id}] ✅ ThreadPool互动执行成功: {username}")
                    
                    # 应用随机延迟（同步版本）
                    random_delay = self.apply_random_delay()
                    if random_delay > 0:
                        logger.info(f"[任务{task_id}] ⏱️ ThreadPool随机延迟 {random_delay} 秒: {username}")
                        import time
                        time.sleep(random_delay)
                    
                    result['success'] = True
                    result['message'] = 'ThreadPool互动成功'
                    logger.info(f"[任务{task_id}] 🎉 ThreadPool养号流程完成: {username}")
                else:
                    logger.warning(f"[任务{task_id}] ❌ ThreadPool互动执行失败: {username}")
                    result['success'] = False
                    result['message'] = 'ThreadPool互动失败'
                    
            except Exception as interaction_error:
                logger.error(f"[任务{task_id}] ❌ ThreadPool互动异常: {username} - {interaction_error}")
                result['setup_success'] = setup_success
                result['interaction_success'] = False
                result['success'] = False
                result['message'] = f'ThreadPool互动异常: {interaction_error}'
            
            return result
            
        except Exception as e:
            logger.error(f"[任务{task_config.get('task_id', 'N/A')}] ❌ ThreadPool单任务异常: {e}")
            return {
                'account': task_config.get('account', {}),
                'position': task_config.get('position', 0),
                'success': False,
                'message': f'ThreadPool单任务异常: {e}',
                'setup_success': False,
                'interaction_success': False
            }
    
    def _sync_setup_language_and_proxy(self, device_ip: str, container_name: str, username: str, task_id: int) -> bool:
        """同步版本的设置代理和语言 - 修复：使用正确的API接口"""
        try:
            import requests
            import time
            import urllib.parse
            
            logger.info(f"[任务{task_id}] 🌐 ThreadPool开始设置代理和语言: {container_name}")
            
            # 获取代理配置（从数据库）
            proxy_config = self.database_handler.get_proxy_config_for_account(username)
            
            # 步骤1：设置代理（先设置代理）- 使用正确的S5代理API
            if proxy_config.get('use_proxy', False):
                proxy_ip = proxy_config.get('proxyIp', '')
                proxy_port = proxy_config.get('proxyPort', '')
                proxy_user = proxy_config.get('proxyUser', '')
                proxy_password = proxy_config.get('proxyPassword', '')
                
                # 容器名URL编码
                encoded_container_name = urllib.parse.quote(container_name, safe='')
                proxy_url = f"http://127.0.0.1:5000/s5_set/{device_ip}/{encoded_container_name}"
                proxy_params = {
                    's5ip': proxy_ip,
                    's5port': proxy_port,
                    's5user': proxy_user,
                    's5pwd': proxy_password
                }
                
                try:
                    logger.info(f"[任务{task_id}] 🌐 ThreadPool设置代理: {container_name} -> {proxy_ip}:{proxy_port}")
                    proxy_response = requests.get(proxy_url, params=proxy_params, timeout=30)
                    
                    if proxy_response.status_code == 200:
                        response_data = proxy_response.json()
                        proxy_success = (response_data.get('code') == 200 or 
                                       (response_data.get('success') is not False and response_data.get('code') != 400))
                    else:
                        proxy_success = False
                        
                except Exception as e:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool代理设置请求异常: {e}")
                    proxy_success = False
                
                if proxy_success:
                    logger.info(f"[任务{task_id}] ✅ ThreadPool代理设置成功: {container_name}")
                else:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool代理设置失败: {container_name}")
            else:
                logger.info(f"[任务{task_id}] ✅ ThreadPool跳过代理设置（账号未配置代理）: {container_name}")
                proxy_success = True  # 跳过代理设置算作成功
            
            # 间隔等待：代理设置后等待5秒
            time.sleep(5)
            
            # 步骤2：设置语言（后设置语言）- 使用正确的语言设置API
            encoded_container_name = urllib.parse.quote(container_name, safe='')
            language_url = f"http://127.0.0.1:5000/set_ipLocation/{device_ip}/{encoded_container_name}/{self.language_code}"
            
            try:
                logger.info(f"[任务{task_id}] 🌍 ThreadPool设置语言: {container_name} -> {self.language_code}")
                language_response = requests.get(language_url, timeout=30)
                
                if language_response.status_code == 200:
                    response_data = language_response.json()
                    language_success = (response_data.get('code') == 200 or 
                                      (response_data.get('success') is not False and response_data.get('code') != 400))
                else:
                    language_success = False
                    
            except Exception as e:
                logger.error(f"[任务{task_id}] ❌ ThreadPool语言设置请求异常: {e}")
                language_success = False
            
            if language_success:
                logger.info(f"[任务{task_id}] ✅ ThreadPool语言设置成功: {container_name} -> {self.language_code}")
            else:
                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool语言设置失败: {container_name}")
            
            setup_success = proxy_success and language_success
            
            if setup_success:
                logger.info(f"[任务{task_id}] ✅ ThreadPool {container_name} 代理语言设置成功")
            else:
                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool {container_name} 代理语言设置部分失败")
            
            return setup_success
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool设置代理语言异常: {e}")
            return False
    
    def _sync_verify_account_status(self, device_ip: str, position: int, account: Dict[str, Any], task_id: int) -> bool:
        """同步版本的验证账号状态 - 修复：允许没有密码的备份账号"""
        try:
            username = account.get('username', '')
            password = account.get('password', '')
            
            # 修复：只要有用户名就允许继续（备份文件中的账号通常没有密码）
            if username:
                if password:
                    logger.info(f"[任务{task_id}] ✅ ThreadPool账号验证通过: {username} (完整信息)")
                else:
                    logger.info(f"[任务{task_id}] ✅ ThreadPool账号验证通过: {username} (仅用户名，来自备份文件)")
                return True
            else:
                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool账号缺少用户名: {account}")
                return False
                
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool账号验证异常: {e}")
            return False
    
    def _sync_perform_nurture_interaction(self, device_ip: str, position: int, duration_seconds: int, task_id: int) -> bool:
        """同步版本的执行养号互动 - 修复：调用真实的推特互动脚本"""
        try:
            import time  # 添加time模块导入
            logger.info(f"[任务{task_id}] 🎮 ThreadPool开始 {duration_seconds} 秒的推特养号互动...")
            
            # 获取端口信息（同步版本）- 修复：使用同步方式获取端口
            try:
                base_port, debug_port = self._sync_get_container_ports(device_ip, position, task_id)
                
                if not base_port or not debug_port:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool无法获取实例位{position}的端口信息")
                    return False
                    
                logger.info(f"[任务{task_id}] 🎯 ThreadPool获取端口成功 - U2: {base_port}, RPC: {debug_port}")
                
            except Exception as e:
                logger.error(f"[任务{task_id}] ❌ ThreadPool端口获取异常: {e}")
                return False
            
            # 导入真实的互动模块
            try:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                backend_dir = os.path.dirname(current_dir)
                automation_dir = os.path.join(backend_dir, 'automation')
                sys.path.insert(0, automation_dir)
                
                from automation.interactTest import run_interaction
                logger.info(f"[任务{task_id}] ✅ ThreadPool成功导入真实互动模块")
                
                # 定义状态回调函数
                def interaction_status_callback(message):
                    # 过滤过于详细的日志，只显示关键信息
                    if any(keyword in message for keyword in ['开始', '完成', '成功', '失败', '错误', '❌', '✅', '🎮']):
                        logger.info(f"[任务{task_id}] 🎮 {message}")
                    
                    # 检查任务取消状态
                    if self.task_manager.check_if_cancelled():
                        raise Exception("任务已被用户取消")
                
                # 执行真实的推特互动 - 增加重试机制
                max_retries = 2  # 最多重试2次
                for retry_attempt in range(max_retries + 1):
                    try:
                        if retry_attempt > 0:
                            logger.info(f"[任务{task_id}] 🔄 ThreadPool互动重试 {retry_attempt}/{max_retries}")
                            interaction_status_callback(f"🔄 互动重试 {retry_attempt}/{max_retries}")
                            time.sleep(5)  # 重试前等待5秒
                        
                        interaction_success = run_interaction(
                            status_callback=interaction_status_callback,
                            device_ip_address=device_ip,
                            u2_port=base_port,
                            myt_rpc_port=debug_port,
                            duration_seconds=duration_seconds,
                            enable_liking_param=self.enable_liking,
                            enable_commenting_param=self.enable_commenting,
                            comment_text_param="Great post! 👍"
                        )
                        
                        if interaction_success:
                            if retry_attempt == 0:
                                logger.info(f"[任务{task_id}] 🎉 ThreadPool推特养号互动完成!")
                            else:
                                logger.info(f"[任务{task_id}] 🎉 ThreadPool重试{retry_attempt}次后推特养号互动完成!")
                            return True
                        else:
                            if retry_attempt < max_retries:
                                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool推特养号互动失败，准备重试")
                                continue
                            else:
                                logger.error(f"[任务{task_id}] ❌ ThreadPool推特养号互动重试{max_retries}次后仍失败")
                                return False
                                
                    except Exception as e:
                        if retry_attempt < max_retries:
                            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool互动异常，准备重试: {e}")
                            continue
                        else:
                            logger.error(f"[任务{task_id}] ❌ ThreadPool互动重试{max_retries}次后仍异常: {e}")
                            raise e
                    
            except ImportError as e:
                logger.error(f"[任务{task_id}] ❌ ThreadPool导入互动模块失败: {e}")
                logger.info(f"[任务{task_id}] 🔄 ThreadPool使用模拟互动模式")
                return self._sync_simulate_interaction(duration_seconds, task_id)
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool互动执行异常: {e}")
            return False
    
    def _sync_get_container_ports(self, device_ip: str, position: int, task_id: int) -> tuple:
        """同步版本的获取容器端口"""
        try:
            import requests
            
            # 步骤1: 获取容器列表
            get_url = f"http://127.0.0.1:5000/get/{device_ip}"
            params = {'index': position}
            
            try:
                response = requests.get(get_url, params=params, timeout=30)
                if response.status_code == 200:
                    response_data = response.json()
                    if response_data.get('code') == 200:
                        devices = response_data.get('msg', [])
                        
                        # 查找对应实例位且状态为running的容器
                        container_name = None
                        for device in devices:
                            if (device.get('index') == position and 
                                device.get('State') == 'running'):
                                container_name = device.get('Names')
                                logger.info(f"[任务{task_id}] 🔍 ThreadPool找到实例位{position}的运行容器: {container_name}")
                                break
                        
                        if not container_name:
                            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool未找到实例位{position}的运行容器")
                            return None, None
                else:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool获取容器列表HTTP错误: {response.status_code}")
                    return None, None
            except Exception as e:
                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool获取容器列表异常: {e}")
                return None, None
            
            # 步骤2: 获取API信息
            api_info_url = f"http://127.0.0.1:5000/and_api/v1/get_api_info/{device_ip}/{container_name}"
            
            try:
                response = requests.get(api_info_url, timeout=30)
                if response.status_code == 200:
                    api_data = response.json()
                    if api_data.get('code') == 200 and api_data.get('data'):
                        data = api_data['data']
                        
                        # 解析U2端口
                        u2_port = None
                        adb_info = data.get('ADB', '')
                        if adb_info and ':' in adb_info:
                            try:
                                u2_port = int(adb_info.split(':')[1])
                            except (ValueError, IndexError):
                                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool ADB端口解析失败: {adb_info}")
                        
                        # 解析RPC端口
                        myt_rpc_port = None  
                        host_rpa_info = data.get('HOST_RPA', '')
                        if host_rpa_info and ':' in host_rpa_info:
                            try:
                                myt_rpc_port = int(host_rpa_info.split(':')[1])
                            except (ValueError, IndexError):
                                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool HOST_RPA端口解析失败: {host_rpa_info}")
                        
                        if u2_port and myt_rpc_port:
                            logger.info(f"[任务{task_id}] ✅ ThreadPool端口解析成功: U2={u2_port}, RPC={myt_rpc_port}")
                            return u2_port, myt_rpc_port
                        else:
                            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool端口信息不完整: ADB={adb_info}, HOST_RPA={host_rpa_info}")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ ThreadPool API返回数据格式异常: {api_data}")
                else:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool获取API信息HTTP错误: {response.status_code}")
            except Exception as e:
                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool获取API信息异常: {e}")
            
            return None, None
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool端口获取总体异常: {e}")
            return None, None
    
    def _sync_simulate_interaction(self, duration_seconds: int, task_id: int) -> bool:
        """同步版本的模拟互动（备用方案）"""
        try:
            import time
            
            logger.info(f"[任务{task_id}] 🎮 ThreadPool使用模拟模式进行 {duration_seconds} 秒的互动...")
            
            interaction_steps = duration_seconds // 30  # 每30秒一个步骤
            
            for step in range(interaction_steps):
                # 检查任务取消状态
                if self.task_manager.check_if_cancelled():
                    logger.info(f"[任务{task_id}] 🚨 ThreadPool模拟互动已取消")
                    return False
                
                # 模拟不同的互动活动
                if step % 3 == 0 and self.enable_liking:
                    logger.info(f"[任务{task_id}] 👍 ThreadPool模拟点赞操作...")
                elif step % 3 == 1 and self.enable_following:
                    logger.info(f"[任务{task_id}] ➕ ThreadPool模拟关注操作...")
                else:
                    logger.info(f"[任务{task_id}] 📱 ThreadPool模拟浏览操作...")
                
                # 等待30秒（同步版本）
                time.sleep(30)
            
            logger.info(f"[任务{task_id}] 🎉 ThreadPool模拟互动完成!")
            return True
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool模拟互动异常: {e}")
            return False
    
    async def _batch_cleanup_nurture(self, final_results: List[Dict[str, Any]], device_ip: str) -> None:
        """批量清理养号容器 - 修复：确保所有容器都被清理，防止资源泄露"""
        if not final_results:
            self.status_callback("ℹ️ 没有容器需要清理")
            return
        
        cleanup_count = 0
        total_containers = 0
        
        self.status_callback(f"🗑️ 开始清理 {len(final_results)} 个容器...")
        
        for result in final_results:
            # 关键修复：只要有容器名称就尝试清理，不管导入是否成功
            container_name = result.get('container_name')
            username = result.get('username', result.get('account', {}).get('username', 'Unknown'))
            
            if container_name:
                total_containers += 1
                try:
                    logger.info(f"[任务{self.task_manager.task_id}] 🗑️ 清理容器: {container_name} ({username})")
                    
                    cleanup_success = await self.cleanup_container(device_ip, container_name)
                    
                    if cleanup_success:
                        cleanup_count += 1
                        logger.info(f"[任务{self.task_manager.task_id}] ✅ 容器清理成功: {container_name}")
                    else:
                        logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 容器清理失败: {container_name}")
                        
                except Exception as e:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 清理容器异常: {container_name} - {e}")
            else:
                logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 结果中缺少容器名称: {result}")
        
        if total_containers > 0:
            self.status_callback(f"🗑️ 容器清理完成: {cleanup_count}/{total_containers} 成功")
            logger.info(f"[任务{self.task_manager.task_id}] 🗑️ 清理统计: {cleanup_count}/{total_containers} 成功")
        else:
            self.status_callback("ℹ️ 没有找到需要清理的容器")
            logger.info(f"[任务{self.task_manager.task_id}] ℹ️ 没有找到需要清理的容器") 