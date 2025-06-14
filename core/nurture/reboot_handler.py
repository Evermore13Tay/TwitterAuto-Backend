"""
养号重启处理模块
负责处理容器重启相关功能
"""

import asyncio
import logging
from typing import List, Dict, Any, Callable

try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class NurtureRebootHandler:
    """养号重启处理器"""
    
    def __init__(self, device_manager, config_manager, task_manager, status_callback: Callable[[str], None] = None):
        self.device_manager = device_manager
        self.config_manager = config_manager
        self.task_manager = task_manager
        self.status_callback = status_callback or (lambda x: logger.info(x))
    
    async def batch_reboot_nurture(self, import_results: List[Dict[str, Any]], device_ip: str) -> List[Dict[str, Any]]:
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
            reboot_tasks = []
            for result in containers_in_position:
                task = self.reboot_single_nurture_container(device_ip, result)
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
            await self.config_manager.apply_smart_interval('reboot')
        
        # 🔧 **所有实例位重启完成后，统一等待重启完成**
        successful_reboots = len([r for r in reboot_results if r.get('reboot_success')])
        if successful_reboots > 0:
            self.status_callback(f"⏰ 所有实例位重启完成，统一等待 {self.config_manager.reboot_wait_time} 秒...")
            from utils.task_cancellation import sleep_with_cancel_check
            success = await sleep_with_cancel_check(self.task_manager.task_id, self.config_manager.reboot_wait_time, 20.0, "重启统一等待")
            if not success:
                self.status_callback("任务在重启统一等待期间被取消")
                return reboot_results
            self.status_callback(f"✅ 重启等待完成")
        else:
            self.status_callback("⚠️ 没有容器重启成功，跳过等待")
        
        return reboot_results
    
    async def reboot_single_nurture_container(self, device_ip: str, result: Dict[str, Any]) -> Dict[str, Any]:
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