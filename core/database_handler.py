"""
数据库处理核心模块
统一管理数据库连接、查询、更新、线程安全操作等功能
"""

import threading
import queue
import logging
import time
from typing import List, Dict, Any, Optional, Tuple, Callable
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class DatabaseHandler:
    """数据库处理核心类"""
    
    def __init__(self, connection_timeout: int = 20, operation_timeout: int = 10):
        self.connection_timeout = connection_timeout
        self.operation_timeout = operation_timeout
        self.session_local = None
        self.models = {}
        
        # 导入数据库模块
        self._import_database_modules()
    
    def _import_database_modules(self) -> None:
        """导入数据库相关模块"""
        try:
            from db.database import SessionLocal
            from db.models import SocialAccount, Proxy
            from suspended_account import SuspendedAccount
            
            self.session_local = SessionLocal
            self.models = {
                'SocialAccount': SocialAccount,
                'Proxy': Proxy,
                'SuspendedAccount': SuspendedAccount
            }
            logger.info("✅ 数据库模块导入成功")
            
        except ImportError as e:
            logger.error(f"❌ 导入数据库模块失败: {e}")
            
            # 创建占位符
            class MockSessionLocal:
                def __enter__(self):
                    return None
                def __exit__(self, *args):
                    pass
            
            self.session_local = MockSessionLocal
            self.models = {}
    
    @contextmanager
    def get_db_session(self):
        """获取数据库会话的上下文管理器"""
        if not self.session_local:
            logger.error("数据库会话工厂未初始化")
            yield None
            return
        
        db = None
        try:
            db = self.session_local()
            yield db
        except Exception as e:
            if db:
                db.rollback()
            logger.error(f"数据库会话异常: {e}", exc_info=True)
            raise
        finally:
            if db:
                db.close()
    
    def execute_in_thread(self, operation: Callable, *args, **kwargs) -> Any:
        """
        在线程中执行数据库操作
        
        Args:
            operation: 要执行的操作函数
            *args, **kwargs: 操作参数
        
        Returns:
            Any: 操作结果
        """
        result_queue = queue.Queue()
        error_queue = queue.Queue()
        
        def db_operation():
            try:
                result = operation(*args, **kwargs)
                result_queue.put(result)
            except Exception as e:
                error_queue.put(e)
        
        # 启动线程
        db_thread = threading.Thread(target=db_operation)
        db_thread.daemon = True
        db_thread.start()
        db_thread.join(timeout=self.operation_timeout)
        
        # 检查结果
        if not error_queue.empty():
            raise error_queue.get()
        elif not result_queue.empty():
            return result_queue.get()
        else:
            raise TimeoutError(f"数据库操作超时 ({self.operation_timeout}秒)")
    
    def get_accounts_by_group(self, group_id: str, exclude_backed_up: bool = True, exclude_suspended: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        根据分组ID获取账号列表
        
        Args:
            group_id: 分组ID
            exclude_backed_up: 是否排除已备份账号
            exclude_suspended: 是否排除已封号账号
        
        Returns:
            Tuple[List[Dict], Dict]: (账号列表, 统计信息)
        """
        def db_query():
            with self.get_db_session() as db:
                if not db:
                    return [], {}
                
                SocialAccount = self.models.get('SocialAccount')
                SuspendedAccount = self.models.get('SuspendedAccount')
                
                if not SocialAccount:
                    logger.error("SocialAccount模型未找到")
                    return [], {}
                
                # 获取所有该分组的账号
                all_accounts = db.query(SocialAccount).filter(SocialAccount.group_id == group_id).all()
                
                # 获取封号账号列表
                suspended_usernames = set()
                if SuspendedAccount:
                    try:
                        suspended_accounts_records = db.query(SuspendedAccount).all()
                        suspended_usernames = {acc.username for acc in suspended_accounts_records}
                    except Exception as e:
                        logger.warning(f"获取suspended_accounts表失败: {e}")
                
                # 处理账号列表
                valid_accounts = []
                skipped_backed_up = []
                skipped_suspended = []
                
                for acc in all_accounts:
                    is_suspended = (acc.username in suspended_usernames) or (acc.status == 'suspended')
                    
                    if exclude_backed_up and acc.backup_exported == 1:
                        skipped_backed_up.append(acc.username)
                    elif exclude_suspended and is_suspended:
                        skipped_suspended.append(acc.username)
                    elif acc.username and acc.password and acc.secret_key:
                        valid_accounts.append({
                            'id': acc.id,
                            'username': acc.username,
                            'password': acc.password,
                            'secretkey': acc.secret_key,
                            'email': getattr(acc, 'email', ''),
                            'phone': getattr(acc, 'phone', ''),
                            'status': acc.status or 'active',
                            'proxy_id': getattr(acc, 'proxy_id', None),
                            'backup_exported': acc.backup_exported
                        })
                
                # 统计信息
                stats = {
                    'total_accounts': len(all_accounts),
                    'valid_accounts': len(valid_accounts),
                    'skipped_backed_up': len(skipped_backed_up),
                    'skipped_suspended': len(skipped_suspended),
                    'backed_up_list': skipped_backed_up,
                    'suspended_list': skipped_suspended
                }
                
                return valid_accounts, stats
        
        try:
            return self.execute_in_thread(db_query)
        except Exception as e:
            logger.error(f"获取分组账号失败: {e}", exc_info=True)
            return [], {}
    
    def update_account_backup_status(self, account_identifier, backup_exported: int = 1) -> bool:
        """
        更新账号备份状态
        
        Args:
            account_identifier: 账号标识符（ID或用户名）
            backup_exported: 备份状态
        
        Returns:
            bool: 是否成功
        """
        def db_update():
            with self.get_db_session() as db:
                if not db:
                    return False
                
                SocialAccount = self.models.get('SocialAccount')
                if not SocialAccount:
                    logger.error("SocialAccount模型未找到")
                    return False
                
                # 根据类型查找账号
                if isinstance(account_identifier, int):
                    account = db.query(SocialAccount).filter(SocialAccount.id == account_identifier).first()
                else:
                    account = db.query(SocialAccount).filter(SocialAccount.username == account_identifier).first()
                
                if account:
                    account.backup_exported = backup_exported
                    db.commit()
                    logger.info(f"✅ 更新备份状态成功: {account_identifier} -> {backup_exported}")
                    return True
                else:
                    logger.warning(f"⚠️ 未找到账号: {account_identifier}")
                    return False
        
        try:
            return self.execute_in_thread(db_update)
        except Exception as e:
            logger.error(f"更新账号备份状态异常: {e}", exc_info=True)
            return False
    
    def update_account_status(self, account_identifier, status: str) -> bool:
        """
        更新账号状态
        
        Args:
            account_identifier: 账号标识符（ID或用户名）
            status: 新状态
        
        Returns:
            bool: 是否成功
        """
        def db_update():
            with self.get_db_session() as db:
                if not db:
                    return False
                
                SocialAccount = self.models.get('SocialAccount')
                if not SocialAccount:
                    logger.error("SocialAccount模型未找到")
                    return False
                
                # 根据类型查找账号
                if isinstance(account_identifier, int):
                    account = db.query(SocialAccount).filter(SocialAccount.id == account_identifier).first()
                else:
                    account = db.query(SocialAccount).filter(SocialAccount.username == account_identifier).first()
                
                if account:
                    account.status = status
                    db.commit()
                    logger.info(f"✅ 更新账号状态成功: {account_identifier} -> {status}")
                    return True
                else:
                    logger.warning(f"⚠️ 未找到账号: {account_identifier}")
                    return False
        
        try:
            return self.execute_in_thread(db_update)
        except Exception as e:
            logger.error(f"更新账号状态异常: {e}", exc_info=True)
            return False
    
    def add_suspended_account(self, username: str, reason: str = '', detected_at: Optional[float] = None) -> bool:
        """
        添加封号账号记录
        
        Args:
            username: 用户名
            reason: 封号原因
            detected_at: 检测时间
        
        Returns:
            bool: 是否成功
        """
        def db_insert():
            with self.get_db_session() as db:
                if not db:
                    return False
                
                SuspendedAccount = self.models.get('SuspendedAccount')
                if not SuspendedAccount:
                    logger.error("SuspendedAccount模型未找到")
                    return False
                
                # 检查是否已存在
                existing = db.query(SuspendedAccount).filter(SuspendedAccount.username == username).first()
                if existing:
                    logger.info(f"封号账号已存在: {username}")
                    return True
                
                # 添加新记录
                suspended_account = SuspendedAccount(
                    username=username,
                    reason=reason,
                    detected_at=detected_at or time.time()
                )
                db.add(suspended_account)
                db.commit()
                logger.info(f"✅ 添加封号账号记录: {username}")
                return True
        
        try:
            return self.execute_in_thread(db_insert)
        except Exception as e:
            logger.error(f"添加封号账号异常: {e}", exc_info=True)
            return False
    
    def get_account_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        根据用户名获取账号信息
        
        Args:
            username: 用户名
        
        Returns:
            Optional[Dict]: 账号信息
        """
        def db_query():
            with self.get_db_session() as db:
                if not db:
                    return None
                
                SocialAccount = self.models.get('SocialAccount')
                if not SocialAccount:
                    logger.error("SocialAccount模型未找到")
                    return None
                
                account = db.query(SocialAccount).filter(SocialAccount.username == username).first()
                
                if account:
                    return {
                        'id': account.id,
                        'username': account.username,
                        'password': account.password,
                        'secret_key': account.secret_key,
                        'email': getattr(account, 'email', ''),
                        'phone': getattr(account, 'phone', ''),
                        'status': account.status or 'active',
                        'proxy_id': getattr(account, 'proxy_id', None),
                        'backup_exported': account.backup_exported,
                        'group_id': getattr(account, 'group_id', None)
                    }
                else:
                    return None
        
        try:
            return self.execute_in_thread(db_query)
        except Exception as e:
            logger.error(f"获取账号信息异常: {e}", exc_info=True)
            return None
    
    def get_proxy_by_id(self, proxy_id: int) -> Optional[Dict[str, Any]]:
        """
        根据代理ID获取代理信息
        
        Args:
            proxy_id: 代理ID
        
        Returns:
            Optional[Dict]: 代理信息
        """
        def db_query():
            with self.get_db_session() as db:
                if not db:
                    return None
                
                Proxy = self.models.get('Proxy')
                if not Proxy:
                    logger.error("Proxy模型未找到")
                    return None
                
                proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
                
                if proxy:
                    return {
                        'id': proxy.id,
                        'host': proxy.ip,
                        'port': proxy.port,
                        'username': proxy.username,
                        'password': proxy.password,
                        'type': proxy.proxy_type or 'http',
                        'format_string': f"{proxy.ip}:{proxy.port}:{proxy.username}:{proxy.password}"
                    }
                else:
                    return None
        
        try:
            return self.execute_in_thread(db_query)
        except Exception as e:
            logger.error(f"获取代理信息异常: {e}", exc_info=True)
            return None
    
    def get_proxy_for_account(self, account_username: str) -> Optional[Dict[str, Any]]:
        """
        获取账号的代理配置
        
        Args:
            account_username: 账号用户名
        
        Returns:
            Optional[Dict]: 代理配置
        """
        def db_query():
            with self.get_db_session() as db:
                if not db:
                    return None
                
                SocialAccount = self.models.get('SocialAccount')
                Proxy = self.models.get('Proxy')
                
                if not SocialAccount or not Proxy:
                    logger.error("所需模型未找到")
                    return None
                
                # 查找账号
                account = db.query(SocialAccount).filter(SocialAccount.username == account_username).first()
                if not account or not account.proxy_id:
                    return None
                
                # 查找代理
                proxy = db.query(Proxy).filter(Proxy.id == account.proxy_id).first()
                if proxy:
                    return {
                        'id': proxy.id,
                        'host': proxy.ip,
                        'port': proxy.port,
                        'username': proxy.username,
                        'password': proxy.password,
                        'type': proxy.proxy_type or 'http',
                        'format_string': f"{proxy.ip}:{proxy.port}:{proxy.username}:{proxy.password}"
                    }
                else:
                    return None
        
        try:
            return self.execute_in_thread(db_query)
        except Exception as e:
            logger.error(f"获取账号代理配置异常: {e}", exc_info=True)
            return None
    
    def get_suspended_accounts(self) -> List[str]:
        """
        获取所有封号账号的用户名列表
        
        Returns:
            List[str]: 封号账号用户名列表
        """
        def db_query():
            with self.get_db_session() as db:
                if not db:
                    return []
                
                SuspendedAccount = self.models.get('SuspendedAccount')
                if not SuspendedAccount:
                    logger.warning("SuspendedAccount模型未找到")
                    return []
                
                suspended_accounts = db.query(SuspendedAccount).all()
                return [acc.username for acc in suspended_accounts]
        
        try:
            return self.execute_in_thread(db_query)
        except Exception as e:
            logger.error(f"获取封号账号列表异常: {e}", exc_info=True)
            return []
    
    def batch_update_backup_status(self, account_identifiers: List, backup_exported: int = 1) -> int:
        """
        批量更新账号备份状态
        
        Args:
            account_identifiers: 账号标识符列表
            backup_exported: 备份状态
        
        Returns:
            int: 成功更新的数量
        """
        def db_batch_update():
            with self.get_db_session() as db:
                if not db:
                    return 0
                
                SocialAccount = self.models.get('SocialAccount')
                if not SocialAccount:
                    logger.error("SocialAccount模型未找到")
                    return 0
                
                success_count = 0
                
                for identifier in account_identifiers:
                    try:
                        # 根据类型查找账号
                        if isinstance(identifier, int):
                            account = db.query(SocialAccount).filter(SocialAccount.id == identifier).first()
                        else:
                            account = db.query(SocialAccount).filter(SocialAccount.username == identifier).first()
                        
                        if account:
                            account.backup_exported = backup_exported
                            success_count += 1
                        else:
                            logger.warning(f"未找到账号: {identifier}")
                    
                    except Exception as e:
                        logger.error(f"更新账号 {identifier} 失败: {e}")
                
                if success_count > 0:
                    db.commit()
                    logger.info(f"✅ 批量更新备份状态成功: {success_count}/{len(account_identifiers)}")
                
                return success_count
        
        try:
            return self.execute_in_thread(db_batch_update)
        except Exception as e:
            logger.error(f"批量更新备份状态异常: {e}", exc_info=True)
            return 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取数据库统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        def db_stats():
            with self.get_db_session() as db:
                if not db:
                    return {}
                
                stats = {}
                
                # 账号统计
                SocialAccount = self.models.get('SocialAccount')
                if SocialAccount:
                    total_accounts = db.query(SocialAccount).count()
                    backed_up_accounts = db.query(SocialAccount).filter(SocialAccount.backup_exported == 1).count()
                    active_accounts = db.query(SocialAccount).filter(SocialAccount.status == 'active').count()
                    
                    stats.update({
                        'total_accounts': total_accounts,
                        'backed_up_accounts': backed_up_accounts,
                        'active_accounts': active_accounts,
                        'backup_rate': f"{(backed_up_accounts/total_accounts*100):.1f}%" if total_accounts > 0 else "0%"
                    })
                
                # 封号账号统计
                SuspendedAccount = self.models.get('SuspendedAccount')
                if SuspendedAccount:
                    suspended_count = db.query(SuspendedAccount).count()
                    stats['suspended_accounts'] = suspended_count
                
                # 代理统计
                Proxy = self.models.get('Proxy')
                if Proxy:
                    proxy_count = db.query(Proxy).count()
                    stats['total_proxies'] = proxy_count
                
                return stats
        
        try:
            return self.execute_in_thread(db_stats)
        except Exception as e:
            logger.error(f"获取数据库统计信息异常: {e}", exc_info=True)
            return {}

    def get_proxy_config_for_account(self, account_username: str) -> dict:
        """根据账号获取代理配置"""
        def db_operation():
            with self.get_db_session() as db:
                if not db:
                    logger.warning("⚠️ 数据库模块未配置，返回空代理配置")
                    return {
                        'proxyIp': '',
                        'proxyPort': '',
                        'proxyUser': '',
                        'proxyPassword': '',
                        'use_proxy': False
                    }
                
                SocialAccount = self.models.get('SocialAccount')
                Proxy = self.models.get('Proxy')
                
                if not SocialAccount or not Proxy:
                    logger.error("所需模型未找到")
                    return {
                        'proxyIp': '',
                        'proxyPort': '',
                        'proxyUser': '',
                        'proxyPassword': '',
                        'use_proxy': False
                    }
                
                # 查找账号信息
                account = db.query(SocialAccount).filter(
                    SocialAccount.username == account_username
                ).first()
                
                if not account or not account.proxy_id:
                    logger.debug(f"账号 {account_username} 未设置代理")
                    return {
                        'proxyIp': '',
                        'proxyPort': '',
                        'proxyUser': '',
                        'proxyPassword': '',
                        'use_proxy': False
                    }
                
                # 查找代理信息
                proxy = db.query(Proxy).filter(Proxy.id == account.proxy_id).first()
                
                if not proxy:
                    logger.warning(f"账号 {account_username} 关联的代理 ID {account.proxy_id} 不存在")
                    return {
                        'proxyIp': '',
                        'proxyPort': '',
                        'proxyUser': '',
                        'proxyPassword': '',
                        'use_proxy': False
                    }
                
                if proxy.status != 'active':
                    logger.warning(f"账号 {account_username} 关联的代理 {proxy.ip}:{proxy.port} 状态为 {proxy.status}")
                    return {
                        'proxyIp': '',
                        'proxyPort': '',
                        'proxyUser': '',
                        'proxyPassword': '',
                        'use_proxy': False
                    }
                
                logger.debug(f"账号 {account_username} 使用代理: {proxy.ip}:{proxy.port}")
                
                return {
                    'proxyIp': proxy.ip,
                    'proxyPort': str(proxy.port),
                    'proxyUser': proxy.username or '',
                    'proxyPassword': proxy.password or '',
                    'use_proxy': True,
                    'proxy_name': f"{proxy.ip}:{proxy.port}"
                }
        
        try:
            return self.execute_in_thread(db_operation)
        except Exception as e:
            logger.error(f"❌ 获取账号 {account_username} 代理配置失败: {e}")
            return {
                'proxyIp': '',
                'proxyPort': '',
                'proxyUser': '',
                'proxyPassword': '',
                'use_proxy': False
            }

    def get_account_id_by_username(self, username: str) -> Optional[int]:
        """根据用户名获取账号ID"""
        def db_operation():
            with self.get_db_session() as db:
                if not db:
                    logger.warning("⚠️ 数据库模块未配置，无法查询账号ID")
                    return None
                
                SocialAccount = self.models.get('SocialAccount')
                if not SocialAccount:
                    logger.error("SocialAccount模型未找到")
                    return None
                
                account = db.query(SocialAccount).filter(SocialAccount.username == username).first()
                if account:
                    return account.id
                else:
                    logger.warning(f"⚠️ 未找到用户名为 {username} 的账号")
                    return None
        
        try:
            return self.execute_in_thread(db_operation)
        except Exception as e:
            logger.error(f"❌ 查询账号ID失败: {e}")
            return None

    def get_accounts_by_ids(self, account_ids: List[int]) -> List[dict]:
        """根据账号ID列表批量获取账号"""
        def db_operation():
            with self.get_db_session() as db:
                if not db:
                    logger.warning("⚠️ 数据库模块未配置，返回空账号列表")
                    return []
                
                SocialAccount = self.models.get('SocialAccount')
                if not SocialAccount:
                    logger.error("SocialAccount模型未找到")
                    return []
                
                accounts = db.query(SocialAccount).filter(
                    SocialAccount.id.in_(account_ids)
                ).all()
                
                result = []
                for account in accounts:
                    result.append({
                        'id': account.id,
                        'username': account.username,
                        'password': account.password or '',
                        'email': account.email or '',
                        'phone': account.phone or '',
                        'group_id': account.group_id,
                        'proxy_id': account.proxy_id,
                        'status': account.status or 'active',
                        'backup_exported': account.backup_exported or 0,
                        'created_at': account.created_at,
                        'updated_at': account.updated_at
                    })
                
                logger.info(f"✅ 批量获取账号成功: {len(result)} 个账号")
                return result
        
        try:
            return self.execute_in_thread(db_operation)
        except Exception as e:
            logger.error(f"❌ 批量获取账号失败: {e}")
            return []

    def batch_update_backup_status(self, account_ids: List[int], backup_exported: int = 1) -> bool:
        """批量更新账号备份状态"""
        def db_operation():
            with self.get_db_session() as db:
                if not db:
                    logger.warning("⚠️ 数据库模块未配置，无法批量更新备份状态")
                    return False
                
                SocialAccount = self.models.get('SocialAccount')
                if not SocialAccount:
                    logger.error("SocialAccount模型未找到")
                    return False
                
                # 批量更新
                update_count = db.query(SocialAccount).filter(
                    SocialAccount.id.in_(account_ids)
                ).update(
                    {SocialAccount.backup_exported: backup_exported},
                    synchronize_session=False
                )
                
                db.commit()
                
                logger.info(f"✅ 批量更新备份状态成功: {update_count} 个账号更新为 {'已导出' if backup_exported == 1 else '未导出'}")
                return True
        
        try:
            return self.execute_in_thread(db_operation)
        except Exception as e:
            logger.error(f"❌ 批量更新备份状态失败: {e}")
            return False 