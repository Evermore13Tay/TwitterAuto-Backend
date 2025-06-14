"""
批量备份处理器 - 专门处理账号备份相关逻辑
"""

import os
import time
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger("TwitterAutomationAPI")

class BatchBackupHandler:
    """批量备份处理器"""
    
    def __init__(self):
        pass
    
    def sync_export_account_backup(self, device_ip: str, container_name: str, username: str, task_id: int) -> bool:
        """同步版本的账号备份导出（串行执行）"""
        try:
            logger.info(f"[任务{task_id}] 💾 串行开始导出账号备份: {username} (容器: {container_name})")
            
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
            
            logger.info(f"[任务{task_id}] 📡 串行调用备份API: {backup_url}")
            
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
                        logger.info(f"[任务{task_id}] ✅ 串行备份文件验证成功: {backup_path} ({file_size} 字节)")
                        return True
                    elif success:
                        logger.warning(f"[任务{task_id}] ⚠️ 串行备份文件过小但API成功: {file_size} 字节")
                        return True
                
                if not file_exists and success:
                    # 延迟检查
                    time.sleep(1)
                    if os.path.exists(backup_path):
                        file_size = os.path.getsize(backup_path)
                        logger.info(f"[任务{task_id}] ✅ 串行延迟检查发现备份文件: {backup_path} ({file_size} 字节)")
                        return True
                
                logger.error(f"[任务{task_id}] ❌ 串行备份验证失败: file_exists={file_exists}, api_success={success}")
                return False
            else:
                logger.error(f"[任务{task_id}] ❌ 串行备份API请求失败: 状态码{response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 串行备份异常: {username} - {e}")
            return False 