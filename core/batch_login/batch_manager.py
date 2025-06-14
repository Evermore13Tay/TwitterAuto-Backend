"""
批量管理器 - 核心批量管理器，整合所有子模块
"""

import asyncio
import logging
import concurrent.futures
import time
import os
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

from .login_handler import BatchLoginHandler
from .backup_handler import BatchBackupHandler
from .batch_operations import BatchOperationsHandler

logger = logging.getLogger("TwitterAutomationAPI")

class BatchManager:
    """批量管理器核心类"""
    
    def __init__(self, task_manager, device_manager, account_manager, database_handler):
        self.task_manager = task_manager
        self.device_manager = device_manager
        self.account_manager = account_manager
        self.database_handler = database_handler
        
        # 初始化子处理器
        self.login_handler = BatchLoginHandler(database_handler)
        self.backup_handler = BatchBackupHandler()
        self.operations_handler = BatchOperationsHandler(task_manager, device_manager)
        
        # 批量处理配置 - 默认值，会被任务参数覆盖
        self.accounts_per_batch = 10
        self.import_interval = 3
        self.import_wait_time = 15
        self.reboot_interval = 1
        self.reboot_wait_time = 165  # 默认值，会被任务参数覆盖
        
        # 高效并发登录配置
        self.efficient_login_mode = True
        self.login_base_stagger = 2
        self.login_random_variance = 3
        self.login_timeout = 180
        self.suspension_check_timeout = 20
        self.backup_timeout = 180
        self.max_concurrent_logins = 10
    
    def configure_login_mode(self, mode: str = "efficient"):
        """
        配置登录模式
        
        Args:
            mode: "efficient" 高效模式 或 "conservative" 保守模式
        """
        if mode == "efficient":
            # 高效模式：最大化并发效率
            self.efficient_login_mode = True
            self.login_base_stagger = 2
            self.login_random_variance = 1.5
            self.login_timeout = 120
            self.suspension_check_timeout = 20
            self.backup_timeout = 120
            logger.info("✅ 已切换到高效登录模式：2秒错峰 + 1.5秒随机延迟")
            
        elif mode == "conservative": 
            # 保守模式：优先稳定性
            self.efficient_login_mode = False
            self.login_base_stagger = 8
            self.login_random_variance = 5
            self.login_timeout = 300
            self.suspension_check_timeout = 60
            self.backup_timeout = 300
            logger.info("🛡️ 已切换到保守登录模式：8秒错峰 + 5秒随机延迟")
            
        elif mode == "ultra_fast":
            # 极速模式：极致效率（适合测试环境）
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
            
            # 应用用户设置的等待时间
            self.reboot_wait_time = wait_time
            self.operations_handler.set_wait_time(wait_time)
            self.task_manager.status_callback(f"✅ 应用用户设置的重启等待时间: {wait_time}秒")
            
            # 关键修复：强化取消检查
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
            
            # 初始化统计数据
            total_accounts_processed = []
            
            # 逐批次处理
            successful_accounts = []
            for batch_num, current_batch in enumerate(account_batches):
                # 关键修复：每个批次开始时检查取消状态
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
                
                # 关键修复：每个批次完成后立即检查取消状态
                if self.task_manager.check_if_cancelled():
                    self.task_manager.status_callback(f"任务在第{batch_num+1}批次完成后被取消")
                    return False
                
                successful_accounts.extend(batch_results)
                
                # 收集所有处理过的账号用于最终统计
                for result in batch_results:
                    if result and 'account' in result:
                        total_accounts_processed.append(result)
                
                # 关键修复：批次间短暂暂停，给取消检查更多机会
                if batch_num < len(account_batches) - 1:  # 不是最后一个批次
                    await asyncio.sleep(0.5)  # 短暂暂停0.5秒
                    if self.task_manager.check_if_cancelled():
                        self.task_manager.status_callback(f"任务在批次间隔时被取消")
                        return False
            
            # 新增功能：最终任务总结打印
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
            
            # 修复：统一前后端等待时间计算逻辑
            base_wait_time = 60
            additional_time_per_slot = 35  # 与前端保持一致
            recommended_wait_time = base_wait_time + (len(instance_slots) - 1) * additional_time_per_slot
            
            # 修复：只在用户设置时间过低时调整，否则尊重用户设置
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
        
        # 关键修复：按轮次创建批次，确保每批次包含所有实例位的账号
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
            
            # 关键修复：每个阶段前检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在批次处理开始时被取消")
                return []
            
            # 阶段1：批量导入
            import_results = await self.operations_handler.batch_import(batch, device_ip, pure_backup_file)
            
            # 关键修复：导入后检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在导入阶段后被取消")
                return []
            
            # 阶段2：批量重启
            reboot_results = await self.operations_handler.batch_reboot(import_results, device_ip)
            
            # 关键修复：重启后检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在重启阶段后被取消")
                return []
            
            # 阶段3：批量设置代理和语言
            setup_results = await self.operations_handler.batch_setup_proxy_language(reboot_results, device_ip, self.database_handler)
            
            # 关键修复：设置后检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在代理设置阶段后被取消")
                return []
            
            # 阶段4：批量登录和备份
            final_results = await self._batch_login_backup(setup_results, device_ip)
            
            # 关键修复：登录备份后检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务在登录备份阶段后被取消")
                return []
            
            # 阶段5：清理容器
            await self.operations_handler.batch_cleanup(final_results, device_ip)
            
            successful_accounts = [result for result in final_results if result.get('success')]
            self.task_manager.status_callback(f"✅ 批次 {batch_num} 完成，成功 {len(successful_accounts)} 个账号")
            
            return successful_accounts
            
        except Exception as e:
            logger.error(f"处理批次异常: {e}", exc_info=True)
            return []
    
    async def _batch_login_backup(self, setup_results: List[Dict[str, Any]], device_ip: str) -> List[Dict[str, Any]]:
        """批量登录和备份 - 真正并发版本"""
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
            
            # 革命性优化：真正的ThreadPoolExecutor并发登录，串行备份
            # 策略1：预先分配端口，避免运行时争抢
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
            
            # 策略2：真正的并发登录执行 - 借鉴batch_login_test.py的ThreadPoolExecutor
            # 关键修复：使用ThreadPoolExecutor绕过MytRpc全局连接锁，备份采用串行避免I/O瓶颈
            logger.info(f"[任务{self.task_manager.task_id}] 🎯 启用ThreadPoolExecutor并发登录+串行备份模式")
            self.task_manager.status_callback(f"🎯 混合策略：{len(valid_results)}个账号并发登录→串行备份")
            
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
            
            # 策略3：ThreadPoolExecutor真正并发登录执行
            all_final_results = []
            success_count = 0
            
            self.task_manager.status_callback(f"⚡ 启动ThreadPoolExecutor并发登录 - {len(login_tasks)}个账号（备份将串行执行）")
            
            # 关键：使用ThreadPoolExecutor实现真正并发
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
                        # 关键修复：检查任务取消状态
                        if self.task_manager.check_if_cancelled():
                            logger.info(f"[任务{self.task_manager.task_id}] ❌ 任务已取消，停止收集结果")
                            self.task_manager.status_callback("任务已取消，停止执行")
                            break
                        
                        result = future.result()
                        # 修复：确保所有结果都被收集，无论成功还是失败
                        if result is not None:
                            all_final_results.append(result)
                            if result.get('success', False):
                                success_count += 1
                                logger.info(f"[任务{self.task_manager.task_id}] ✅ ThreadPool任务完成: {username}")
                            else:
                                logger.warning(f"[任务{self.task_manager.task_id}] ❌ ThreadPool任务失败: {username} - {result.get('message', 'Unknown error')}")
                            
                            # 调试日志：确认结果收集
                            logger.info(f"[任务{self.task_manager.task_id}] 📊 收集结果: {username} - success={result.get('success', False)}, login_success={result.get('login_success', False)}")
                        else:
                            logger.error(f"[任务{self.task_manager.task_id}] ❌ ThreadPool返回空结果: {username}")
                            # 为空结果创建失败记录
                            error_result = {
                                'account': task_config['account'],
                                'slot_num': task_config['slot_num'],
                                'success': False,
                                'message': 'ThreadPool返回空结果',
                                'login_success': False,
                                'backup_success': False
                            }
                            all_final_results.append(error_result)
                        
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
            
            # 关键修复：串行备份导出，避免磁盘I/O瓶颈
            logger.info(f"[任务{self.task_manager.task_id}] 💾 开始串行备份导出（避免性能爆炸）")
            self.task_manager.status_callback("💾 开始串行备份导出...")
            
            backup_start_time = time.time()
            backup_success_count = 0
            
            for result in all_final_results:
                # 只为登录成功的账号执行备份
                if not result.get('success', False) or not result.get('login_success', False):
                    result['backup_success'] = False
                    continue
                
                # 检查任务取消状态
                if self.task_manager.check_if_cancelled():
                    logger.info(f"[任务{self.task_manager.task_id}] ❌ 任务已取消，停止备份导出")
                    break
                
                account = result['account']
                username = account['username']
                slot_num = result['slot_num']
                container_name = result.get('container_name', f"twitter_{slot_num}")
                
                logger.info(f"[任务{self.task_manager.task_id}] 💾 串行备份导出: {username}")
                
                try:
                    backup_success = self.backup_handler.sync_export_account_backup(
                        device_ip, container_name, username, self.task_manager.task_id
                    )
                    
                    result['backup_success'] = backup_success
                    
                    if backup_success:
                        backup_success_count += 1
                        logger.info(f"[任务{self.task_manager.task_id}] ✅ 串行备份导出成功: {username}")
                        
                        # 更新数据库备份状态
                        if account.get('id'):
                            update_success = self.database_handler.update_account_backup_status(account['id'], 1)
                            if update_success:
                                logger.info(f"[任务{self.task_manager.task_id}] ✅ 数据库备份状态更新成功: {username}")
                            else:
                                logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 数据库备份状态更新失败: {username}")
                        
                        # 更新最终结果状态
                        result['message'] = '登录备份成功'
                    else:
                        logger.warning(f"[任务{self.task_manager.task_id}] ❌ 串行备份导出失败: {username}")
                        result['message'] = '登录成功但备份失败'
                        
                except Exception as backup_error:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 串行备份异常: {username} - {backup_error}")
                    result['backup_success'] = False
                    result['message'] = f'登录成功但备份异常: {backup_error}'
            
            backup_duration = time.time() - backup_start_time
            login_success_count = sum(1 for r in all_final_results if r.get('login_success', False))
            
            self.task_manager.status_callback(
                f"💾 串行备份导出完成: {backup_success_count}/{login_success_count} 成功 "
                f"(耗时: {backup_duration:.1f}s, 平均: {backup_duration/max(login_success_count, 1):.1f}s/账号)"
            )
            logger.info(f"[任务{self.task_manager.task_id}] 💾 串行备份性能: 平均每账号 {backup_duration/max(login_success_count, 1):.1f}s")
            
            return all_final_results
            
        except Exception as e:
            logger.error(f"[任务{self.task_manager.task_id}] ❌ 批量登录备份异常: {e}", exc_info=True)
            return []
    
    def _thread_login_backup_single(self, task_config: Dict[str, Any]) -> Dict[str, Any]:
        """ThreadPoolExecutor单个账号登录（备份将在后续串行执行）"""
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
            
            # 优化1：真正的并发登录（绕过MytRpc全局锁），备份将在ThreadPool外串行执行
            try:
                # 修复版：使用batch_login_test.py验证有效的直接设备连接方法
                login_success = self.login_handler.sync_account_login(
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
            
            # 关键修复：ThreadPool中检查取消状态
            if self.task_manager.check_if_cancelled():
                result['success'] = False
                result['message'] = "任务已取消"
                return result
            
            # 登录成功，标记结果但不在ThreadPool中执行备份
            result['success'] = True
            result['message'] = 'ThreadPool登录成功'
            
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
    
    async def _print_final_task_summary(self, all_results: List[Dict[str, Any]]) -> None:
        """
        新增功能：打印最终任务总结统计
        
        Args:
            all_results: 所有账号的处理结果
        """
        try:
            logger.info(f"[任务{self.task_manager.task_id}] 📊 开始生成最终任务总结...")
            
            # 调试：打印所有结果概览
            logger.info(f"[任务{self.task_manager.task_id}] 🔍 调试 - 收到总结果数: {len(all_results)}")
            for i, result in enumerate(all_results):
                if result and 'account' in result:
                    username = result['account'].get('username', 'Unknown')
                    success = result.get('success', False)
                    login_success = result.get('login_success', False)
                    backup_success = result.get('backup_success', False)
                    message = result.get('message', 'No message')
                    logger.info(f"[任务{self.task_manager.task_id}] 🔍 调试结果 {i+1}: {username} - success={success}, login={login_success}, backup={backup_success}, msg={message}")
                else:
                    logger.warning(f"[任务{self.task_manager.task_id}] 🔍 调试结果 {i+1}: 空结果或缺少account字段")
            
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
            
            # 核心功能：打印详细统计报告
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
            
            # 成功账号详情
            if successful_accounts:
                logger.info(f"\n✅ 成功账号列表 ({len(successful_accounts)}个):")
                for i, username in enumerate(successful_accounts, 1):
                    logger.info(f"   {i:2d}. {username}")
            
            # 封号账号详情  
            if suspended_accounts:
                logger.info(f"\n🚫 封号账号列表 ({len(suspended_accounts)}个):")
                for i, account_info in enumerate(suspended_accounts, 1):
                    username = account_info['username']
                    reason = account_info['reason']
                    logger.info(f"   {i:2d}. {username} - {reason}")
            
            # 仅登录成功账号详情
            if login_only_accounts:
                logger.info(f"\n🔐 仅登录成功账号列表 ({len(login_only_accounts)}个):")
                for i, account_info in enumerate(login_only_accounts, 1):
                    username = account_info['username']
                    error = account_info['backup_error']
                    logger.info(f"   {i:2d}. {username} - 备份失败: {error}")
            
            # 失败账号详情
            if failed_accounts:
                logger.info(f"\n❌ 登录失败账号列表 ({len(failed_accounts)}个):")
                for i, account_info in enumerate(failed_accounts, 1):
                    username = account_info['username']
                    error = account_info['error']
                    logger.info(f"   {i:2d}. {username} - {error}")
            
            # 异常账号详情
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
            
            # 同时发送给状态回调（前端显示）
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