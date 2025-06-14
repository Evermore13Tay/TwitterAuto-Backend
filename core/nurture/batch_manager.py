"""
养号批次管理模块
负责处理批次创建、管理等功能
"""

import logging
from typing import List, Dict, Any, Callable

try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class NurtureBatchManager:
    """养号批次管理器"""
    
    def __init__(self, config_manager, status_callback: Callable[[str], None] = None):
        self.config_manager = config_manager
        self.status_callback = status_callback or (lambda x: logger.info(x))
    
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
                    'container_name': self.config_manager.generate_random_container_name(account['username'])
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