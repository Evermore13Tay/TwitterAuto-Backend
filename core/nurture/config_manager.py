"""
养号配置管理模块
负责处理养号任务的配置参数管理、随机延迟、智能间隔控制等功能
"""

import time
import random
import string
import logging
from typing import Dict, Any, Callable

try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class NurtureConfigManager:
    """养号配置管理器"""
    
    def __init__(self, task_manager, status_callback: Callable[[str], None] = None):
        self.task_manager = task_manager
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