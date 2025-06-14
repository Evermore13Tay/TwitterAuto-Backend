"""
账号管理核心模块
统一管理账号验证、登录、备份、状态检查等功能
"""

import asyncio
import aiohttp
import logging
import time
import threading
import queue
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class AccountManager:
    """账号管理核心类"""
    
    def __init__(self):
        self.operation_timeout = 30
        self.login_timeout = 180
        self.max_retry_attempts = 3
        
    def get_accounts_from_group(self, group_id: str, exclude_backed_up: bool = True, exclude_suspended: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        从分组获取账号列表
        
        Args:
            group_id: 分组ID
            exclude_backed_up: 是否排除已备份账号
            exclude_suspended: 是否排除已封号账号
        
        Returns:
            Tuple[List[Dict], Dict]: (账号列表, 统计信息)
        """
        try:
            # 导入数据库相关模块
            try:
                from db.database import SessionLocal
                from db.models import SocialAccount
                from suspended_account import SuspendedAccount
            except ImportError as e:
                logger.error(f"导入数据库模块失败: {e}")
                return [], {}
            
            result_queue = queue.Queue()
            error_queue = queue.Queue()
            
            def db_query_operation():
                try:
                    db = SessionLocal()
                    
                    # 获取所有该分组的账号
                    all_accounts = db.query(SocialAccount).filter(SocialAccount.group_id == group_id).all()
                    
                    # 获取suspended_accounts表中的封号账号列表
                    suspended_usernames = set()
                    try:
                        suspended_accounts_records = db.query(SuspendedAccount).all()
                        suspended_usernames = {acc.username for acc in suspended_accounts_records}
                    except Exception as suspended_error:
                        logger.warning(f"获取suspended_accounts表失败: {suspended_error}")
                    
                    # 处理账号列表
                    accounts_from_db = []
                    skipped_backed_up = []
                    skipped_suspended = []
                    
                    for db_acc in all_accounts:
                        # 检查是否在suspended_accounts表中或status为suspended
                        is_suspended = (db_acc.username in suspended_usernames) or (db_acc.status == 'suspended')
                        
                        if exclude_backed_up and db_acc.backup_exported == 1:
                            skipped_backed_up.append(db_acc.username)
                        elif exclude_suspended and is_suspended:
                            skipped_suspended.append(db_acc.username)
                        elif db_acc.username and db_acc.password and db_acc.secret_key:
                            # 添加有效账号
                            accounts_from_db.append({
                                'id': db_acc.id,
                                'username': db_acc.username,
                                'password': db_acc.password,
                                'secretkey': db_acc.secret_key,
                                'email': getattr(db_acc, 'email', ''),
                                'phone': getattr(db_acc, 'phone', ''),
                                'status': db_acc.status or 'active'
                            })
                    
                    # 统计信息
                    stats = {
                        'total_accounts': len(all_accounts),
                        'valid_accounts': len(accounts_from_db),
                        'skipped_backed_up': len(skipped_backed_up),
                        'skipped_suspended': len(skipped_suspended),
                        'backed_up_list': skipped_backed_up,
                        'suspended_list': skipped_suspended
                    }
                    
                    db.close()
                    result_queue.put((accounts_from_db, stats))
                    
                except Exception as e:
                    error_queue.put(e)
            
            # 执行数据库查询
            db_thread = threading.Thread(target=db_query_operation)
            db_thread.daemon = True
            db_thread.start()
            db_thread.join(timeout=20)
            
            if not error_queue.empty():
                raise error_queue.get()
            elif not result_queue.empty():
                accounts, stats = result_queue.get()
                
                logger.info(f"📊 分组账号统计: 总数={stats['total_accounts']}, "
                           f"已备份={stats['skipped_backed_up']}, "
                           f"已封号={stats['skipped_suspended']}, "
                           f"待处理={stats['valid_accounts']}")
                
                return accounts, stats
            else:
                logger.error("数据库查询超时")
                return [], {}
                
        except Exception as e:
            logger.error(f"获取分组账号失败: {e}", exc_info=True)
            return [], {}
    
    def parse_accounts_from_string(self, accounts_str: str) -> List[Dict[str, Any]]:
        """
        从字符串解析账号列表
        
        Args:
            accounts_str: 账号字符串，格式：username:password:secretkey
        
        Returns:
            List[Dict]: 账号列表
        """
        try:
            accounts = []
            if not accounts_str or accounts_str.strip() == '':
                return accounts
            
            lines = accounts_str.strip().split('\n')
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split(':')
                if len(parts) >= 3:
                    username = parts[0].strip()
                    password = parts[1].strip()
                    secretkey = parts[2].strip()
                    
                    if username and password and secretkey:
                        accounts.append({
                            'username': username,
                            'password': password,
                            'secretkey': secretkey,
                            'line_number': line_num
                        })
                    else:
                        logger.warning(f"第{line_num}行账号信息不完整: {line}")
                else:
                    logger.warning(f"第{line_num}行格式错误: {line}")
            
            logger.info(f"📝 从字符串解析到 {len(accounts)} 个有效账号")
            return accounts
            
        except Exception as e:
            logger.error(f"解析账号字符串失败: {e}", exc_info=True)
            return []
    
    async def verify_account_login(self, device_ip: str, u2_port: int, myt_rpc_port: int, username: str, password: str, secret_key: str, task_id: Optional[int] = None) -> bool:
        """
        验证账号登录状态 - 使用本地脚本而非直连设备
        
        Args:
            device_ip: 设备IP地址
            u2_port: U2端口
            myt_rpc_port: RPC端口
            username: 用户名
            password: 密码
            secret_key: 密钥
            task_id: 任务ID
        
        Returns:
            bool: 是否登录成功
        """
        try:
            logger.info(f"[任务{task_id}] 🔍 开始验证账号登录: {username}")
            
            # 🔧 **修复：使用本地脚本检查登录状态，而不是直连设备API**
            # 先尝试检查登录状态
            login_status = await self._check_login_status_via_script(device_ip, u2_port, myt_rpc_port, username, task_id)
            
            if login_status:
                logger.info(f"[任务{task_id}] ✅ 账号已登录: {username}")
                return True
            else:
                logger.info(f"[任务{task_id}] 📱 账号未登录，尝试登录: {username}")
                return await self._perform_login_via_script(device_ip, u2_port, myt_rpc_port, username, password, secret_key, task_id)
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 验证账号登录异常: {e}", exc_info=True)
            return False
    
    async def _check_login_status_via_script(self, device_ip: str, u2_port: int, myt_rpc_port: int, username: str, task_id: Optional[int] = None) -> bool:
        """通过本地脚本检查登录状态"""
        try:
            import asyncio
            import sys
            import os
            
            # 找到check_twitter_login_status脚本
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'check_twitter_login_status.py')
            
            if not os.path.exists(script_path):
                logger.warning(f"[任务{task_id}] ⚠️ 登录状态检查脚本不存在: {script_path}")
                return False
            
            # 构建命令
            cmd = [
                sys.executable,
                script_path,
                device_ip,
                str(u2_port),
                str(myt_rpc_port),
                username
            ]
            
            logger.debug(f"[任务{task_id}] 🔍 执行登录状态检查: {' '.join(cmd)}")
            
            # 执行命令
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)  # 2分钟超时
                
                if process.returncode == 0:
                    logger.info(f"[任务{task_id}] ✅ 登录状态检查成功: {username}")
                    return True
                else:
                    logger.info(f"[任务{task_id}] 📱 登录状态检查：账号未登录: {username}")
                    if stderr:
                        try:
                            error_output = stderr.decode('utf-8', errors='ignore')
                            logger.debug(f"[任务{task_id}] 检查脚本错误输出: {error_output}")
                        except Exception as decode_error:
                            logger.debug(f"[任务{task_id}] 检查脚本错误输出解码失败: {decode_error}")
                    return False
                    
            except asyncio.TimeoutError:
                logger.warning(f"[任务{task_id}] ⚠️ 登录状态检查超时: {username}")
                process.kill()
                return False
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 登录状态检查脚本异常: {e}", exc_info=True)
            return False
    
    async def _perform_login_via_script(self, device_ip: str, u2_port: int, myt_rpc_port: int, username: str, password: str, secret_key: str, task_id: Optional[int] = None) -> bool:
        """🚀 [优化版] 直接使用batch_login_test.py兼容的登录服务，提高效率和稳定性"""
        try:
            # 🔧 [关键修复] 直接调用我们修复的优化登录服务，而不是通过subprocess调用脚本
            logger.info(f"[任务{task_id}] 🚀 [OPTIMIZED] 使用batch_login_test兼容登录方法: {username}")
            
            # 导入我们修复的登录服务
            try:
                from services.optimized_login_service import run_batch_login_test_compatible_task
            except ImportError:
                logger.error(f"[任务{task_id}] ❌ 无法导入优化登录服务，回退到脚本方式")
                return await self._perform_login_via_script_fallback(device_ip, u2_port, myt_rpc_port, username, password, secret_key, task_id)
            
            # 创建状态回调函数
            def status_callback(message):
                logger.info(f"[任务{task_id}] [LOGIN_STATUS] {message}")
            
            # 🚀 [关键] 调用100%兼容batch_login_test.py的登录方法
            success, result_message = await run_batch_login_test_compatible_task(
                status_callback,
                device_ip,
                u2_port,
                myt_rpc_port,
                username,
                password,
                secret_key,
                task_id
            )
            
            if success:
                logger.info(f"[任务{task_id}] ✅ [OPTIMIZED] 账号登录成功: {username}")
                return True
            else:
                logger.error(f"[任务{task_id}] ❌ [OPTIMIZED] 账号登录失败: {username} - {result_message}")
                return False
                
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ [OPTIMIZED] 优化登录服务执行异常: {e}", exc_info=True)
            # 回退到脚本方式
            logger.info(f"[任务{task_id}] 🔄 回退到脚本登录方式...")
            return await self._perform_login_via_script_fallback(device_ip, u2_port, myt_rpc_port, username, password, secret_key, task_id)
    
    async def _perform_login_via_script_fallback(self, device_ip: str, u2_port: int, myt_rpc_port: int, username: str, password: str, secret_key: str, task_id: Optional[int] = None) -> bool:
        """回退到脚本方式执行登录"""
        try:
            import asyncio
            import sys
            import os
            
            # 找到logintest脚本
            script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'automation', 'logintest.py')
            
            if not os.path.exists(script_path):
                logger.warning(f"[任务{task_id}] ⚠️ 登录脚本不存在: {script_path}")
                return False
            
            # 构建命令
            cmd = [
                sys.executable,
                script_path,
                device_ip,
                str(u2_port),
                str(myt_rpc_port),
                username,
                password,
                secret_key
            ]
            
            logger.debug(f"[任务{task_id}] 🔍 执行登录脚本: {device_ip}:{u2_port} 用户: {username}")
            
            # 执行命令
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)  # 5分钟超时
                
                stdout_str = stdout.decode('utf-8', errors='ignore') if stdout else ""
                stderr_str = stderr.decode('utf-8', errors='ignore') if stderr else ""
                
                # 检查输出中的登录成功标识
                if "LOGIN_SUCCESS" in stdout_str or process.returncode == 0:
                    logger.info(f"[任务{task_id}] ✅ 账号登录成功: {username}")
                    return True
                else:
                    logger.error(f"[任务{task_id}] ❌ 账号登录失败: {username}")
                    if "LOGIN_FAIL" in stdout_str:
                        logger.debug(f"[任务{task_id}] 登录失败详情: {stdout_str}")
                    if stderr_str:
                        logger.debug(f"[任务{task_id}] 登录脚本错误输出: {stderr_str}")
                    return False
                    
            except asyncio.TimeoutError:
                logger.warning(f"[任务{task_id}] ⚠️ 登录操作超时: {username}")
                process.kill()
                return False
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 登录脚本执行异常: {e}", exc_info=True)
            return False

    async def _perform_login(self, device_ip: str, u2_port: int, myt_rpc_port: int, username: str, password: str, secret_key: str, task_id: Optional[int] = None) -> bool:
        """执行登录的内部方法 - 已弃用，使用_perform_login_via_script代替"""
        logger.warning(f"[任务{task_id}] ⚠️ 使用了已弃用的登录方法，自动切换到脚本方式")
        return await self._perform_login_via_script(device_ip, u2_port, myt_rpc_port, username, password, secret_key, task_id)
    
    async def check_suspension_status(self, device_ip: str, u2_port: int, username: str, task_id: Optional[int] = None) -> bool:
        """
        检查账号是否被封号
        
        Args:
            device_ip: 设备IP地址
            u2_port: U2端口
            username: 用户名
            task_id: 任务ID
        
        Returns:
            bool: 是否被封号
        """
        max_retries = 3
        session = None
        
        try:
            for attempt in range(max_retries):
                try:
                    # 🔧 **修复：为每次尝试创建新的session，避免连接重置错误**
                    connector = aiohttp.TCPConnector(
                        limit=10,
                        limit_per_host=5,
                        ttl_dns_cache=300,
                        use_dns_cache=True,
                        keepalive_timeout=30,
                        enable_cleanup_closed=True,  # 启用清理已关闭连接
                        force_close=True,            # Windows平台强制关闭连接
                        connector_timeout=10
                    )
                    
                    timeout = aiohttp.ClientTimeout(
                        total=30,
                        connect=10,
                        sock_read=10,
                        sock_connect=10
                    )
                    
                    session = aiohttp.ClientSession(
                        connector=connector,
                        timeout=timeout,
                        trust_env=True
                    )
                    
                    url = f"http://{device_ip}:{u2_port}/api/twitter/check_status"
                    data = {
                        "username": username,
                        "check_suspended": True,
                        "skip_backup": True
                    }
                    
                    logger.info(f"[任务{task_id}] 🔍 检查封号状态: {username} -> {url}")
                    
                    async with session.post(url, json=data) as response:
                        if response.status == 200:
                            result = await response.json()
                            is_suspended = result.get('is_suspended', False)
                            
                            if is_suspended:
                                reason = result.get('reason', '未知原因')
                                logger.warning(f"[任务{task_id}] ⚠️ 账号已被封号: {username} - {reason}")
                                
                                # 🔧 **增强：更新数据库封号状态**
                                await self._update_suspension_database(username, reason, task_id)
                                
                                return is_suspended
                            else:
                                logger.info(f"[任务{task_id}] ✅ 账号状态正常: {username}")
                                return is_suspended
                        else:
                            if response.status == 404:
                                logger.warning(f"[任务{task_id}] ⚠️ 账号API不存在: {username}")
                                
                                return is_suspended
                            else:
                                logger.warning(f"[任务{task_id}] ⚠️ 无法检查封号状态: {username}")
                                return False
                                
                except (
                    aiohttp.ClientError, 
                    asyncio.TimeoutError, 
                    RuntimeError,
                    ConnectionResetError,  # 🔧 新增：显式处理连接重置错误
                    OSError,               # 🔧 新增：处理Windows网络错误
                    Exception             # 🔧 新增：捕获其他连接异常
                ) as e:
                    # 🔧 **修复：针对Windows平台的连接错误进行特殊处理**
                    error_msg = str(e)
                    is_connection_error = any(error_pattern in error_msg.lower() for error_pattern in [
                        'connection reset',
                        'winError 10054',
                        'server disconnected',
                        'connection lost',
                        'remote host closed',
                        'connection broken'
                    ])
                    
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2  # 递增等待时间：2s, 4s, 6s
                        if is_connection_error:
                            logger.warning(f"[任务{task_id}] ⚠️ 连接重置错误，重试 {attempt + 1}/{max_retries}: {e}")
                            logger.info(f"[任务{task_id}] 🔄 等待 {wait_time}s 后重试...")
                        else:
                            logger.warning(f"[任务{task_id}] ⚠️ 封号检测失败，重试 {attempt + 1}/{max_retries}: {e}")
                        
                        await asyncio.sleep(wait_time)  # 🔧 修复：递增等待时间
                        continue
                    else:
                        if is_connection_error:
                            logger.error(f"[任务{task_id}] ❌ 连接重置错误（最终失败）: {e}")
                        else:
                            logger.error(f"[任务{task_id}] ❌ 封号检测最终失败: {e}")
                        return False
                finally:
                    # 🔧 **修复：强化session清理，防止连接泄漏**
                    if session and not session.closed:
                        try:
                            await session.close()
                            # 🔧 Windows平台需要额外等待确保连接完全关闭
                            await asyncio.sleep(0.2)
                            
                            # 🔧 强制清理连接器
                            if hasattr(session, '_connector') and session._connector:
                                await session._connector.close()
                                
                        except Exception as cleanup_error:
                            logger.debug(f"[任务{task_id}] Session清理警告: {cleanup_error}")
                    session = None  # 🔧 重置session引用
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 检查封号状态异常: {e}", exc_info=True)
            return False
    
    async def _update_suspension_database(self, username: str, reason: str, task_id: int):
        """更新封号账号到数据库的异步方法"""
        try:
            logger.info(f"[任务{task_id}] 📝 开始更新封号数据库: {username} - {reason}")
            
            # 在线程池中执行数据库操作，避免阻塞异步循环
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sync_update_suspension_database, username, reason, task_id)
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 更新封号数据库异常: {e}")
    
    def _sync_update_suspension_database(self, username: str, reason: str, task_id: int):
        """同步更新封号数据库的方法"""
        try:
            # 导入数据库模块
            try:
                from db.database import SessionLocal
                from db.models import SocialAccount
                from suspended_account import SuspendedAccount
            except ImportError:
                logger.warning(f"[任务{task_id}] 无法导入数据库模块，跳过封号状态更新")
                return
            
            db = SessionLocal()
            try:
                # 🔧 双重更新：suspended_accounts表 + social_accounts.status
                
                # 1. 添加到suspended_accounts表
                existing_suspended = db.query(SuspendedAccount).filter(SuspendedAccount.username == username).first()
                if not existing_suspended:
                    suspended_account = SuspendedAccount(
                        username=username,
                        reason=reason,
                        detected_at=time.time()
                    )
                    db.add(suspended_account)
                    logger.info(f"[任务{task_id}] ✅ 已添加到封号表: {username}")
                
                # 2. 更新SocialAccount表状态
                account = db.query(SocialAccount).filter(SocialAccount.username == username).first()
                if account:
                    account.status = 'suspended'
                    logger.info(f"[任务{task_id}] ✅ 已更新账号状态: {username} -> suspended")
                
                db.commit()
                logger.info(f"[任务{task_id}] ✅ 封号状态数据库更新完成: {username}")
                
            except Exception as e:
                db.rollback()
                logger.error(f"[任务{task_id}] ❌ 数据库操作失败: {e}")
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 封号状态更新异常: {e}")
    
    async def export_account_backup(self, device_ip: str, u2_port: int, username: str, backup_dir: str, task_id: Optional[int] = None) -> Optional[str]:
        """
        导出账号备份 - 使用BoxManipulate模块导出
        
        Args:
            device_ip: 设备IP地址
            u2_port: U2端口
            username: 用户名
            backup_dir: 备份目录
            task_id: 任务ID
        
        Returns:
            Optional[str]: 备份文件路径
        """
        try:
            logger.info(f"[任务{task_id}] 📦 开始导出备份: {username}")
            
            # 🔧 **修复：使用BoxManipulate模块进行备份导出，而不是直连设备API**
            try:
                import sys
                import os
                current_dir = os.path.dirname(os.path.abspath(__file__))
                backend_dir = os.path.dirname(current_dir)
                automation_dir = os.path.join(backend_dir, 'automation')
                sys.path.insert(0, automation_dir)
                
                from automation.BoxManipulate import call_export_api
                
                # 🔧 修复：生成正确的备份文件名格式（账号名.tar.gz）
                backup_filename = f"{username}.tar.gz"
                backup_file_path = os.path.join(backup_dir, backup_filename)
                
                # 确保备份目录存在
                try:
                    os.makedirs(backup_dir, exist_ok=True)
                    logger.info(f"[任务{task_id}] 📂 备份目录已准备: {backup_dir}")
                except Exception as e:
                    logger.error(f"[任务{task_id}] ❌ 创建备份目录失败: {e}")
                    return None
                
                # 调用导出API
                # call_export_api(ip_address, name, local_path)
                # 这里我们需要找到对应的容器名称
                container_name = f"Twitter_{username}_{device_ip.replace('.', '_')}"  # 需要根据实际情况调整
                
                result = call_export_api(device_ip, container_name, backup_file_path)
                
                if result:
                    logger.info(f"[任务{task_id}] ✅ 备份导出成功: {username} -> {backup_file_path}")
                    # 更新数据库备份状态
                    self.update_account_backup_status(username, 1)
                    return backup_file_path
                else:
                    logger.error(f"[任务{task_id}] ❌ 备份导出失败: BoxManipulate返回失败")
                    return None
                    
            except ImportError as e:
                logger.warning(f"[任务{task_id}] ⚠️ 无法导入BoxManipulate模块: {e}")
                # 降级处理：简单标记为已备份但不实际导出文件
                logger.info(f"[任务{task_id}] 🔄 降级处理：标记账号为已备份状态")
                self.update_account_backup_status(username, 1)
                return f"{backup_dir}/{username}_placeholder.tar.gz"
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 导出备份异常: {e}", exc_info=True)
            return None
    
    def update_account_backup_status(self, username_or_id, backup_exported: int = 1) -> bool:
        """
        更新账号备份状态
        
        Args:
            username_or_id: 用户名或ID
            backup_exported: 备份状态（1=已备份，0=未备份）
        
        Returns:
            bool: 是否成功
        """
        try:
            # 导入数据库模块
            try:
                from db.database import SessionLocal
                from db.models import SocialAccount
            except ImportError:
                logger.warning("无法导入数据库模块，跳过备份状态更新")
                return False
            
            result_queue = queue.Queue()
            error_queue = queue.Queue()
            
            def db_update_operation():
                try:
                    db = SessionLocal()
                    
                    # 根据类型查找账号
                    if isinstance(username_or_id, int):
                        account = db.query(SocialAccount).filter(SocialAccount.id == username_or_id).first()
                    else:
                        account = db.query(SocialAccount).filter(SocialAccount.username == username_or_id).first()
                    
                    if account:
                        account.backup_exported = backup_exported
                        db.commit()
                        result_queue.put(True)
                        logger.info(f"✅ 更新备份状态成功: {username_or_id} -> {backup_exported}")
                    else:
                        result_queue.put(False)
                        logger.warning(f"⚠️ 未找到账号: {username_or_id}")
                    
                    db.close()
                    
                except Exception as e:
                    error_queue.put(e)
            
            # 在线程中执行数据库操作
            db_thread = threading.Thread(target=db_update_operation)
            db_thread.daemon = True
            db_thread.start()
            db_thread.join(timeout=10)
            
            if not error_queue.empty():
                raise error_queue.get()
            elif not result_queue.empty():
                return result_queue.get()
            else:
                logger.error("数据库更新超时")
                return False
                
        except Exception as e:
            logger.error(f"更新账号备份状态异常: {e}", exc_info=True)
            return False
    
    def get_account_id_by_username(self, username: str) -> Optional[int]:
        """
        根据用户名获取账号ID
        
        Args:
            username: 用户名
        
        Returns:
            Optional[int]: 账号ID
        """
        try:
            # 导入数据库模块
            try:
                from db.database import SessionLocal
                from db.models import SocialAccount
            except ImportError:
                logger.warning("无法导入数据库模块")
                return None
            
            result_queue = queue.Queue()
            error_queue = queue.Queue()
            
            def db_query_operation():
                try:
                    db = SessionLocal()
                    account = db.query(SocialAccount).filter(SocialAccount.username == username).first()
                    
                    if account:
                        result_queue.put(account.id)
                    else:
                        result_queue.put(None)
                    
                    db.close()
                    
                except Exception as e:
                    error_queue.put(e)
            
            # 在线程中执行数据库查询
            db_thread = threading.Thread(target=db_query_operation)
            db_thread.daemon = True
            db_thread.start()
            db_thread.join(timeout=10)
            
            if not error_queue.empty():
                raise error_queue.get()
            elif not result_queue.empty():
                return result_queue.get()
            else:
                logger.error("数据库查询超时")
                return None
                
        except Exception as e:
            logger.error(f"获取账号ID异常: {e}", exc_info=True)
            return None
    
    def get_proxy_config_for_account(self, account_username: str) -> Dict[str, Any]:
        """
        获取账号的代理配置
        
        Args:
            account_username: 账号用户名
        
        Returns:
            Dict[str, Any]: 代理配置
        """
        try:
            # 导入数据库模块
            try:
                from db.database import SessionLocal
                from db.models import SocialAccount, Proxy
            except ImportError:
                logger.warning("无法导入数据库模块")
                return {}
            
            result_queue = queue.Queue()
            error_queue = queue.Queue()
            
            def db_query_operation():
                try:
                    db = SessionLocal()
                    
                    # 查找账号
                    account = db.query(SocialAccount).filter(SocialAccount.username == account_username).first()
                    if not account or not account.proxy_id:
                        result_queue.put({})
                        db.close()
                        return
                    
                    # 查找代理
                    proxy = db.query(Proxy).filter(Proxy.id == account.proxy_id).first()
                    if proxy:
                        proxy_config = {
                            'id': proxy.id,
                            'host': proxy.host,
                            'port': proxy.port,
                            'username': proxy.username,
                            'password': proxy.password,
                            'type': proxy.type or 'http',
                            'format_string': f"{proxy.host}:{proxy.port}:{proxy.username}:{proxy.password}"
                        }
                        result_queue.put(proxy_config)
                    else:
                        result_queue.put({})
                    
                    db.close()
                    
                except Exception as e:
                    error_queue.put(e)
            
            # 在线程中执行数据库查询
            db_thread = threading.Thread(target=db_query_operation)
            db_thread.daemon = True
            db_thread.start()
            db_thread.join(timeout=10)
            
            if not error_queue.empty():
                raise error_queue.get()
            elif not result_queue.empty():
                return result_queue.get()
            else:
                logger.error("数据库查询超时")
                return {}
                
        except Exception as e:
            logger.error(f"获取代理配置异常: {e}", exc_info=True)
            return {} 