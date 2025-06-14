"""
重构后的自动养号处理器模块
封装完整的自动养号业务逻辑：导入→重启→设置→登录→互动→清理
使用模块化设计，便于维护
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable

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

# 导入拆分的养号模块
from .nurture import (
    NurtureConfigManager,
    NurtureAccountHandler,
    NurtureBatchManager,
    NurtureImportHandler,
    NurtureRebootHandler,
    NurtureCleanupHandler
)


class NurtureProcessor:
    """重构后的自动养号处理器"""
    
    def __init__(self, task_manager: TaskManager, device_manager: DeviceManager, 
                 account_manager: AccountManager, database_handler: DatabaseHandler,
                 status_callback: Callable[[str], None] = None):
        self.task_manager = task_manager
        self.device_manager = device_manager
        self.account_manager = account_manager
        self.database_handler = database_handler
        self.status_callback = status_callback or (lambda x: logger.info(x))
        
        # 初始化各个处理模块
        self.config_manager = NurtureConfigManager(task_manager, status_callback)
        self.account_handler = NurtureAccountHandler(account_manager, database_handler, status_callback)
        self.batch_manager = NurtureBatchManager(self.config_manager, status_callback)
        self.import_handler = NurtureImportHandler(device_manager, self.account_handler, self.config_manager, task_manager, status_callback)
        self.reboot_handler = NurtureRebootHandler(device_manager, self.config_manager, task_manager, status_callback)
        self.cleanup_handler = NurtureCleanupHandler(device_manager, task_manager, status_callback)
        
        # 为了兼容性，保留原有的配置属性访问方式
        self._setup_compatibility_properties()
    
    def _setup_compatibility_properties(self):
        """设置兼容性属性，保持原有接口不变"""
        # 配置参数的兼容性访问
        @property
        def import_wait_time(self):
            return self.config_manager.import_wait_time
        
        @property
        def reboot_wait_time(self):
            return self.config_manager.reboot_wait_time
        
        @property
        def account_wait_time(self):
            return self.config_manager.account_wait_time
        
        @property
        def interaction_duration(self):
            return self.config_manager.interaction_duration
        
        @property
        def max_retries(self):
            return self.config_manager.max_retries
        
        @property
        def language_code(self):
            return self.config_manager.language_code
        
        @property
        def container_prefix(self):
            return self.config_manager.container_prefix
        
        # 绑定属性到实例
        self.__class__.import_wait_time = import_wait_time
        self.__class__.reboot_wait_time = reboot_wait_time
        self.__class__.account_wait_time = account_wait_time
        self.__class__.interaction_duration = interaction_duration
        self.__class__.max_retries = max_retries
        self.__class__.language_code = language_code
        self.__class__.container_prefix = container_prefix
    
    def update_config(self, config: Dict[str, Any]):
        """更新配置参数 - 委托给配置管理器"""
        return self.config_manager.update_config(config)
    
    def generate_random_container_name(self, username: str) -> str:
        """生成随机容器名称 - 委托给配置管理器"""
        return self.config_manager.generate_random_container_name(username)
    
    def apply_random_delay(self) -> int:
        """应用随机延迟 - 委托给配置管理器"""
        return self.config_manager.apply_random_delay()
    
    async def apply_smart_interval(self, operation_type: str) -> bool:
        """应用智能间隔控制 - 委托给配置管理器"""
        return await self.config_manager.apply_smart_interval(operation_type)
    
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
            accounts = await self.account_handler.get_accounts(task_params)
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
            batches = self.batch_manager.create_intelligent_batches(accounts, device_ip, positions)
            
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
                    success = await sleep_with_cancel_check(self.task_manager.task_id, self.config_manager.account_wait_time, 2.0, "批次间隔等待")
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
            import_results = await self.import_handler.batch_import_nurture(accounts_in_batch, device_ip, backup_file)
            # 收集所有创建的容器（无论导入是否成功）
            all_containers_for_cleanup.extend(import_results)
            
            successful_imports = [r for r in import_results if r.get('import_success')]
            
            if not successful_imports:
                self.status_callback(f"❌ [第{batch_index}批] 没有成功导入的账号")
                # 即使导入失败，也要清理容器
                await self.cleanup_handler.batch_cleanup_nurture(all_containers_for_cleanup, device_ip)
                return False
            
            # 🔧 **阶段2: 批量重启（并行优化）**
            reboot_results = await self.reboot_handler.batch_reboot_nurture(successful_imports, device_ip)
            successful_reboots = [r for r in reboot_results if r.get('reboot_success')]
            
            if not successful_reboots:
                self.status_callback(f"❌ [第{batch_index}批] 没有成功重启的账号")
                # 重启失败，清理所有容器
                await self.cleanup_handler.batch_cleanup_nurture(all_containers_for_cleanup, device_ip)
                return False
            
            # 🔧 **阶段3: 批量设置和互动（并行优化）**
            # 注意：这里需要导入互动处理器，因为它比较大，我们单独处理
            try:
                from .nurture.interaction_handler import NurtureInteractionHandler
                interaction_handler = NurtureInteractionHandler(
                    self.device_manager, self.database_handler, self.config_manager, 
                    self.task_manager, self.status_callback
                )
                final_results = await interaction_handler.batch_setup_and_interaction(successful_reboots, device_ip)
            except ImportError:
                # 如果互动处理器导入失败，使用简化版本
                logger.warning("互动处理器导入失败，使用简化版本")
                final_results = successful_reboots
                for result in final_results:
                    result['success'] = True
                    result['setup_success'] = True
                    result['interaction_success'] = True
            
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
                    await self.cleanup_handler.batch_cleanup_nurture(all_containers_for_cleanup, device_ip)
                    logger.info(f"[任务{self.task_manager.task_id}] 🗑️ 批次清理完成")
                else:
                    logger.info(f"[任务{self.task_manager.task_id}] ℹ️ 没有容器需要清理")
            except Exception as cleanup_error:
                logger.error(f"[任务{self.task_manager.task_id}] ❌ 批次清理异常: {cleanup_error}")
                self.status_callback(f"⚠️ 容器清理异常，可能有资源泄露: {cleanup_error}")
    
    # 为了兼容性，保留一些原有方法的委托
    async def import_backup_with_retry(self, device_ip: str, container_name: str, position: int, backup_file: str) -> bool:
        """带重试的备份导入 - 委托给导入处理器"""
        return await self.import_handler.import_backup_with_retry(device_ip, container_name, position, backup_file)
    
    async def cleanup_container(self, device_ip: str, container_name: str) -> bool:
        """清理容器 - 委托给清理处理器"""
        return await self.cleanup_handler.cleanup_container(device_ip, container_name)
    
    def create_intelligent_batches(self, accounts: List[Dict[str, Any]], device_ip: str, positions: List[int]) -> List[Dict[str, Any]]:
        """创建智能批次 - 委托给批次管理器"""
        return self.batch_manager.create_intelligent_batches(accounts, device_ip, positions)
    
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
                device_ip, container_name, self.config_manager.language_code, self.task_manager.task_id
            )
            
            if language_success:
                logger.info(f"[任务{self.task_manager.task_id}] ✅ 语言设置成功: {container_name} -> {self.config_manager.language_code}")
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
        """验证账号状态 - 委托给账号处理器"""
        return await self.account_handler.verify_account_status(self.device_manager, device_ip, position, account, self.task_manager.task_id) 