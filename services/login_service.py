import logging
import asyncio
from typing import Callable, Dict, Any, Optional
from fastapi import WebSocket
import traceback
# 替换原有的logintest模块，使用优化的登录服务
from services.optimized_login_service import run_optimized_login_task, run_batch_login_test_compatible_task
from utils.callbacks import WebSocketStatusCallback, SynchronousStatusCallback

logger = logging.getLogger("TwitterAutomationAPI")

async def run_login_task(status_callback, device_ip: str, u2_port: int, myt_rpc_port: int, 
                  username: str, password: str, secret_key: str) -> tuple[bool, str]:
    """
    🚀 [优化版] 使用基于batch_login_test.py验证成功的登录方法
    Returns (success, error_message)。error_message 仅在失败时返回详细异常。
    """
    try:
        logger.info(f"run_login_task: [OPTIMIZED START] device_ip={device_ip}, u2_port={u2_port}, "
                   f"myt_rpc_port={myt_rpc_port}, username={username}, "
                   f"password_len={len(password) if password else 0}, "
                   f"secret_key_len={len(secret_key) if secret_key else 0}")
        
        if hasattr(status_callback, 'thread'):
            logger.info(f"run_login_task: Callback has .thread. Progress updater type: {type(status_callback.thread.progress_updated)}")
        else:
            logger.warning("run_login_task: Callback does NOT have .thread attribute as expected by logintest.py for progress/stop.")

        # 🚀 [关键改进] 使用优化的登录方法替换原有的logintest.run_login
        logger.info(f"run_login_task: [OPTIMIZED] 使用基于batch_login_test.py的验证成功方法")
        
        # 新增：收集所有 status_callback 消息
        error_messages = []
        def collecting_callback(msg):
            error_messages.append(str(msg))
            if status_callback and callable(status_callback):
                status_callback(msg)

        # 创建本地副本避免并发问题
        local_username = username
        local_device_ip = device_ip
        local_password = password  
        local_secret_key = secret_key
        
        # 🚀 [关键] 调用100%兼容batch_login_test.py的登录方法
        success, result_message = await run_batch_login_test_compatible_task(
            collecting_callback,  # 用收集器包装原 callback
            local_device_ip,
            u2_port,
            myt_rpc_port,
            local_username,
            local_password,
            local_secret_key
        )
        
        logger.info(f"run_login_task: [OPTIMIZED END] device_ip={local_device_ip}, username={local_username}, "
                   f"success={success}, result_message={result_message}")
        
        if not success:
            logger.error(f"run_login_task: [OPTIMIZED] Login failed for device_ip={local_device_ip}, "
                        f"username={local_username}, password_len={len(local_password) if local_password else 0}, "
                        f"secret_key_len={len(local_secret_key) if local_secret_key else 0}")
            # 返回优化登录服务的详细错误信息
            detailed_error = result_message if result_message else "优化登录方法返回失败"
            if error_messages:
                detailed_error += f"\n详细信息: {' | '.join(error_messages[-5:])}"  # 只取最后5条消息
            return False, detailed_error
            
        logger.info(f"run_login_task: [OPTIMIZED] Login successful for device_ip={local_device_ip}, username={local_username}")
        return True, result_message
        
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"run_login_task error: {e}\n{tb}")
        if status_callback and callable(status_callback):
            try:
                status_callback(f"CRITICAL ERROR in optimized login task: {str(e)}")
            except Exception as cb_e:
                logger.error(f"Failed to send critical error via status_callback: {cb_e}")
        return False, f"run_login_task异常: {e}\n{tb}" 