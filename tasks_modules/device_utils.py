"""
设备工具函数模块
包含封号检测、设备连接等功能
"""

import asyncio
import aiohttp
from datetime import datetime
from common.logger import logger
from utils.port_manager import calculate_default_ports
from db.database import SessionLocal
from suspended_account import SuspendedAccount

async def add_to_suspended_accounts(username: str, device_ip: str, container_name: str, task_id: int):
    """
    将封号账号添加到suspended_accounts表
    
    Args:
        username: 账号用户名
        device_ip: 设备IP
        container_name: 容器名称
        task_id: 任务ID
    """
    try:
        db = SessionLocal()
        
        # 检查账号是否已在suspended_accounts表中
        existing = db.query(SuspendedAccount).filter(SuspendedAccount.username == username).first()
        
        if existing:
            logger.info(f"[任务{task_id}] 📝 账号 {username} 已在封号列表中，更新信息")
            # 更新现有记录
            existing.device_ip = device_ip
            existing.device_name = container_name or "未知容器"
            existing.suspended_at = datetime.utcnow()
            existing.details = f"任务{task_id}更新 - 设备{device_ip}容器{container_name}"
        else:
            logger.info(f"[任务{task_id}] ➕ 将账号 {username} 添加到封号列表")
            # 创建新记录
            suspended_account = SuspendedAccount(
                username=username,
                device_ip=device_ip,
                device_name=container_name or "未知容器",
                details=f"任务{task_id}检测 - 设备{device_ip}容器{container_name}"
            )
            db.add(suspended_account)
        
        db.commit()
        logger.info(f"[任务{task_id}] ✅ 封号账号 {username} 已成功记录到数据库")
        
    except Exception as e:
        logger.error(f"[任务{task_id}] ❌ 记录封号账号 {username} 到数据库失败: {e}")
        if 'db' in locals():
            db.rollback()
    finally:
        if 'db' in locals():
            db.close()

async def perform_real_time_suspension_check(task_id: int, device_ip: str, instance_slot: int, account: dict, is_suspended: bool, container_name: str = None):
    """
    实时封号检测函数
    
    Args:
        task_id: 任务ID
        device_ip: 设备IP
        instance_slot: 实例位
        account: 账号信息
        is_suspended: 当前封号状态
        container_name: 容器名称
    
    Returns:
        bool: 更新后的封号状态
    """
    logger.info(f"[任务{task_id}] 🔍 登录成功后等待3秒，进行实时封号检测: {account['username']}")
    await asyncio.sleep(3)  # 等待3秒让页面稳定
    
    try:
        # 🔧 使用统一的端口管理器获取端口信息
        u2_port, myt_rpc_port = calculate_default_ports(instance_slot)
        
        # 方法1: 直接通过UI检测封号状态 (推荐方法)
        logger.info(f"[任务{task_id}] 📱 通过UI直接检测封号状态...")
        
        # 连接设备进行UI检测 - 先获取动态端口信息
        logger.info(f"[任务{task_id}] 动态获取到端口信息 - U2端口: {u2_port}, MytRpc端口: {myt_rpc_port}")
        
        try:
            # 如果没有提供容器名，需要先获取当前容器信息
            if not container_name:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://127.0.0.1:5000/get/{device_ip}") as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get('code') == 200 and data.get('msg') and isinstance(data['msg'], list):
                                devices = data['msg']
                                for device in devices:
                                    if device.get('index') == instance_slot and device.get('State') == 'running':
                                        container_name = device.get('Names')
                                        break
                                if not container_name:
                                    logger.warning(f"[任务{task_id}] ⚠️ 无法找到实例位{instance_slot}的运行容器，使用默认端口")
                                    raise Exception("容器名未找到")
            
            if container_name:
                api_info_url = f"http://127.0.0.1:5000/and_api/v1/get_api_info/{device_ip}/{container_name}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(api_info_url) as response:
                        if response.status == 200:
                            api_data = await response.json()
                            if api_data.get('code') == 200 and api_data.get('data'):
                                adb_info = api_data['data'].get('ADB', '')
                                rpc_info = api_data['data'].get('RPC', '')
                                if adb_info and ':' in adb_info:
                                    u2_port = int(adb_info.split(':')[1])
                                if rpc_info and ':' in rpc_info:
                                    myt_rpc_port = int(rpc_info.split(':')[1])
                                logger.debug(f"[任务{task_id}] 动态获取到端口信息 - U2端口: {u2_port}, MytRpc端口: {myt_rpc_port}")
                            else:
                                logger.warning(f"[任务{task_id}] ⚠️ 动态端口获取失败，使用默认端口计算")
                        else:
                            logger.warning(f"[任务{task_id}] ⚠️ 无法获取动态端口信息 ({response.status})，使用默认端口计算")
        except Exception as port_error:
            logger.warning(f"[任务{task_id}] ⚠️ 动态端口获取异常: {port_error}，使用默认端口计算")
        
        try:
            # 导入必要的模块
            import uiautomator2 as u2
            from common.twitter_ui_handlers import check_account_suspended
            
            # 连接设备
            u2_device = u2.connect(f"{device_ip}:{u2_port}")
            device_info = f"[{device_ip}:{u2_port}]"
            
            # 状态回调函数
            def ui_status_callback(message):
                logger.info(f"[任务{task_id}] UI检测: {message}")
            
            # 使用UI检测封号状态
            ui_suspended = check_account_suspended(
                u2_device, None, ui_status_callback, device_info, 
                account['username'], f"TwitterAutomation_{device_ip.replace('.', '_')}"
            )
            
            if ui_suspended:
                is_suspended = True
                logger.warning(f"[任务{task_id}] 🚫 UI检测发现账号 {account['username']} 已被封号！")
                
                # 将封号账号添加到suspended_accounts表
                await add_to_suspended_accounts(account['username'], device_ip, container_name, task_id)
            else:
                logger.debug(f"[任务{task_id}] UI检测确认账号 {account['username']} 状态正常")
                
        except Exception as ui_check_error:
            logger.warning(f"[任务{task_id}] ⚠️ UI封号检测失败: {ui_check_error}，尝试API检测...")
            
            # 方法2: API检测作为备用方案
            login_test_url = "http://127.0.0.1:8000/api/login_test"
            login_test_params = {
                'device_ip': device_ip,
                'username': account['username'],
                'instance_id': instance_slot
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(login_test_url, json=login_test_params) as response:
                    if response.status == 200:
                        test_result = await response.json()
                        # 检查返回结果中是否包含封号信息
                        result_data = test_result.get('result', {})
                        account_status = result_data.get('account_status', '')
                        login_status = result_data.get('login_status', '')
                        
                        # 更新封号状态检测
                        if account_status == 'suspended' or login_status == 'suspended':
                            is_suspended = True
                            logger.warning(f"[任务{task_id}] ⚠️ API检测发现账号 {account['username']} 已被封号")
                            
                            # 将封号账号添加到suspended_accounts表
                            await add_to_suspended_accounts(account['username'], device_ip, container_name, task_id)
                        else:
                            logger.debug(f"[任务{task_id}] API检测确认账号 {account['username']} 状态正常 (status: {account_status})")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ API封号检测调用失败: HTTP {response.status}，继续使用之前的检测结果")
        
    except Exception as real_time_check_error:
        logger.error(f"[任务{task_id}] ❌ 实时封号检测异常: {real_time_check_error}，继续使用之前的检测结果")
    
    # 返回最终的封号状态
    final_status = "已封号" if is_suspended else "正常"
    logger.info(f"[任务{task_id}] 🎯 实时封号检测完成: {account['username']} -> {final_status}")
    return is_suspended
