"""
养号账号处理模块
负责处理账号获取、解析、验证等功能
"""

import os
import re
import logging
from typing import List, Dict, Any, Callable

try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class NurtureAccountHandler:
    """养号账号处理器"""
    
    def __init__(self, account_manager, database_handler, status_callback: Callable[[str], None] = None):
        self.account_manager = account_manager
        self.database_handler = database_handler
        self.status_callback = status_callback or (lambda x: logger.info(x))
    
    async def get_accounts(self, task_params: Dict[str, Any]) -> List[Dict[str, Any]]:
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
                    file_accounts = await self.extract_accounts_from_backup(full_backup_path)
                    all_accounts.extend(file_accounts)
                
                if all_accounts:
                    self.status_callback(f"✅ 从 {len(backup_files)} 个备份文件解析到 {len(all_accounts)} 个账号")
                    return all_accounts
                else:
                    self.status_callback("⚠️ 备份文件中未找到账号信息，尝试其他方式获取")
                    
            elif single_backup_file:
                self.status_callback(f"📦 从单个备份文件自动解析账号: {single_backup_file}")
                accounts = await self.extract_accounts_from_backup(single_backup_file)
                
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
    
    async def extract_accounts_from_backup(self, backup_file: str) -> List[Dict[str, Any]]:
        """从备份文件中提取账号信息"""
        try:
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
    
    def find_backup_file_for_account(self, backup_path: str, username: str) -> str:
        """为指定账号找到对应的备份文件"""
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
    
    async def verify_account_status(self, device_manager, device_ip: str, position: int, account: Dict[str, Any], task_id: int) -> bool:
        """验证账号状态 - 修复：允许没有密码的备份账号"""
        try:
            # 获取端口信息 - 修复：使用正确的端口获取方法
            base_port, debug_port = await device_manager.get_container_ports(
                device_ip, position, task_id
            )
            
            # 端口获取失败不影响账号验证（因为账号验证主要检查账号信息本身）
            if not base_port or not debug_port:
                logger.warning(f"[任务{task_id}] ⚠️ 端口获取失败，但继续账号验证")
            
            username = account.get('username', '')
            password = account.get('password', '')
            
            # 修复：只要有用户名就允许继续（备份文件中的账号通常没有密码）
            if username:
                if password:
                    logger.info(f"[任务{task_id}] ✅ 账号验证通过: {username} (完整信息)")
                else:
                    logger.info(f"[任务{task_id}] ✅ 账号验证通过: {username} (仅用户名，来自备份文件)")
                return True
            else:
                logger.warning(f"[任务{task_id}] ⚠️ 账号缺少用户名: {account}")
                return False
                
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 账号验证异常: {e}")
            return False
    
    def sync_verify_account_status(self, device_ip: str, position: int, account: Dict[str, Any], task_id: int) -> bool:
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