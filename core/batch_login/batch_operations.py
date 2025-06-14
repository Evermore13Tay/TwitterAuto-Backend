"""
批量操作处理器 - 专门处理容器导入、重启、设置等批次操作
"""

import asyncio
import logging
import time
import random
import sys
import os
from typing import Dict, Any, List, Tuple

logger = logging.getLogger("TwitterAutomationAPI")

class BatchOperationsHandler:
    """批量操作处理器"""
    
    def __init__(self, task_manager, device_manager):
        self.task_manager = task_manager
        self.device_manager = device_manager
        
        # 操作配置
        self.import_interval = 3
        self.reboot_interval = 1
        self.reboot_wait_time = 165
    
    def set_wait_time(self, wait_time: int):
        """设置重启等待时间"""
        self.reboot_wait_time = wait_time
    
    async def batch_import(self, batch: List[Tuple[int, Dict[str, Any]]], 
                          device_ip: str, pure_backup_file: str) -> List[Dict[str, Any]]:
        """批量导入纯净备份"""
        results = []
        container_names = []
        slot_numbers = []
        
        # 修复容器名重复问题：每个容器都应该有独立的时间戳
        for i, (slot_num, account) in enumerate(batch):
            slot_numbers.append(slot_num)
            # 每个容器添加独立的随机后缀，避免重复
            unique_suffix = int(time.time() * 1000) + i * 1000 + random.randint(1, 999)
            container_name = f"Pure_{slot_num}_{unique_suffix}"
            container_names.append(container_name)
        
        # 添加冲突设备清理
        self.task_manager.status_callback(f"🧹 检查并清理实例位 {slot_numbers} 的冲突设备...")
        conflict_cleanup_success = await self.device_manager.cleanup_conflict_devices(
            device_ip, slot_numbers, container_names, self.task_manager.task_id
        )
        
        if not conflict_cleanup_success:
            self.task_manager.status_callback("⚠️ 冲突设备清理失败，但继续执行")
        
        for i, (slot_num, account) in enumerate(batch):
            # 关键修复：每个操作前检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务已被取消")
                return results
            
            container_name = container_names[i]
            
            self.task_manager.status_callback(f"📦 导入实例位 {slot_num}: {account['username']}")
            
            import_success = await self.device_manager.import_backup(
                device_ip, slot_num, pure_backup_file, container_name, self.task_manager.task_id
            )
            
            # 取消检查点2：导入后检查
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
    
    async def batch_reboot(self, import_results: List[Dict[str, Any]], device_ip: str) -> List[Dict[str, Any]]:
        """批量重启容器 - 修复：按实例位分批重启"""
        reboot_results = []
        
        # 取消检查点：重启开始前
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
        
        # 关键修复：按实例位分组重启
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
            
            # 取消检查点：每个实例位重启前
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务已被取消")
                return reboot_results
            
            self.task_manager.status_callback(f"🔄 重启实例位 {slot_num} 的 {len(containers_in_slot)} 个容器...")
            
            # 同实例位的容器可以并发重启
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
            
            # 每个实例位重启后的间隔等待
            if slot_num != max(position_groups.keys()):  # 不是最后一个实例位
                success = await self._wait_with_cancellation_check(self.reboot_interval, f"实例位 {slot_num} 重启间隔")
                if not success:
                    self.task_manager.status_callback("任务在实例位重启间隔期间被取消")
                    return reboot_results
        
        # 所有实例位重启完成后，统一等待重启完成
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
            # 关键修复：直接调用BoxManipulate API，绕过DeviceManager的间隔控制
            try:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                backend_dir = os.path.dirname(os.path.dirname(current_dir))  # 向上两级到backend
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
    
    async def batch_setup_proxy_language(self, reboot_results: List[Dict[str, Any]], 
                                        device_ip: str, database_handler) -> List[Dict[str, Any]]:
        """批量设置代理和语言 - 修复：逐个设置避免并发冲突"""
        try:
            self.task_manager.status_callback("🌐 开始批量设置代理和语言...")
            
            # 调试信息：检查输入数据结构
            logger.info(f"[任务{self.task_manager.task_id}] 📋 收到 {len(reboot_results)} 个重启结果")
            for i, result in enumerate(reboot_results):
                logger.info(f"[任务{self.task_manager.task_id}] 结果 {i+1}: 字段={list(result.keys())}")
                if 'slot_num' not in result:
                    logger.error(f"[任务{self.task_manager.task_id}] ❌ 缺少 slot_num 字段: {result}")
            
            successful_setups = []
            
            # 关键修复：逐个设置代理和语言，避免并发冲突
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
                proxy_config = database_handler.get_proxy_config_for_account(username)
                
                self.task_manager.status_callback(f"🔧 设置实例位 {slot_num}: {container_name}")
                
                try:
                    # 步骤1：设置代理（带重试）
                    proxy_success = await self.device_manager.set_device_proxy(
                        device_ip, container_name, proxy_config, self.task_manager.task_id
                    )
                    
                    if proxy_success:
                        logger.info(f"[任务{self.task_manager.task_id}] ✅ 实例位 {slot_num} 代理设置成功")
                    else:
                        logger.warning(f"[任务{self.task_manager.task_id}] ⚠️ 实例位 {slot_num} 代理设置失败")
                    
                    # 间隔等待：代理设置后等待5秒
                    await asyncio.sleep(5)
                    
                    # 步骤2：设置语言（带重试）
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
                
                # 实例间隔：每个实例设置完成后等待5秒（除了最后一个）
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
    
    async def batch_cleanup(self, final_results: List[Dict[str, Any]], device_ip: str) -> None:
        """批量清理容器 - 确保所有容器都被清理"""
        cleanup_count = 0
        total_containers = 0
        
        for result in final_results:
            # 关键修复：清理时也要检查取消状态
            if self.task_manager.check_if_cancelled():
                self.task_manager.status_callback("任务已被取消，但继续清理容器以避免资源泄露")
                # 即使任务被取消，也要清理容器以避免资源泄露
            
            # 重要修复：只要有容器名称就尝试清理，不管导入是否成功
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
            interval = min(20, seconds)  # 每20秒检查一次取消状态
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