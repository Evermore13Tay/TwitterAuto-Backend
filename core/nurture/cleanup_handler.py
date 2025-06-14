"""
养号清理处理模块
负责处理容器清理相关功能
"""

import logging
from typing import List, Dict, Any, Callable

try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class NurtureCleanupHandler:
    """养号清理处理器"""
    
    def __init__(self, device_manager, task_manager, status_callback: Callable[[str], None] = None):
        self.device_manager = device_manager
        self.task_manager = task_manager
        self.status_callback = status_callback or (lambda x: logger.info(x))
    
    async def batch_cleanup_nurture(self, final_results: List[Dict[str, Any]], device_ip: str) -> None:
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
    
    async def cleanup_container(self, device_ip: str, container_name: str) -> bool:
        """清理容器"""
        try:
            return await self.device_manager.cleanup_container(device_ip, container_name, self.task_manager.task_id)
        except Exception as e:
            logger.error(f"❌ 清理容器异常: {e}")
            return False 