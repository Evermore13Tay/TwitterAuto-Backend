"""
批量处理器核心模块
封装复杂的批量登录备份流程，减少主业务逻辑复杂度
"""

import asyncio
import logging
import concurrent.futures
import time
import aiohttp
import os
import threading
import requests
import random
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

# 🔧 新增：ThreadPool直接设备连接所需的导入
import uiautomator2 as u2
import pyotp
from common.mytRpc import MytRpc

from .task_manager import TaskManager
from .device_manager import DeviceManager  
from .account_manager import AccountManager
from .database_handler import DatabaseHandler

logger = logging.getLogger("TwitterAutomationAPI")

class BatchProcessor:
    """批量处理器核心类"""
    
    def __init__(self, task_manager: TaskManager, device_manager: DeviceManager, 
                 account_manager: AccountManager, database_handler: DatabaseHandler):
        self.task_manager = task_manager
        self.device_manager = device_manager
        self.account_manager = account_manager
        self.database_handler = database_handler
        
        # 批量处理配置 - 默认值，会被任务参数覆盖
        self.accounts_per_batch = 10
        self.import_interval = 3
        self.import_wait_time = 15
        self.reboot_interval = 1
        self.reboot_wait_time = 165  # 默认值，会被任务参数覆盖
        
        # 🚀 优化：高效并发登录配置（参考login_routes最佳实践）
        self.efficient_login_mode = True  # 启用高效模式
        self.login_base_stagger = 2       # 基础错峰延迟（秒）- 从10秒优化到2秒
        self.login_random_variance = 3  # 随机延迟范围（秒）- 从5-15秒优化到0-1.5秒
        self.login_timeout = 180          # 登录超时（秒）- 更短的超时时间
        self.suspension_check_timeout = 20 # 封号检测超时（秒）
        self.backup_timeout = 180         # 备份超时（秒）
        self.max_concurrent_logins = 10   # 最大并发登录数（参考login_routes）
        
    def configure_login_mode(self, mode: str = "efficient"):
        """
        配置登录模式
        
        Args:
            mode: "efficient" 高效模式 或 "conservative" 保守模式
        """
        if mode == "efficient":
            # 🚀 高效模式：最大化并发效率
            self.efficient_login_mode = True
            self.login_base_stagger = 2
            self.login_random_variance = 1.5
            self.login_timeout = 120
            self.suspension_check_timeout = 20
            self.backup_timeout = 120
            logger.info("✅ 已切换到高效登录模式：2秒错峰 + 1.5秒随机延迟")
            
        elif mode == "conservative": 
            # 🛡️ 保守模式：优先稳定性
            self.efficient_login_mode = False
            self.login_base_stagger = 8
            self.login_random_variance = 5
            self.login_timeout = 300
            self.suspension_check_timeout = 60
            self.backup_timeout = 300
            logger.info("🛡️ 已切换到保守登录模式：8秒错峰 + 5秒随机延迟")
            
        elif mode == "ultra_fast":
            # ⚡ 极速模式：极致效率（适合测试环境）
            self.efficient_login_mode = True
            self.login_base_stagger = 1
            self.login_random_variance = 0.5
            self.login_timeout = 60
            self.suspension_check_timeout = 10
            self.backup_timeout = 60
            logger.info("⚡ 已切换到极速登录模式：1秒错峰 + 0.5秒随机延迟")
            
        else:
            logger.warning(f"⚠️ 未知的登录模式: {mode}，保持当前配置")
            
    def get_current_efficiency_stats(self) -> dict:
        """获取当前效率配置统计"""
        max_delay_per_account = self.login_base_stagger + self.login_random_variance
        estimated_delay_for_10_accounts = 10 * max_delay_per_account
        
        return {
            "mode": "efficient" if self.efficient_login_mode else "conservative",
            "base_stagger": self.login_base_stagger,
            "random_variance": self.login_random_variance,
            "max_delay_per_account": max_delay_per_account,
            "estimated_10_accounts_delay": estimated_delay_for_10_accounts,
            "login_timeout": self.login_timeout,
            "suspension_timeout": self.suspension_check_timeout,
            "backup_timeout": self.backup_timeout
        }
    
    async def execute_batch_login_backup(self, task_params: Dict[str, Any]) -> bool:
        """
        执行完整的批量登录备份流程
        
        Args:
            task_params: 任务参数
            
        Returns:
            bool: 是否成功
        """
        try:
            # 解析参数
            parsed_params = self._parse_parameters(task_params)
            if not parsed_params:
                self.task_manager.fail_task("参数解析失败")
                return False
            
            device_ip = parsed_params['device_ip']
            instance_slots = parsed_params['instance_slots']
            wait_time = parsed_params['wait_time']
            pure_backup_file = parsed_params['pure_backup_file']
            
            # 🔧 应用用户设置的等待时间
            self.reboot_wait_time = wait_time
            self.task_manager.status_callback(f"✅ 应用用户设置的重启等待时间: {wait_time}秒")
            
            # 🔧 关键修复：强化取消检查
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在启动时被取消")
                return False
            
            # 获取账号列表
            accounts = await self._get_accounts(task_params)
            if not accounts:
                return False
            
            # 分配账号到实例位
            slot_assignments = self._assign_accounts_to_slots(accounts, instance_slots)
            
            # 创建批次
            account_batches = self._create_batches(slot_assignments)
            
            self.task_manager.status_callback(f"📊 开始处理 {len(accounts)} 个账号，分为 {len(account_batches)} 个批次")
            self.task_manager.status_callback(f"📋 批次策略：每批次包含所有实例位的1个账号，按轮次处理")
            
            # 🔧 新增：初始化统计数据
            total_accounts_processed = []
            
            # 逐批次处理
            successful_accounts = []
            for batch_num, current_batch in enumerate(account_batches):
                # 🔧 关键修复：每个批次开始时检查取消状态
                if self.task_manager.check_if_cancelled():
                    self.task_manager.status_callback(f"任务在第{batch_num+1}批次开始时被取消")
                    return False
                
                self.task_manager.update_progress(
                    (batch_num / len(account_batches)) * 100,
                    f"处理批次 {batch_num + 1}/{len(account_batches)}"
                )
                
                batch_results = await self._process_single_batch(
                    current_batch, device_ip, pure_backup_file, batch_num + 1
                )
                
                # 🔧 关键修复：每个批次完成后立即检查取消状态
                if self.task_manager.check_if_cancelled():
                    self.task_manager.status_callback(f"任务在第{batch_num+1}批次完成后被取消")
                    return False
                
                successful_accounts.extend(batch_results)
                
                # 🔧 新增：收集所有处理过的账号用于最终统计
                for result in batch_results:
                    if result and 'account' in result:
                        total_accounts_processed.append(result)
                
                # 🔧 关键修复：批次间短暂暂停，给取消检查更多机会
                if batch_num < len(account_batches) - 1:  # 不是最后一个批次
                    await asyncio.sleep(0.5)  # 短暂暂停0.5秒
                    if self.task_manager.check_if_cancelled():
                        self.task_manager.status_callback(f"任务在批次间隔时被取消")
                        return False
            
            # 🚀 **新增功能：最终任务总结打印**
            await self._print_final_task_summary(total_accounts_processed)
            
            # 完成任务
            self.task_manager.complete_task(f"批量备份完成，成功处理 {len(successful_accounts)} 个账号")
            return True
            
        except Exception as e:
            logger.error(f"批量处理异常: {e}", exc_info=True)
            self.task_manager.fail_task(f"批量处理异常: {e}")
            return False
    
    def _parse_parameters(self, task_params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """解析任务参数"""
        try:
            batch_params = task_params.get('batchLoginBackupParams', {})
            
            # 获取基本参数
            device_ip = batch_params.get('targetIp', '10.18.96.3')
            instance_slot = batch_params.get('instanceSlot', 1)
            instance_slots = batch_params.get('instanceSlots', [instance_slot])
            wait_time = batch_params.get('waitTime', 60)
            
            # 🔧 **修复：统一前后端等待时间计算逻辑**
            base_wait_time = 60
            additional_time_per_slot = 35  # 与前端保持一致
            recommended_wait_time = base_wait_time + (len(instance_slots) - 1) * additional_time_per_slot
            
            # 🔧 **修复：只在用户设置时间过低时调整，否则尊重用户设置**
            if wait_time < recommended_wait_time:
                wait_time = recommended_wait_time
                self.task_manager.status_callback(f"⚠️ 等待时间过低，自动调整为推荐时间: {wait_time}s")
            else:
                self.task_manager.status_callback(f"✅ 使用用户设置的等待时间: {wait_time}s")
            
            # 获取备份文件路径
            pure_backup_file = batch_params.get('pureBackupFile', '')
            if not pure_backup_file or not os.path.exists(pure_backup_file):
                logger.error(f"纯净备份文件不存在或未提供: {pure_backup_file}")
                return None
            
            return {
                'device_ip': device_ip,
                'instance_slots': instance_slots,
                'wait_time': wait_time,
                'pure_backup_file': pure_backup_file,
                'batch_params': batch_params
            }
            
        except Exception as e:
            logger.error(f"参数解析异常: {e}", exc_info=True)
            return None
    
    async def _get_accounts(self, task_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取要处理的账号列表"""
        try:
            accounts = []
            account_group_id = task_params.get('selectedAccountGroup')
            accounts_str = task_params.get('batchLoginBackupParams', {}).get('accounts', '')
            
            if account_group_id:
                # 从数据库分组获取账号
                accounts, stats = self.database_handler.get_accounts_by_group(
                    group_id=account_group_id,
                    exclude_backed_up=True,
                    exclude_suspended=True
                )
                
                self.task_manager.status_callback(
                    f"📊 分组账号统计: 总数={stats.get('total_accounts', 0)}, "
                    f"已备份={stats.get('skipped_backed_up', 0)}, "
                    f"已封号={stats.get('skipped_suspended', 0)}, "
                    f"待备份={stats.get('valid_accounts', 0)}"
                )
                
            elif accounts_str:
                # 从字符串解析账号
                accounts = self.account_manager.parse_accounts_from_string(accounts_str)
                
                # 为每个账号查询数据库ID
                for account in accounts:
                    account_info = self.database_handler.get_account_by_username(account['username'])
                    if account_info:
                        account['id'] = account_info['id']
                    else:
                        account['id'] = None
                        logger.warning(f"⚠️ 无法找到账号 {account['username']} 的ID")
            
            if not accounts:
                if account_group_id:
                    self.task_manager.complete_task("该分组的所有账号都已处理完成")
                else:
                    self.task_manager.fail_task("未找到有效的账号信息")
                return []
            
            self.task_manager.status_callback(f"✅ 解析到 {len(accounts)} 个待处理账号")
            return accounts
            
        except Exception as e:
            logger.error(f"获取账号列表异常: {e}", exc_info=True)
            self.task_manager.fail_task(f"获取账号失败: {e}")
            return []
    
    def _assign_accounts_to_slots(self, accounts: List[Dict[str, Any]], instance_slots: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        """分配账号到实例位"""
        total_accounts = len(accounts)
        total_slots = len(instance_slots)
        
        # 计算每个实例位分配的账号数量
        accounts_per_slot = total_accounts // total_slots
        remaining_accounts = total_accounts % total_slots
        
        slot_assignments = {}
        account_index = 0
        
        for i, slot in enumerate(instance_slots):
            slot_account_count = accounts_per_slot
            if i < remaining_accounts:
                slot_account_count += 1
            
            slot_accounts = accounts[account_index:account_index + slot_account_count]
            slot_assignments[slot] = slot_accounts
            account_index += slot_account_count
            
            self.task_manager.status_callback(f"实例位 {slot}: 分配 {len(slot_accounts)} 个账号")
        
        return slot_assignments
    
    def _create_batches(self, slot_assignments: Dict[int, List[Dict[str, Any]]]) -> List[List[Tuple[int, Dict[str, Any]]]]:
        """创建处理批次（轮转分配）- 修复：按实例位轮次创建批次"""
        account_batches = []
        max_accounts_per_slot = max(len(slot_accounts) for slot_accounts in slot_assignments.values())
        
        # 🔧 **关键修复：按轮次创建批次，确保每批次包含所有实例位的账号**
        for round_idx in range(max_accounts_per_slot):
            current_batch = []
            for slot_num in sorted(slot_assignments.keys()):
                if round_idx < len(slot_assignments[slot_num]):
                    account = slot_assignments[slot_num][round_idx]
                    current_batch.append((slot_num, account))
            
            # 如果当前批次有账号，就添加到批次列表
            if current_batch:
                account_batches.append(current_batch)
        
        return account_batches
    
    async def _process_single_batch(self, batch: List[Tuple[int, Dict[str, Any]]], 
                                  device_ip: str, pure_backup_file: str, batch_num: int) -> List[Dict[str, Any]]:
        """处理单个批次"""
        try:
            self.task_manager.status_callback(f"📦 开始处理批次 {batch_num} (包含 {len(batch)} 个账号)")
            
            # 🔧 关键修复：每个阶段前检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在批次处理开始时被取消")
                return []
            
            # 阶段1：批量导入
            import_results = await self._batch_import(batch, device_ip, pure_backup_file)
            
            # 🔧 关键修复：导入后检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在导入阶段后被取消")
                return []
            
            # 阶段2：批量重启
            reboot_results = await self._batch_reboot(import_results, device_ip)
            
            # 🔧 关键修复：重启后检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在重启阶段后被取消")
                return []
            
            # 阶段3：批量设置代理和语言
            setup_results = await self._batch_setup_proxy_language(reboot_results, device_ip)
            
            # 🔧 关键修复：设置后检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在代理设置阶段后被取消")
                return []
            
            # 阶段4：批量登录和备份
            final_results = await self._batch_login_backup(setup_results, device_ip)
            
            # 🔧 关键修复：登录备份后检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在登录备份阶段后被取消")
                return []
            
            # 阶段5：清理容器
            await self._batch_cleanup(final_results, device_ip)
            
            successful_accounts = [result for result in final_results if result.get('success')]
            self.task_manager.status_callback(f"✅ 批次 {batch_num} 完成，成功 {len(successful_accounts)} 个账号")
            
            return successful_accounts
            
        except Exception as e:
            logger.error(f"处理批次异常: {e}", exc_info=True)
            return []
    
    async def _batch_import(self, batch: List[Tuple[int, Dict[str, Any]]], 
                           device_ip: str, pure_backup_file: str) -> List[Dict[str, Any]]:
        """批量导入纯净备份"""
        results = []
        container_names = []
        slot_numbers = []
        
        # 🔧 **修复容器名重复问题：每个容器都应该有独立的时间戳**
        for i, (slot_num, account) in enumerate(batch):
            slot_numbers.append(slot_num)
            # 每个容器添加独立的随机后缀，避免重复
            unique_suffix = int(time.time() * 1000) + i * 1000 + random.randint(1, 999)
            container_name = f"Pure_{slot_num}_{unique_suffix}"
            container_names.append(container_name)
        
        # 🔧 添加冲突设备清理
        self.task_manager.status_callback(f"🧹 检查并清理实例位 {slot_numbers} 的冲突设备...")
        conflict_cleanup_success = await self.device_manager.cleanup_conflict_devices(
            device_ip, slot_numbers, container_names, self.task_manager.task_id
        )
        
        if not conflict_cleanup_success:
            self.task_manager.status_callback("⚠️ 冲突设备清理失败，但继续执行")
        
        for i, (slot_num, account) in enumerate(batch):
            # 🔧 **关键修复：每个操作前检查取消状态**
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务已被取消")
                return results
            
            container_name = container_names[i]
            
            self.task_manager.status_callback(f"📦 导入实例位 {slot_num}: {account['username']}")
            
            import_success = await self.device_manager.import_backup(
                device_ip, slot_num, pure_backup_file, container_name, self.task_manager.task_id
            )
            
            # 🔧 **取消检查点2：导入后检查**
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务已被取消")
                return results
            
            results.append({
                'slot_num': slot_num,
                'account': account,
                'container_name': container_name,
                'import_success': import_success
            })
            
            # 导入间隔等待（带取消检查）
            if i < len(batch) - 1:  # 最后一个不需要等待
                success = await self._wait_with_cancellation_check(self.import_interval, "导入间隔等待")
                if not success:  # 如果等待期间被取消，立即返回
                    self.task_manager.status_callback("任务在导入间隔等待期间被取消")
                    return results
        
        return results
    
    async def _batch_reboot(self, import_results: List[Dict[str, Any]], device_ip: str) -> List[Dict[str, Any]]:
        """批量重启容器 - 修复：按实例位分批重启"""
        reboot_results = []
        
        # 🔧 **取消检查点：重启开始前**
        if self.task_manager.check_if_cancelled():
            self.task_manager.status_callback("任务已被取消")
            return reboot_results
        
        # 筛选出导入成功的容器
        successful_imports = [result for result in import_results if result.get('import_success')]
        
        if not successful_imports:
            self.task_manager.status_callback("⚠️ 没有导入成功的容器需要重启")
            # 返回所有结果，标记重启失败
            for result in import_results:
                reboot_results.append({**result, 'reboot_success': False})
            return reboot_results
        
        self.task_manager.status_callback(f"🔄 开始批量重启 {len(successful_imports)} 个容器...")
        
        # 🔧 **关键修复：按实例位分组重启**
        # 先按实例位分组
        position_groups = {}
        for result in import_results:
            if not result.get('import_success'):
                # 导入失败的容器直接标记重启失败
                reboot_results.append({**result, 'reboot_success': False})
                continue
            
            slot_num = result['slot_num']
            if slot_num not in position_groups:
                position_groups[slot_num] = []
            position_groups[slot_num].append(result)
        
        # 按实例位顺序逐批重启
        for slot_num in sorted(position_groups.keys()):
            containers_in_slot = position_groups[slot_num]
            
            # 🔧 **取消检查点：每个实例位重启前**
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务已被取消")
                return reboot_results
            
            self.task_manager.status_callback(f"🔄 重启实例位 {slot_num} 的 {len(containers_in_slot)} 个容器...")
            
            # 同实例位的容器可以并发重启
            import asyncio
            reboot_tasks = []
            for result in containers_in_slot:
                task = self._reboot_single_container(device_ip, result)
                reboot_tasks.append(task)
            
            # 并发执行同实例位的重启操作
            if reboot_tasks:
                concurrent_results = await asyncio.gather(*reboot_tasks, return_exceptions=True)
                
                # 处理重启结果
                for concurrent_result in concurrent_results:
                    if isinstance(concurrent_result, Exception):
                        logger.error(f"重启容器异常: {concurrent_result}")
                        # 找到对应的失败容器
                        for result in containers_in_slot:
                            if len([r for r in reboot_results if r.get('container_name') == result['container_name']]) == 0:
                                reboot_results.append({**result, 'reboot_success': False})
                                break
                    else:
                        reboot_results.append(concurrent_result)
            
            successful_reboots_in_slot = len([r for r in concurrent_results if not isinstance(r, Exception) and r.get('reboot_success')])
            self.task_manager.status_callback(f"✅ 实例位 {slot_num}: {successful_reboots_in_slot}/{len(containers_in_slot)} 个容器重启成功")
            
            # 🔧 **每个实例位重启后的间隔等待**
            if slot_num != max(position_groups.keys()):  # 不是最后一个实例位
                success = await self._wait_with_cancellation_check(self.reboot_interval, f"实例位 {slot_num} 重启间隔")
                if not success:
                    self.task_manager.status_callback("任务在实例位重启间隔期间被取消")
                    return reboot_results
        
        # 🔧 **所有实例位重启完成后，统一等待重启完成**
        successful_reboots = len([r for r in reboot_results if r.get('reboot_success')])
        if successful_reboots > 0:
            self.task_manager.status_callback(f"⏰ 所有实例位重启完成，统一等待 {self.reboot_wait_time} 秒...")
            await self._wait_with_cancellation_check(self.reboot_wait_time, "重启统一等待")
            self.task_manager.status_callback(f"✅ 重启等待完成")
        else:
            self.task_manager.status_callback("⚠️ 没有容器重启成功，跳过等待")
        
        return reboot_results
    
    async def _reboot_single_container(self, device_ip: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """重启单个容器 - 绕过DeviceManager间隔控制，实现真正并发"""
        try:
            # 🔧 **关键修复：直接调用BoxManipulate API，绕过DeviceManager的间隔控制**
            try:
                import sys
                import os
                current_dir = os.path.dirname(os.path.abspath(__file__))
                backend_dir = os.path.dirname(current_dir)
                automation_dir = os.path.join(backend_dir, 'automation')
                sys.path.insert(0, automation_dir)
                
                from automation.BoxManipulate import call_reboot_api
                
                container_name = result['container_name']
                logger.info(f"[任务{self.task_manager.task_id}] 🔄 并发重启容器: {container_name} @ {device_ip}")
                
                # 直接调用重启API，实现真正并发
                reboot_success = call_reboot_api(device_ip, container_name, wait_after_reboot=False)
                
                if reboot_success:
                    logger.info(f"[任务{self.task_manager.task_id}] ✅ 容器重启成功: {container_name}")
                else:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 容器重启失败: {container_name}")
                
                return {**result, 'reboot_success': reboot_success}
                
            except ImportError as e:
                logger.error(f"[任务{self.task_manager.task_id}] 导入BoxManipulate失败: {e}")
                return {**result, 'reboot_success': False}
            
        except Exception as e:
            logger.error(f"重启容器 {result['container_name']} 异常: {e}")
            return {**result, 'reboot_success': False}
    
    async def _batch_setup_proxy_language(self, reboot_results: List[Dict[str, Any]], 
                                         device_ip: str) -> List[Dict[str, Any]]:
        """批量设置代理和语言 - 修复：逐个设置避免并发冲突"""
        try:
            self.task_manager.status_callback("🌐 开始批量设置代理和语言...")
            
            # 🔧 **调试信息：检查输入数据结构**
            logger.info(f"[任务{self.task_manager.task_id}] 📋 收到 {len(reboot_results)} 个重启结果")
            for i, result in enumerate(reboot_results):
                logger.info(f"[任务{self.task_manager.task_id}] 结果 {i+1}: 字段={list(result.keys())}")
                if 'slot_num' not in result:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 缺少 slot_num 字段: {result}")
            
            successful_setups = []
            
            # 🔧 **关键修复：逐个设置代理和语言，避免并发冲突**
            for i, result in enumerate(reboot_results):
                # 检查取消状态
                if self.task_manager.check_if_cancelled():
                    self.task_manager.status_callback("任务已被取消")
                    return successful_setups
                
                container_name = result['container_name']
                account = result['account']
                username = account['username']
                slot_num = result['slot_num']  # 确保有这个字段
                
                # 获取代理配置
                proxy_config = self.database_handler.get_proxy_config_for_account(username)
                
                self.task_manager.status_callback(f"🔧 设置实例位 {slot_num}: {container_name}")
                
                try:
                    # 🔧 **步骤1：设置代理（带重试）**
                    proxy_success = await self.device_manager.set_device_proxy(
                        device_ip, container_name, proxy_config, self.task_manager.task_id
                    )
                    
                    if proxy_success:
                        logger.info(f"[任务{self.task_manager.task_id}] ✅ 实例位 {slot_num} 代理设置成功")
                    else:
                        logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 实例位 {slot_num} 代理设置失败")
                    
                    # 🔧 **间隔等待：代理设置后等待5秒**
                    await asyncio.sleep(5)
                    
                    # 🔧 **步骤2：设置语言（带重试）**
                    language_success = await self.device_manager.set_device_language(
                        device_ip, container_name, 'en', self.task_manager.task_id
                    )
                    
                    if language_success:
                        logger.info(f"[任务{self.task_manager.task_id}] ✅ 实例位 {slot_num} 语言设置成功")
                    else:
                        logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 实例位 {slot_num} 语言设置失败")
                    
                    setup_success = proxy_success and language_success
                    
                    if setup_success:
                        logger.info(f"[任务{self.task_manager.task_id}] ✅ {container_name} 代理语言设置成功")
                    else:
                        logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ {container_name} 代理语言设置部分失败")
                    
                    successful_setups.append({
                        'slot_num': slot_num,
                        'container_name': container_name,
                        'account': account,
                        'setup_success': setup_success,
                        'proxy_config': proxy_config
                    })
                    
                except Exception as e:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ {container_name} 设置异常: {e}")
                    successful_setups.append({
                        'slot_num': slot_num,
                        'container_name': container_name,
                        'account': account,
                        'setup_success': False,
                        'proxy_config': proxy_config
                    })
                
                # 🔧 **实例间隔：每个实例设置完成后等待5秒（除了最后一个）**
                if i < len(reboot_results) - 1:
                    await asyncio.sleep(5)
                    self.task_manager.status_callback(f"⏰ 实例位 {slot_num} 设置完成，等待5秒后处理下一个...")
            
            success_count = sum(1 for r in successful_setups if r['setup_success'])
            self.task_manager.status_callback(f"✅ 代理语言设置完成: {success_count}/{len(reboot_results)} 成功")
            
            return successful_setups
            
        except Exception as e:
            error_msg = f"批量设置代理语言异常: {e}"
            logger.error(f"[任务{self.task_manager.task_id}] ❌ {error_msg}", exc_info=True)
            self.task_manager.fail_task(error_msg)
            return []
    
    async def _batch_login_backup(self, setup_results: List[Dict[str, Any]], device_ip: str) -> List[Dict[str, Any]]:
        """批量登录和备份 - 🚀 真正并发版本"""
        try:
            logger.info(f"[任务{self.task_manager.task_id}] 🚀 开始批量登录备份 (设备: {device_ip})")
            
            # 验证输入数据完整性
            valid_results = []
            for i, result in enumerate(setup_results):
                if 'slot_num' not in result:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 设置结果缺少 slot_num 字段: {result}")
                    continue
                if not result.get('setup_success', False):
                    logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 跳过设置失败的结果: slot_num={result.get('slot_num')}")
                    continue
                valid_results.append(result)
            
            if not valid_results:
                self.task_manager.status_callback("❌ 没有可执行的登录任务")
                return []
            
            # 🚀 **革命性优化：真正的ThreadPoolExecutor并发登录**
            # **策略1：预先分配端口，避免运行时争抢**
            port_assignments = {}
            for result in valid_results:
                slot_num = result['slot_num']
                try:
                    u2_port, myt_rpc_port = await self.device_manager.get_container_ports(
                        device_ip, slot_num, self.task_manager.task_id
                    )
                    port_assignments[slot_num] = (u2_port, myt_rpc_port)
                    logger.info(f"[任务{self.task_manager.task_id}] ✅ 预分配端口 - 实例位{slot_num}: U2={u2_port}, RPC={myt_rpc_port}")
                except Exception as e:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 实例位{slot_num}端口预分配失败: {e}")
                    port_assignments[slot_num] = (None, None)
            
            # **策略2：真正的并发执行 - 借鉴batch_login_test.py的ThreadPoolExecutor**
            # 🔧 关键修复：使用ThreadPoolExecutor绕过MytRpc全局连接锁
            logger.info(f"[任务{self.task_manager.task_id}] 🎯 启用ThreadPoolExecutor真正并发模式")
            self.task_manager.status_callback(f"🎯 真正并发策略：{len(valid_results)}个账号ThreadPoolExecutor并发登录")
            
            # 创建登录任务列表
            login_tasks = []
            for result in valid_results:
                account = result['account']
                slot_num = result['slot_num']
                
                # 获取预分配的端口
                ports = port_assignments.get(slot_num, (None, None))
                if ports[0] is None:
                    logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 跳过端口无效的账号: {account['username']}")
                    continue
                
                # 创建登录任务配置
                task_config = {
                    'result': result,
                    'device_ip': device_ip,
                    'ports': ports,
                    'account': account,
                    'slot_num': slot_num,
                    'task_id': self.task_manager.task_id
                }
                login_tasks.append(task_config)
            
            if not login_tasks:
                self.task_manager.status_callback("❌ 没有有效的登录任务")
                return []
            
            # **策略3：ThreadPoolExecutor真正并发执行**
            all_final_results = []
            success_count = 0
            
            self.task_manager.status_callback(f"⚡ 启动ThreadPoolExecutor并发登录 - {len(login_tasks)}个账号")
            
            # 🚀 关键：使用ThreadPoolExecutor实现真正并发
            start_time = time.time()
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(login_tasks)) as executor:
                # 提交所有登录任务
                future_to_config = {
                    executor.submit(self._thread_login_backup_single, task_config): task_config 
                    for task_config in login_tasks
                }
                
                logger.info(f"[任务{self.task_manager.task_id}] 🚀 同时提交 {len(login_tasks)} 个ThreadPoolExecutor任务")
                
                # 收集结果
                for future in concurrent.futures.as_completed(future_to_config):
                    task_config = future_to_config[future]
                    username = task_config['account']['username']
                    
                    try:
                        # 🔧 关键修复：检查任务取消状态
                        if self.task_manager.check_if_cancelled():
                            logger.info(f"[任务{self.task_manager.task_id}] ❌ 任务已取消，停止收集结果")
                            self.task_manager.status_callback("任务已取消，停止执行")
                            break
                        
                        result = future.result()
                        if result:
                            all_final_results.append(result)
                            if result.get('success', False):
                                success_count += 1
                                logger.info(f"[任务{self.task_manager.task_id}] ✅ ThreadPool任务完成: {username}")
                            else:
                                logger.warning(f"[任务{self.task_manager.task_id}] ❌ ThreadPool任务失败: {username} - {result.get('message', 'Unknown error')}")
                        
                    except Exception as e:
                        logger.error(f"[任务{self.task_manager.task_id}] ❌ ThreadPool任务异常: {username} - {e}")
                        # 创建失败结果
                        error_result = {
                            'account': task_config['account'],
                            'slot_num': task_config['slot_num'],
                            'success': False,
                            'message': f'ThreadPool执行异常: {e}',
                            'login_success': False,
                            'backup_success': False
                        }
                        all_final_results.append(error_result)
            
            total_duration = time.time() - start_time
            total_count = len(valid_results)
            
            self.task_manager.status_callback(f"🔐 ThreadPoolExecutor并发登录完成: {success_count}/{total_count} 成功 (耗时: {total_duration:.1f}s)")
            logger.info(f"[任务{self.task_manager.task_id}] 🎯 并发性能: 平均每账号 {total_duration/total_count:.1f}s (真正并发)")
            
            return all_final_results
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 批量登录备份异常: {e}", exc_info=True)
            return []

    def _thread_login_backup_single(self, task_config: Dict[str, Any]) -> Dict[str, Any]:
        """ThreadPoolExecutor单个账号登录备份（绕过asyncio和MytRpc全局锁）"""
        try:
            result = task_config['result']
            device_ip = task_config['device_ip']
            ports = task_config['ports']
            account = task_config['account']
            slot_num = task_config['slot_num']
            task_id = task_config['task_id']
            
            username = account['username']
            u2_port, myt_rpc_port = ports
            
            logger.info(f"[任务{task_id}] 🔐 ThreadPool开始登录: {username} (实例位{slot_num})")
            
            # 🚀 **优化1：真正的并发登录（绕过MytRpc全局锁）**
            try:
                # 🔧 修复版：使用batch_login_test.py验证有效的直接设备连接方法
                login_success = self._sync_account_login(
                    device_ip, u2_port, myt_rpc_port,
                    account['username'], account['password'], account['secretkey'],
                    task_id
                )
            except Exception as login_error:
                logger.error(f"[任务{task_id}] ❌ ThreadPool登录异常: {username} - {login_error}")
                login_success = False
            
            if not login_success:
                logger.warning(f"[任务{task_id}] ❌ ThreadPool账号登录失败: {username}")
                result['success'] = False
                result['login_success'] = False
                result['message'] = 'ThreadPool登录失败'
                return result
            
            logger.info(f"[任务{task_id}] ✅ ThreadPool账号登录成功: {username}")
            result['login_success'] = True
            
            # 🔧 关键修复：ThreadPool中检查取消状态
            if self.task_manager.check_if_cancelled():
                result['success'] = False
                result['message'] = "任务已取消"
                return result
            
            # 🚀 **优化2：快速备份导出**
            try:
                container_name = result.get('container_name', f"twitter_{slot_num}")
                backup_success = self._sync_export_account_backup(
                    device_ip, container_name, username, task_id
                )
                
                result['backup_success'] = backup_success
                
                if backup_success:
                    logger.info(f"[任务{task_id}] ✅ ThreadPool备份导出成功: {username}")
                    
                    # 🔧 强化：更新数据库备份状态并记录详细日志
                    if account.get('id'):
                        logger.info(f"[任务{task_id}] 📝 正在更新数据库备份状态: {username} (ID: {account['id']})")
                        update_success = self.database_handler.update_account_backup_status(account['id'], 1)
                        if update_success:
                            logger.info(f"[任务{task_id}] ✅ 数据库备份状态更新成功: {username} → backup_exported=1")
                        else:
                            logger.warning(f"[任务{task_id}] ⚠️ 数据库备份状态更新失败: {username}")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ 账号ID为空，无法更新数据库: {username}")
                    
                    result['success'] = True
                    result['message'] = 'ThreadPool登录备份成功'
                else:
                    logger.warning(f"[任务{task_id}] ❌ ThreadPool备份导出失败: {username}")
                    result['success'] = False
                    result['message'] = 'ThreadPool备份失败'
                    
            except Exception as backup_error:
                logger.error(f"[任务{task_id}] ❌ ThreadPool备份异常: {username} - {backup_error}")
                result['backup_success'] = False
                result['success'] = False
                result['message'] = f'ThreadPool备份异常: {backup_error}'
            
            return result
            
        except Exception as e:
            logger.error(f"[任务{task_config.get('task_id', 'N/A')}] ❌ ThreadPool单任务异常: {e}")
            return {
                'account': task_config.get('account', {}),
                'slot_num': task_config.get('slot_num', 0),
                'success': False,
                'message': f'ThreadPool单任务异常: {e}',
                'login_success': False,
                'backup_success': False
            }

    def _sync_account_login(self, device_ip: str, u2_port: int, myt_rpc_port: int, 
                           username: str, password: str, secret_key: str, task_id: int) -> bool:
        """🔧 修复版：使用batch_login_test.py验证有效的直接设备连接方法"""
        # 增强重试机制
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                logger.info(f"[任务{task_id}] 🔗 ThreadPool直接连接设备 (尝试 {attempt + 1}/{max_retries}): {username}")
                
                # 🚀 关键修复：使用batch_login_test.py中验证有效的方法
                # 直接连接设备，而不是通过HTTP API
                import uiautomator2 as u2
                import pyotp
                from common.mytRpc import MytRpc
                
                start_time = time.time()
                
                # Step 1: 连接设备（增强错误处理）
                u2_d = None
                mytapi = None
                
                try:
                    # 连接u2设备
                    u2_d = u2.connect(f"{device_ip}:{u2_port}")
                    if not u2_d:
                        raise Exception("u2设备连接失败")
                        
                    # 验证u2连接
                    screen_info = u2_d.device_info
                    logger.info(f"[任务{task_id}] ✅ ThreadPool u2连接成功: {username}")
                    
                except Exception as u2_error:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool u2连接失败: {username} - {u2_error}")
                    if attempt < max_retries - 1:
                        time.sleep(5)  # 等待5秒后重试
                        continue
                    else:
                        return False
                
                try:
                    # 连接MytRpc
                    mytapi = MytRpc()
                    
                    # 🔧 增强连接逻辑：更长的超时时间和重试
                    connection_timeout = 20  # 增加到20秒
                    if not mytapi.init(device_ip, myt_rpc_port, connection_timeout):
                        raise Exception(f"MytRpc连接失败，超时{connection_timeout}秒")
                    
                    logger.info(f"[任务{task_id}] ✅ ThreadPool MytRpc连接成功: {username}")
                    
                except Exception as rpc_error:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool MytRpc连接失败: {username} - {rpc_error}")
                    if attempt < max_retries - 1:
                        time.sleep(8)  # MytRpc失败等待更长时间
                        continue
                    else:
                        return False
                
                logger.info(f"[任务{task_id}] ✅ ThreadPool设备连接成功: {username}")
                
                # Step 2: 获取屏幕尺寸并设置坐标（完全匹配batch_login_test.py）
                try:
                    screen_width, screen_height = u2_d.window_size()
                    
                    # 使用batch_login_test.py中验证成功的坐标
                    U2_COORDS = (0.644, 0.947)
                    mytrpc_x = int(U2_COORDS[0] * screen_width)
                    mytrpc_y = int(U2_COORDS[1] * screen_height)
                    
                    logger.info(f"[任务{task_id}] 📍 ThreadPool坐标转换: u2{U2_COORDS} → MytRpc({mytrpc_x}, {mytrpc_y})")
                    
                except Exception as coord_error:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool坐标转换失败: {username} - {coord_error}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # Step 3: 重启Twitter应用确保干净状态（增强版）
                logger.info(f"[任务{task_id}] 🔄 ThreadPool重启Twitter应用: {username}")
                try:
                    # 强制关闭
                    mytapi.exec_cmd("am force-stop com.twitter.android")
                    time.sleep(3)
                    
                    # 清理可能的残留进程
                    mytapi.exec_cmd("am kill com.twitter.android") 
                    time.sleep(1)
                    
                    # 启动应用
                    mytapi.exec_cmd("am start -n com.twitter.android/.StartActivity")
                    time.sleep(10)  # 给应用更多启动时间
                    
                except Exception as app_error:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool重启应用失败: {app_error}")
                    # 应用重启失败不是致命错误，继续尝试
                
                # Step 4: 检查是否已经登录（完全匹配batch_login_test.py）
                logger.info(f"[任务{task_id}] 🔍 ThreadPool检查登录状态: {username}")
                login_indicators = [
                    '//*[@content-desc="Show navigation drawer"]',
                    '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]',
                    '//*[@content-desc="Home Tab"]',
                    '//*[@resource-id="com.twitter.android:id/tweet_button"]'
                ]
                
                already_logged_in = False
                for xpath in login_indicators:
                    try:
                        if u2_d.xpath(xpath).exists:
                            duration = time.time() - start_time
                            logger.info(f"[任务{task_id}] ✅ ThreadPool账户已经登录: {username} (耗时: {duration:.1f}s)")
                            return True
                    except Exception:
                        continue
                
                # Step 5: 使用验证成功的双击方法（完全匹配batch_login_test.py）
                logger.info(f"[任务{task_id}] 📍 ThreadPool使用双击方法点击登录按钮: {username}")
                try:
                    # 第一次点击
                    mytapi.touchDown(0, mytrpc_x, mytrpc_y)
                    time.sleep(1.5)
                    mytapi.touchUp(0, mytrpc_x, mytrpc_y)
                    time.sleep(1)
                    
                    # 第二次点击
                    mytapi.touchDown(0, mytrpc_x, mytrpc_y)
                    time.sleep(1.5)
                    mytapi.touchUp(0, mytrpc_x, mytrpc_y)
                    time.sleep(12)  # 等待页面跳转
                    
                except Exception as click_error:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool点击登录按钮失败: {username} - {click_error}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # Step 6: 输入用户名（完全匹配batch_login_test.py）
                logger.info(f"[任务{task_id}] 👤 ThreadPool输入用户名: {username}")
                if not self._thread_input_username(u2_d, mytapi, username, task_id):
                    logger.error(f"[任务{task_id}] ❌ ThreadPool输入用户名失败: {username}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # Step 7: 输入密码（完全匹配batch_login_test.py）
                logger.info(f"[任务{task_id}] 🔐 ThreadPool输入密码: {username}")
                if not self._thread_input_password(u2_d, mytapi, password, task_id):
                    logger.error(f"[任务{task_id}] ❌ ThreadPool输入密码失败: {username}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # Step 8: 处理2FA验证（完全匹配batch_login_test.py）
                logger.info(f"[任务{task_id}] 🔢 ThreadPool处理2FA验证: {username}")
                if not self._thread_handle_2fa(u2_d, mytapi, secret_key, task_id):
                    logger.error(f"[任务{task_id}] ❌ ThreadPool 2FA验证失败: {username}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # Step 9: 验证登录成功（完全匹配batch_login_test.py）
                logger.info(f"[任务{task_id}] ✅ ThreadPool验证登录状态: {username}")
                if not self._thread_verify_login_success(u2_d, task_id, username, device_ip):
                    logger.error(f"[任务{task_id}] ❌ ThreadPool登录验证失败: {username}")
                    if attempt < max_retries - 1:
                        # 验证失败，清理资源并重试
                        try:
                            if mytapi:
                                mytapi.setRpaWorkMode(0)
                        except:
                            pass
                        continue
                    else:
                        return False
                
                duration = time.time() - start_time
                logger.info(f"[任务{task_id}] ✅ ThreadPool登录成功: {username} (耗时: {duration:.1f}s)")
                
                # 🔧 成功后清理MytRpc连接状态，为下次使用做准备
                try:
                    if mytapi:
                        mytapi.setRpaWorkMode(0)
                        logger.info(f"[任务{task_id}] 🧹 ThreadPool已清理MytRpc状态: {username}")
                except Exception as cleanup_error:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool MytRpc状态清理失败: {cleanup_error}")
                
                return True
                    
            except Exception as e:
                duration = time.time() - start_time if 'start_time' in locals() else 0
                logger.error(f"[任务{task_id}] ❌ ThreadPool登录异常 (尝试 {attempt + 1}/{max_retries}): {username} - {e} (耗时: {duration:.1f}s)")
                
                # 🔧 关键修复：清理资源后重试
                try:
                    if 'mytapi' in locals() and mytapi:
                        mytapi.setRpaWorkMode(0)
                except:
                    pass
                
                if attempt < max_retries - 1:
                    wait_time = 5 + (attempt * 2)  # 递增等待时间
                    logger.info(f"[任务{task_id}] ⏳ ThreadPool等待{wait_time}秒后重试: {username}")
                    time.sleep(wait_time)
                    continue
                else:
                    return False
        
        # 所有重试都失败
        logger.error(f"[任务{task_id}] ❌ ThreadPool所有重试都失败: {username}")
        return False
    
    def _thread_input_username(self, u2_d, mytapi, username: str, task_id: int) -> bool:
        """ThreadPool版本的用户名输入（基于batch_login_test.py）"""
        try:
            # 查找用户名输入框
            username_selectors = [
                {'method': 'textContains', 'value': 'Phone, email, or username'},
                {'method': 'textContains', 'value': '手机、邮箱或用户名'},
                {'method': 'textContains', 'value': 'Username'},
                {'method': 'class', 'value': 'android.widget.EditText'}
            ]
            
            username_field = None
            for selector in username_selectors:
                try:
                    if selector['method'] == 'textContains':
                        username_field = u2_d(textContains=selector['value'])
                    elif selector['method'] == 'class':
                        username_field = u2_d(className=selector['value'])
                    
                    if username_field and username_field.exists:
                        break
                    else:
                        username_field = None
                except Exception:
                    continue
            
            if not username_field or not username_field.exists:
                logger.error(f"[任务{task_id}] ❌ ThreadPool未找到用户名输入框")
                return False
            
            # 点击输入框
            bounds = username_field.info['bounds']
            center_x = (bounds['left'] + bounds['right']) // 2
            center_y = (bounds['top'] + bounds['bottom']) // 2
            
            mytapi.touchDown(0, center_x, center_y)
            time.sleep(1)
            mytapi.touchUp(0, center_x, center_y)
            time.sleep(1)
            
            # 输入用户名
            self._thread_send_text_char_by_char(mytapi, username)
            
            # 点击Next按钮
            next_button = u2_d.xpath('//*[@resource-id="com.twitter.android:id/cta_button"]//android.widget.Button')
            if next_button.exists:
                next_button.click()
                time.sleep(3)
            
            return True
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool输入用户名异常: {e}")
            return False
    
    def _thread_input_password(self, u2_d, mytapi, password: str, task_id: int) -> bool:
        """ThreadPool版本的密码输入（基于batch_login_test.py）"""
        try:
            # 查找密码输入框
            password_field = u2_d(text="Password")
            if not password_field.exists:
                password_field = u2_d(className="android.widget.EditText", focused=True)
                if not password_field.exists:
                    edit_texts = u2_d(className="android.widget.EditText")
                    if edit_texts.count > 1:
                        password_field = edit_texts[1]
            
            if not password_field.exists:
                logger.error(f"[任务{task_id}] ❌ ThreadPool未找到密码输入框")
                return False
            
            # 点击输入框
            bounds = password_field.info['bounds']
            center_x = (bounds['left'] + bounds['right']) // 2
            center_y = (bounds['top'] + bounds['bottom']) // 2
            
            mytapi.touchDown(0, center_x, center_y)
            time.sleep(1)
            mytapi.touchUp(0, center_x, center_y)
            time.sleep(1)
            
            # 输入密码
            self._thread_send_text_char_by_char(mytapi, password)
            
            # 点击Login按钮
            login_button = u2_d.xpath('//*[@resource-id="com.twitter.android:id/cta_button"]//android.widget.Button')
            if login_button.exists:
                login_button.click()
                time.sleep(5)
            
            return True
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool输入密码异常: {e}")
            return False
    
    def _thread_handle_2fa(self, u2_d, mytapi, secret_key: str, task_id: int) -> bool:
        """ThreadPool版本的2FA处理（基于batch_login_test.py）"""
        try:
            # 检查是否出现2FA页面
            verification_screen = u2_d.xpath('//*[@resource-id="com.twitter.android:id/primary_text"]')
            if not verification_screen.exists or verification_screen.get_text() != 'Enter your verification code':
                logger.info(f"[任务{task_id}] ⚠️ ThreadPool未检测到2FA页面，可能已经登录或不需要2FA")
                return True
            
            logger.info(f"[任务{task_id}] 🔢 ThreadPool检测到2FA验证页面")
            
            # 生成2FA代码
            import pyotp
            totp = pyotp.TOTP(secret_key)
            tfa_code = totp.now()
            logger.info(f"[任务{task_id}] ThreadPool生成2FA代码: {tfa_code}")
            
            # 查找2FA输入框并输入
            tfa_input = u2_d.xpath('//*[@resource-id="com.twitter.android:id/text_field"]//android.widget.FrameLayout')
            if tfa_input.exists:
                tfa_input.click()
                time.sleep(1)
                
                # 输入2FA代码
                self._thread_send_text_char_by_char(mytapi, tfa_code)
                
                # 点击Next按钮
                next_button = u2_d(text="Next")
                if next_button.exists:
                    next_button.click()
                    time.sleep(5)
                
                return True
            else:
                logger.error(f"[任务{task_id}] ❌ ThreadPool未找到2FA输入框")
                return False
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool 2FA处理异常: {e}")
            return False
    
    def _thread_verify_login_success(self, u2_d, task_id: int, username: str = None, device_ip: str = None) -> bool:
        """ThreadPool版本的登录验证（增强版：包含Update、广告和封号检测）"""
        try:
            logger.info(f"[任务{task_id}] 🔍 ThreadPool开始增强版登录验证: {username}")
            
            # 等待页面初始加载
            time.sleep(5)
            
            # 🚀 **步骤1：处理可能的Update弹窗**
            logger.info(f"[任务{task_id}] 📱 ThreadPool检查Update弹窗...")
            self._thread_handle_update_dialog(u2_d, task_id)
            
            # 🚀 **步骤2：处理可能的广告弹窗**
            logger.info(f"[任务{task_id}] 📢 ThreadPool检查广告弹窗...")
            self._thread_handle_ads_dialog(u2_d, task_id)
            
            # 🚀 **步骤3：检查账号封号状态**
            logger.info(f"[任务{task_id}] 🚫 ThreadPool检查封号状态...")
            if self._thread_check_suspension(u2_d, task_id, username, device_ip):
                logger.error(f"[任务{task_id}] ❌ ThreadPool检测到账号封号: {username}")
                return False
            
            # 🚀 **步骤4：处理其他模态弹窗**
            logger.info(f"[任务{task_id}] 🪟 ThreadPool处理其他弹窗...")
            self._thread_handle_modal_dialogs(u2_d, task_id)
            
            # 等待页面稳定
            time.sleep(3)
            
            # 🚀 **步骤5：增强的登录成功检测**
            logger.info(f"[任务{task_id}] ✅ ThreadPool进行最终登录状态验证...")
            
            # 检查登录成功的指标（多层检测）
            success_indicators = [
                # 主要指标（权重高）
                {'xpath': '//*[@content-desc="Show navigation drawer"]', 'name': '导航抽屉', 'weight': 10},
                {'xpath': '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]', 'name': '底部导航栏', 'weight': 10},
                {'xpath': '//*[@content-desc="Home Tab"]', 'name': '主页标签', 'weight': 9},
                {'xpath': '//*[@resource-id="com.twitter.android:id/timeline"]', 'name': '时间线', 'weight': 9},
                
                # 次要指标（权重中）
                {'xpath': '//*[@content-desc="Search and Explore"]', 'name': '搜索按钮', 'weight': 7},
                {'xpath': '//*[@resource-id="com.twitter.android:id/composer_write"]', 'name': '发推按钮', 'weight': 7},
                {'xpath': '//*[@resource-id="com.twitter.android:id/tweet_button"]', 'name': '发推浮动按钮', 'weight': 6},
                
                # 辅助指标（权重低）
                {'xpath': '//*[@content-desc="Notifications"]', 'name': '通知按钮', 'weight': 5},
                {'xpath': '//*[@content-desc="Messages"]', 'name': '消息按钮', 'weight': 5},
                {'xpath': '//*[@resource-id="com.twitter.android:id/channels"]', 'name': '频道区域', 'weight': 4},
            ]
            
            found_indicators = []
            total_score = 0
            
            for indicator in success_indicators:
                try:
                    if u2_d.xpath(indicator['xpath']).exists:
                        found_indicators.append(indicator['name'])
                        total_score += indicator['weight']
                        logger.info(f"[任务{task_id}] ✅ ThreadPool发现登录指标: {indicator['name']} (权重: {indicator['weight']})")
                except Exception:
                    continue
            
            # 登录成功判定：总分≥15分且至少有2个指标
            login_success = total_score >= 15 and len(found_indicators) >= 2
            
            if login_success:
                logger.info(f"[任务{task_id}] ✅ ThreadPool登录验证成功: {username} (总分: {total_score}, 指标数: {len(found_indicators)})")
                logger.info(f"[任务{task_id}] 📋 ThreadPool发现的指标: {', '.join(found_indicators)}")
                return True
            
            # 🚀 **步骤6：如果第一次检查失败，进行深度检查**
            logger.info(f"[任务{task_id}] ⏳ ThreadPool第一次检查未成功，进行深度验证...")
            
            # 检查是否在登录页面（失败指标）
            login_page_indicators = [
                '//*[@text="Log in"]',
                '//*[@text="登录"]', 
                '//*[@text="Sign in"]',
                '//*[@text="Create account"]',
                '//*[@text="Phone, email, or username"]',
                '//*[@text="手机、邮箱或用户名"]',
                '//*[@text="Password"]',
                '//*[@text="密码"]'
            ]
            
            on_login_page = False
            for login_indicator in login_page_indicators:
                try:
                    if u2_d.xpath(login_indicator).exists:
                        logger.warning(f"[任务{task_id}] ❌ ThreadPool检测到登录页面指标: {login_indicator}")
                        on_login_page = True
                        break
                except Exception:
                    continue
            
            if on_login_page:
                logger.error(f"[任务{task_id}] ❌ ThreadPool用户需要重新登录: {username}")
                return False
            
            # 等待更长时间后重新检查
            logger.info(f"[任务{task_id}] ⏳ ThreadPool等待10秒后重新检查...")
            time.sleep(10)
            
            # 重新处理可能的弹窗
            self._thread_handle_update_dialog(u2_d, task_id)
            self._thread_handle_ads_dialog(u2_d, task_id)
            self._thread_handle_modal_dialogs(u2_d, task_id)
            
            # 再次检查登录指标
            found_indicators_retry = []
            total_score_retry = 0
            
            for indicator in success_indicators:
                try:
                    if u2_d.xpath(indicator['xpath']).exists:
                        found_indicators_retry.append(indicator['name'])
                        total_score_retry += indicator['weight']
                        logger.info(f"[任务{task_id}] ✅ ThreadPool重试发现登录指标: {indicator['name']}")
                except Exception:
                    continue
            
            # 重试的成功判定（稍微放宽标准）
            login_success_retry = total_score_retry >= 10 and len(found_indicators_retry) >= 1
            
            if login_success_retry:
                logger.info(f"[任务{task_id}] ✅ ThreadPool重试登录验证成功: {username} (总分: {total_score_retry}, 指标数: {len(found_indicators_retry)})")
                return True
            
            logger.error(f"[任务{task_id}] ❌ ThreadPool登录验证最终失败: {username} (重试总分: {total_score_retry}, 指标数: {len(found_indicators_retry)})")
            return False
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool验证登录状态异常: {e}")
            return False
    
    def _thread_handle_update_dialog(self, u2_d, task_id: int) -> None:
        """ThreadPool版本的Update弹窗处理"""
        try:
            # 检查各种Update弹窗
            update_indicators = [
                {'xpath': '//*[@text="Update now"]', 'name': '立即更新'},
                {'xpath': '//*[@text="Update"]', 'name': '更新'},
                {'xpath': '//*[contains(@text, "update") or contains(@text, "Update")]', 'name': '包含update的文本'}
            ]
            
            for indicator in update_indicators:
                try:
                    if u2_d.xpath(indicator['xpath']).exists:
                        logger.info(f"[任务{task_id}] 📱 ThreadPool检测到Update弹窗: {indicator['name']}")
                        
                        # 尝试关闭弹窗的多种方式
                        close_buttons = [
                            '//*[@text="Not now"]',
                            '//*[@text="稍后"]',
                            '//*[@text="Later"]',
                            '//*[@text="Skip"]',
                            '//*[@text="跳过"]',
                            '//*[@content-desc="Close"]',
                            '//*[@content-desc="关闭"]',
                            '//*[@content-desc="Dismiss"]'
                        ]
                        
                        closed = False
                        for close_btn in close_buttons:
                            try:
                                if u2_d.xpath(close_btn).click_exists(timeout=2):
                                    logger.info(f"[任务{task_id}] ✅ ThreadPool已关闭Update弹窗: {close_btn}")
                                    closed = True
                                    time.sleep(2)
                                    break
                            except Exception:
                                continue
                        
                        if not closed:
                            # 如果无法关闭弹窗，重启应用
                            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool无法关闭Update弹窗，重启应用...")
                            u2_d.app_stop("com.twitter.android")
                            time.sleep(3)
                            u2_d.app_start("com.twitter.android")
                            time.sleep(8)
                        
                        break  # 处理一个就够了
                except Exception:
                    continue
                    
        except Exception as e:
            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool处理Update弹窗异常: {e}")
    
    def _thread_handle_ads_dialog(self, u2_d, task_id: int) -> None:
        """ThreadPool版本的广告弹窗处理"""
        try:
            # 检查各种广告相关弹窗
            ads_indicators = [
                {'xpath': '//*[@text="Keep less relevant ads"]', 'name': '保留不太相关的广告'},
                {'xpath': '//*[@text="See fewer ads like this"]', 'name': '减少此类广告'},
                {'xpath': '//*[contains(@text, "ads") or contains(@text, "Ads")]', 'name': '包含ads的文本'},
                {'xpath': '//*[contains(@text, "广告")]', 'name': '包含广告的文本'}
            ]
            
            for indicator in ads_indicators:
                try:
                    if u2_d.xpath(indicator['xpath']).exists:
                        logger.info(f"[任务{task_id}] 📢 ThreadPool检测到广告弹窗: {indicator['name']}")
                        
                        # 尝试点击广告选项或关闭
                        if u2_d.xpath(indicator['xpath']).click_exists(timeout=2):
                            logger.info(f"[任务{task_id}] ✅ ThreadPool已处理广告弹窗: {indicator['name']}")
                            time.sleep(2)
                            break
                except Exception:
                    continue
                    
        except Exception as e:
            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool处理广告弹窗异常: {e}")
    
    def _thread_check_suspension(self, u2_d, task_id: int, username: str = None, device_ip: str = None) -> bool:
        """ThreadPool版本的封号检测"""
        try:
            # 检查封号相关指标
            suspension_indicators = [
                {'xpath': '//*[@resource-id="com.twitter.android:id/alertTitle"]', 'name': '警告标题'},
                {'xpath': '//*[contains(@text, "Suspended") or contains(@text, "suspended")]', 'name': '包含Suspended的文本'},
                {'xpath': '//*[contains(@text, "封停") or contains(@text, "封号")]', 'name': '包含封停的文本'},
                {'xpath': '//*[contains(@text, "违反") or contains(@text, "violation")]', 'name': '违反规则相关文本'}
            ]
            
            for indicator in suspension_indicators:
                try:
                    element = u2_d.xpath(indicator['xpath'])
                    if element.exists:
                        alert_text = element.get_text() if hasattr(element, 'get_text') else "检测到封号指标"
                        logger.warning(f"[任务{task_id}] 🚫 ThreadPool检测到封号指标: {indicator['name']} - {alert_text}")
                        
                        # 如果检测到封号，尝试更新数据库
                        if username and ("Suspended" in alert_text or "suspended" in alert_text or "封停" in alert_text):
                            logger.warning(f"[任务{task_id}] 📝 ThreadPool准备更新封号数据库: {username}")
                            try:
                                # 调用同步版本的数据库更新
                                self._thread_update_suspension_database(username, alert_text, task_id)
                            except Exception as db_e:
                                logger.error(f"[任务{task_id}] ❌ ThreadPool更新封号数据库失败: {db_e}")
                            
                            return True  # 确认封号
                except Exception:
                    continue
            
            return False  # 未检测到封号
            
        except Exception as e:
            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool检查封号状态异常: {e}")
            return False
    
    def _thread_handle_modal_dialogs(self, u2_d, task_id: int) -> None:
        """ThreadPool版本的通用模态弹窗处理"""
        try:
            # 通用弹窗关闭按钮
            modal_buttons = [
                '//*[@text="Got it"]',
                '//*[@text="知道了"]',
                '//*[@text="OK"]',
                '//*[@text="确定"]', 
                '//*[@text="Continue"]',
                '//*[@text="继续"]',
                '//*[@text="Dismiss"]',
                '//*[@text="关闭"]',
                '//*[@content-desc="Dismiss"]',
                '//*[@content-desc="关闭"]',
                '//*[@resource-id="com.twitter.android:id/dismiss_button"]',
                '//*[@text="Allow"]',
                '//*[@text="允许"]',
                '//*[@text="Not now"]',
                '//*[@text="稍后"]',
                '//*[@text="Skip"]',
                '//*[@text="跳过"]'
            ]
            
            for button in modal_buttons:
                try:
                    if u2_d.xpath(button).click_exists(timeout=1):
                        logger.info(f"[任务{task_id}] ✅ ThreadPool关闭模态弹窗: {button}")
                        time.sleep(1)
                except Exception:
                    continue
                    
        except Exception as e:
            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool处理模态弹窗异常: {e}")
    
    def _thread_update_suspension_database(self, username: str, reason: str, task_id: int) -> None:
        """ThreadPool版本的同步封号数据库更新"""
        try:
            logger.info(f"[任务{task_id}] 📝 ThreadPool开始更新封号数据库: {username} - {reason}")
            
            # 直接使用数据库处理器的方法
            if hasattr(self, 'database_handler') and self.database_handler:
                success = self.database_handler.add_suspended_account(username, reason)
                if success:
                    logger.info(f"[任务{task_id}] ✅ ThreadPool封号数据库更新成功: {username}")
                    
                    # 同时更新账号状态为封号
                    status_updated = self.database_handler.update_account_status(username, "suspended")
                    if status_updated:
                        logger.info(f"[任务{task_id}] ✅ ThreadPool账号状态更新为封号: {username}")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ ThreadPool账号状态更新失败: {username}")
                else:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool封号数据库更新失败: {username}")
            else:
                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool数据库处理器不可用")
                
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool更新封号数据库异常: {username} - {e}")
    
    def _thread_send_text_char_by_char(self, mytapi, text: str, char_delay=0.15):
        """ThreadPool版本的逐字符发送文本（基于batch_login_test.py）"""
        try:
            for char in text:
                if not mytapi.sendText(char):
                    return False
                time.sleep(char_delay)
            time.sleep(1)
            return True
        except Exception as e:
            return False
    
    def _sync_export_account_backup(self, device_ip: str, container_name: str, username: str, task_id: int) -> bool:
        """同步版本的账号备份导出（在ThreadPool中使用）"""
        try:
            logger.info(f"[任务{task_id}] 💾 ThreadPool开始导出账号备份: {username} (容器: {container_name})")
            
            # 生成正确的备份文件名格式
            backup_filename = f"{username}.tar.gz"
            backup_dir = "D:/mytBackUp"
            backup_path = f"{backup_dir}/{backup_filename}"
            
            # 确保备份目录存在
            os.makedirs(backup_dir, exist_ok=True)
            
            # 调用备份API
            backup_url = f"http://127.0.0.1:5000/dc_api/v1/batch_export/{device_ip}"
            backup_params = {
                'names': container_name,
                'locals': backup_path
            }
            
            logger.info(f"[任务{task_id}] 📡 ThreadPool调用备份API: {backup_url}")
            
            response = requests.get(backup_url, params=backup_params, timeout=300)
            
            if response.status_code == 200:
                response_data = response.json()
                
                # 兼容多种API响应格式
                success = response_data.get('success', False)
                if isinstance(response_data, str) and response_data.lower() == 'success':
                    success = True
                if not success and response_data.get('code') == 200:
                    success = True
                
                # 优先以文件存在为准
                file_exists = os.path.exists(backup_path)
                if file_exists:
                    file_size = os.path.getsize(backup_path)
                    if file_size > 1000:
                        logger.info(f"[任务{task_id}] ✅ ThreadPool备份文件验证成功: {backup_path} ({file_size} 字节)")
                        return True
                    elif success:
                        logger.warning(f"[任务{task_id}] ⚠️ ThreadPool备份文件过小但API成功: {file_size} 字节")
                        return True
                
                if not file_exists and success:
                    # 延迟检查
                    time.sleep(1)
                    if os.path.exists(backup_path):
                        file_size = os.path.getsize(backup_path)
                        logger.info(f"[任务{task_id}] ✅ ThreadPool延迟检查发现备份文件: {backup_path} ({file_size} 字节)")
                        return True
                
                logger.error(f"[任务{task_id}] ❌ ThreadPool备份验证失败: file_exists={file_exists}, api_success={success}")
                return False
            else:
                logger.error(f"[任务{task_id}] ❌ ThreadPool备份API请求失败: 状态码{response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool备份异常: {username} - {e}")
            return False
    
    async def _batch_cleanup(self, final_results: List[Dict[str, Any]], device_ip: str) -> None:
        """批量清理容器 - 确保所有容器都被清理"""
        cleanup_count = 0
        total_containers = 0
        
        for result in final_results:
            # 🔧 **关键修复：清理时也要检查取消状态**
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务已被取消，但继续清理容器以避免资源泄露")
                # 即使任务被取消，也要清理容器以避免资源泄露
            
            # 🔧 **重要修复：只要有容器名称就尝试清理，不管导入是否成功**
            container_name = result.get('container_name')
            if container_name:
                total_containers += 1
                try:
                    logger.info(f"[任务{self.task_manager.task_id}] 🗑️ 清理容器: {container_name}")
                    success = await self.device_manager.cleanup_container(
                        device_ip, container_name, self.task_manager.task_id
                    )
                    if success:
                        cleanup_count += 1
                        logger.info(f"[任务{self.task_manager.task_id}] ✅ 容器清理成功: {container_name}")
                    else:
                        logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 容器清理失败: {container_name}")
                
                except Exception as e:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 清理容器异常: {container_name} - {e}")
        
        if total_containers > 0:
            self.task_manager.status_callback(f"🗑️ 容器清理完成: {cleanup_count}/{total_containers} 成功")
        else:
            self.task_manager.status_callback("ℹ️ 没有容器需要清理")
    
    async def _wait_with_cancellation_check(self, seconds: int, description: str = "") -> bool:
        """
        带取消检查的等待函数
        
        Args:
            seconds: 等待秒数
            description: 等待描述
            
        Returns:
            bool: 是否成功等待（False表示被取消）
        """
        try:
            interval = min(2, seconds)  # 每2秒检查一次取消状态
            total_waited = 0
            
            while total_waited < seconds:
                # 检查是否被取消
                if self.task_manager.check_if_cancelled():
                    logger.info(f"[任务{self.task_manager.task_id}] ❌ 等待期间任务被取消: {description}")
                    return False
                
                # 等待一个间隔
                current_wait = min(interval, seconds - total_waited)
                await asyncio.sleep(current_wait)
                total_waited += current_wait
                
                # 更新状态
                if description:
                    remaining = seconds - total_waited
                    self.task_manager.status_callback(f"{description} (剩余: {remaining:.0f}s)")
            
            return True
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 等待异常: {e}")
            return False
    async def _print_final_task_summary(self, all_results: List[Dict[str, Any]]) -> None:
        """
        🚀 **新增功能：打印最终任务总结统计**
        
        Args:
            all_results: 所有账号的处理结果
        """
        try:
            logger.info(f"[任务{self.task_manager.task_id}] 📊 开始生成最终任务总结...")
            
            # 分类统计账号
            successful_accounts = []       # 登录+备份都成功的账号
            login_only_accounts = []      # 仅登录成功的账号  
            failed_accounts = []          # 登录失败的账号
            suspended_accounts = []       # 封号的账号
            error_accounts = []           # 处理异常的账号
            
            for result in all_results:
                if not result or 'account' not in result:
                    continue
                    
                account = result['account']
                username = account.get('username', 'Unknown')
                
                # 根据不同状态分类
                if result.get('is_suspended', False):
                    # 封号账号
                    suspended_accounts.append({
                        'username': username,
                        'reason': result.get('suspension_reason', '检测到封号')
                    })
                elif result.get('success', False) and result.get('login_success', False) and result.get('backup_success', False):
                    # 完全成功：登录+备份
                    successful_accounts.append(username)
                elif result.get('login_success', False) and not result.get('backup_success', False):
                    # 仅登录成功，备份失败
                    login_only_accounts.append({
                        'username': username,
                        'backup_error': result.get('message', '备份失败')
                    })
                elif not result.get('login_success', False):
                    # 登录失败
                    failed_accounts.append({
                        'username': username,
                        'error': result.get('message', '登录失败')
                    })
                else:
                    # 其他异常情况
                    error_accounts.append({
                        'username': username,
                        'error': result.get('message', '处理异常')
                    })
            
            # 🎯 **核心功能：打印详细统计报告**
            total_processed = len(all_results)
            
            # 标题分隔线
            separator = "━" * 80
            logger.info(f"\n{separator}")
            logger.info(f"🏁 [任务{self.task_manager.task_id}] 批量登录备份任务 - 最终统计报告")
            logger.info(f"{separator}")
            
            # 总体统计
            logger.info(f"📊 总体统计:")
            logger.info(f"   📋 总处理账号数: {total_processed}")
            logger.info(f"   ✅ 完全成功账号: {len(successful_accounts)} ({len(successful_accounts)/total_processed*100:.1f}%)" if total_processed > 0 else "   ✅ 完全成功账号: 0")
            logger.info(f"   🔐 仅登录成功账号: {len(login_only_accounts)} ({len(login_only_accounts)/total_processed*100:.1f}%)" if total_processed > 0 else "   🔐 仅登录成功账号: 0")
            logger.info(f"   🚫 封号账号: {len(suspended_accounts)} ({len(suspended_accounts)/total_processed*100:.1f}%)" if total_processed > 0 else "   🚫 封号账号: 0")
            logger.info(f"   ❌ 登录失败账号: {len(failed_accounts)} ({len(failed_accounts)/total_processed*100:.1f}%)" if total_processed > 0 else "   ❌ 登录失败账号: 0")
            logger.info(f"   ⚠️ 异常处理账号: {len(error_accounts)} ({len(error_accounts)/total_processed*100:.1f}%)" if total_processed > 0 else "   ⚠️ 异常处理账号: 0")
            
            # 🎉 成功账号详情
            if successful_accounts:
                logger.info(f"\n✅ 成功账号列表 ({len(successful_accounts)}个):")
                for i, username in enumerate(successful_accounts, 1):
                    logger.info(f"   {i:2d}. {username}")
            
            # 🚫 封号账号详情  
            if suspended_accounts:
                logger.info(f"\n🚫 封号账号列表 ({len(suspended_accounts)}个):")
                for i, account_info in enumerate(suspended_accounts, 1):
                    username = account_info['username']
                    reason = account_info['reason']
                    logger.info(f"   {i:2d}. {username} - {reason}")
            
            # 🔐 仅登录成功账号详情
            if login_only_accounts:
                logger.info(f"\n🔐 仅登录成功账号列表 ({len(login_only_accounts)}个):")
                for i, account_info in enumerate(login_only_accounts, 1):
                    username = account_info['username']
                    error = account_info['backup_error']
                    logger.info(f"   {i:2d}. {username} - 备份失败: {error}")
            
            # ❌ 失败账号详情
            if failed_accounts:
                logger.info(f"\n❌ 登录失败账号列表 ({len(failed_accounts)}个):")
                for i, account_info in enumerate(failed_accounts, 1):
                    username = account_info['username']
                    error = account_info['error']
                    logger.info(f"   {i:2d}. {username} - {error}")
            
            # ⚠️ 异常账号详情
            if error_accounts:
                logger.info(f"\n⚠️ 异常处理账号列表 ({len(error_accounts)}个):")
                for i, account_info in enumerate(error_accounts, 1):
                    username = account_info['username']
                    error = account_info['error']
                    logger.info(f"   {i:2d}. {username} - {error}")
            
            # 性能统计
            if hasattr(self.task_manager, 'start_time'):
                total_duration = time.time() - self.task_manager.start_time
                avg_time_per_account = total_duration / total_processed if total_processed > 0 else 0
                logger.info(f"\n⚡ 性能统计:")
                logger.info(f"   🕒 总耗时: {total_duration:.1f} 秒")
                logger.info(f"   📈 平均每账号: {avg_time_per_account:.1f} 秒")
            
            # 结束分隔线
            logger.info(f"{separator}")
            logger.info(f"🎯 [任务{self.task_manager.task_id}] 批量登录备份任务统计报告完成")
            logger.info(f"{separator}\n")
            
            # 🚀 **同时发送给状态回调（前端显示）**
            summary_message = (
                f"📊 任务总结: 总数{total_processed} | "
                f"✅成功{len(successful_accounts)} | "
                f"🚫封号{len(suspended_accounts)} | "
                f"❌失败{len(failed_accounts)} | "
                f"⚠️异常{len(error_accounts)}"
            )
            self.task_manager.status_callback(summary_message)
            
            # 详细成功和封号列表发送给前端
            if successful_accounts:
                success_list = ", ".join(successful_accounts[:10])  # 最多显示10个
                if len(successful_accounts) > 10:
                    success_list += f" 等{len(successful_accounts)}个"
                self.task_manager.status_callback(f"✅ 成功账号: {success_list}")
            
            if suspended_accounts:
                suspended_list = ", ".join([acc['username'] for acc in suspended_accounts[:10]])  # 最多显示10个
                if len(suspended_accounts) > 10:
                    suspended_list += f" 等{len(suspended_accounts)}个"
                self.task_manager.status_callback(f"🚫 封号账号: {suspended_list}")
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 生成任务总结异常: {e}", exc_info=True)
