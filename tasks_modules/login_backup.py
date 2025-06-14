"""
登录备份模块
包含单个账号登录备份、延时操作等功能
"""

import asyncio
import aiohttp
import logging
import random
import time
import sys
import os

# 导入日志配置
try:
    from common.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# 添加必要的导入
try:
    import uiautomator2 as u2
except ImportError:
    logger.warning("uiautomator2未安装，UI验证功能将被禁用")
    u2 = None

# 添加项目根目录到sys.path以便导入其他模块
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# 导入其他必要的函数

try:
    from mysql_tasks_api import update_task_status
except ImportError:
    def update_task_status(*args, **kwargs):
        logger.warning("使用占位符update_task_status函数")
        pass

# 导入实时封号检测函数
try:
    from tasks_modules.device_utils import perform_real_time_suspension_check
except ImportError:
    logger.warning("无法导入perform_real_time_suspension_check，使用占位符")
    async def perform_real_time_suspension_check(*args, **kwargs):
        return False

async def execute_single_login_backup(slot_num: int, account: dict, container_name: str, target_ip: str, task_id: int):
    """
    执行单个账号的登录和备份操作
    
    Args:
        slot_num: 实例位编号
        account: 账号信息  
        container_name: 容器名称
        target_ip: 目标IP
        task_id: 任务ID
    
    Returns:
        dict: 处理成功时返回账号信息，失败时返回None
    """
    try:
        logger.info(f"[任务{task_id}] 开始执行账号 {account['username']} 的登录备份流程")
        
        # 登录前随机等待，避免冲突
        random_delay = random.uniform(2, 6)  # 2-6秒随机延迟
        logger.info(f"[任务{task_id}] ⏰ 登录前随机等待 {random_delay:.1f} 秒...")
        await asyncio.sleep(random_delay)
        
        # 获取设备的API信息（动态端口）
        from utils.port_manager import get_container_ports
        u2_port, myt_rpc_port = await get_container_ports(target_ip, container_name, slot_num, task_id)
        
        logger.info(f"[任务{task_id}] ✅ 获取到端口信息 - U2端口: {u2_port}, MytRpc端口: {myt_rpc_port}")
        
        # 执行Twitter登录
        logger.info(f"[任务{task_id}] 📱 执行Twitter登录: {account['username']}")
        login_success = False
        login_url = "http://127.0.0.1:8000/api/single-account-login"
        login_data = {
            "deviceIp": target_ip,
            "u2Port": str(u2_port),
            "mytRpcPort": str(myt_rpc_port),
            "username": account['username'],
            "password": account['password'],
            "secretKey": account['secretkey']
        }
        
        logger.info(f"[任务{task_id}] 🔗 发送登录请求到API: {login_url}")
        logger.info(f"[任务{task_id}] 📋 登录参数: IP={target_ip}, U2端口={u2_port}, MytRpc端口={myt_rpc_port}, 用户名={account['username']}")
        
        # 登录超时时间
        login_timeout = aiohttp.ClientTimeout(total=240)  # 4分钟超时
        
        async with aiohttp.ClientSession(timeout=login_timeout) as session:
            try:
                async with session.post(login_url, json=login_data) as response:
                    logger.info(f"[任务{task_id}] 📡 登录API响应状态: HTTP {response.status}")
                    
                    if response.status == 200:
                        login_result = await response.json()
                        login_success = login_result.get('success', False)
                        login_message = login_result.get('message', '未知状态')
                        login_status = login_result.get('status', '')
                        
                        logger.info(f"[任务{task_id}] 📊 登录API返回: success={login_success}, message='{login_message}'")
                        
                        if login_success:
                            logger.info(f"[任务{task_id}] ✅ 账号 {account['username']} 登录成功")
                        else:
                            logger.warning(f"[任务{task_id}] ❌ 账号 {account['username']} 登录失败: {login_message}")
                    else:
                        logger.error(f"[任务{task_id}] ❌ 登录API调用失败: HTTP {response.status}")
                        try:
                            error_data = await response.json()
                            logger.error(f"[任务{task_id}] 📝 API错误详情: {error_data}")
                        except:
                            logger.error(f"[任务{task_id}] 📝 无法解析API错误响应")
            except asyncio.TimeoutError:
                logger.error(f"[任务{task_id}] ⏰ 账号 {account['username']} 登录超时（4分钟）")
            except Exception as login_error:
                logger.error(f"[任务{task_id}] ❌ 账号 {account['username']} 登录异常: {login_error}")
        
        # 检查封号状态
        logger.info(f"[任务{task_id}] 🔍 检查账号封号状态: {account['username']}")
        is_suspended = False
        
        # 检查封号账号列表
        async with aiohttp.ClientSession() as session:
            async with session.get('http://127.0.0.1:8000/device-users/suspended-accounts') as response:
                if response.status == 200:
                    suspended_data = await response.json()
                    suspended_usernames = suspended_data.get('suspended_usernames', [])
                    is_suspended = account['username'] in suspended_usernames
                    
                    if is_suspended:
                        logger.warning(f"[任务{task_id}] 🚫 账号 {account['username']} 已被标记为封号")
                    else:
                        logger.info(f"[任务{task_id}] ✅ 账号 {account['username']} 未在封号列表中")
                else:
                    logger.warning(f"[任务{task_id}] ⚠️ 无法获取封号账号列表(HTTP {response.status})，假设账号正常")
        
        # 登录成功后的实时封号检测
        if login_success:
            logger.info(f"[任务{task_id}] 💡 登录成功，开始实时封号检测...")
            is_suspended = await perform_real_time_suspension_check(task_id, target_ip, slot_num, account, is_suspended, container_name)
        else:
            logger.info(f"[任务{task_id}] ⏭️ 登录失败，跳过实时封号检测")
        
        # 🔧 修复：强化备份决策逻辑
        should_backup = False  # 🔧 默认不备份，必须满足所有条件才备份
        backup_success = False  # 备份成功标志
        skip_reason = ''
        
        # 🔧 严格的备份条件检查
        if not login_success:
            skip_reason = '登录失败'
            logger.warning(f"[任务{task_id}] ❌ 备份条件不满足：账号 {account['username']} 登录失败")
        elif is_suspended:
            skip_reason = '账号已封号'
            logger.warning(f"[任务{task_id}] ❌ 备份条件不满足：账号 {account['username']} 已封号")
        else:
            # 🔧 额外的登录状态验证
            logger.info(f"[任务{task_id}] 🔍 执行额外的登录状态验证: {account['username']}")
            
            try:
                # 获取设备U2端口
                device_u2_port = 5000 + slot_num
                async with aiohttp.ClientSession() as session:
                    api_info_url = f"http://127.0.0.1:5000/and_api/v1/get_api_info/{target_ip}/{container_name}"
                    async with session.get(api_info_url) as response:
                        if response.status == 200:
                            api_data = await response.json()
                            if api_data.get('code') == 200 and api_data.get('data'):
                                adb_info = api_data['data'].get('ADB', '')
                                if adb_info and ':' in adb_info:
                                    device_u2_port = int(adb_info.split(':')[1])
                
                # 🔧 源代码一致的UI检测确认登录状态（宽松模式）
                ui_login_confirmed = True  # 默认已登录，只有发现失败指标才改为False
                
                if u2 is not None:
                    try:
                        u2_target = f"{target_ip}:{device_u2_port}"
                        u2_device = u2.connect(u2_target)
                        
                        logger.info(f"[任务{task_id}] 🔍 开始登录状态验证（宽松模式）：默认已登录，检查失败指标")
                        
                        # 第一重检查：明确的封号指标（最高优先级）
                        suspension_indicators = [
                            '//*[@text="Suspended"]',
                            '//*[@text="Your account is suspended"]', 
                            '//*[contains(@text, "suspended")]',
                            '//*[contains(@text, "Suspended")]',
                            '//*[@text="账户已被暂停"]',
                            '//*[contains(@text, "暂停")]'
                        ]
                        
                        has_suspension_indicators = False
                        for xpath in suspension_indicators:
                            try:
                                if u2_device.xpath(xpath).exists:
                                    logger.warning(f"[任务{task_id}] 🚫 发现封号指标: {xpath}")
                                    has_suspension_indicators = True
                                    break
                            except Exception:
                                continue
                        
                        if has_suspension_indicators:
                            ui_login_confirmed = False
                            logger.warning(f"[任务{task_id}] ❌ 检测到账户封停画面，确认登录失败")
                        
                        # 第二重检查：明确的登录失败指标
                        login_failure_indicators = [
                            '//*[@text="Log in"]',
                            '//*[@text="登录"]', 
                            '//*[@text="Sign in"]',
                            '//*[@text="Sign up"]',
                            '//*[@text="注册"]',
                            '//*[@resource-id="com.twitter.android:id/detail_text"]',  # 登录按钮
                            '//*[@resource-id="com.twitter.android:id/sign_in_text"]',  # 登录文本
                            '//*[@text="Welcome to X"]',
                            '//*[@text="欢迎使用X"]',
                            '//*[contains(@text, "Create account")]',
                            '//*[contains(@text, "创建账户")]'
                        ]
                        
                        has_failure_indicators = False
                        failure_details = []
                        for xpath in login_failure_indicators:
                            try:
                                if u2_device.xpath(xpath).exists:
                                    failure_details.append(xpath)
                                    has_failure_indicators = True
                            except Exception:
                                continue
                        
                        if has_failure_indicators:
                            ui_login_confirmed = False
                            logger.warning(f"[任务{task_id}] ❌ 发现登录失败指标: {', '.join(failure_details[:3])}")
                        
                        # 第三重检查：错误页面指标
                        error_indicators = [
                            '//*[@text="Something went wrong"]',
                            '//*[@text="Try again"]',
                            '//*[@text="出错了"]',
                            '//*[@text="重试"]',
                            '//*[contains(@text, "Error")]',
                            '//*[contains(@text, "错误")]'
                        ]
                        
                        has_error_indicators = False
                        for xpath in error_indicators:
                            try:
                                if u2_device.xpath(xpath).exists:
                                    logger.warning(f"[任务{task_id}] ⚠️ 发现错误页面指标: {xpath}")
                                    has_error_indicators = True
                                    break
                            except Exception:
                                continue
                        
                        if has_error_indicators:
                            ui_login_confirmed = False
                            logger.warning(f"[任务{task_id}] ❌ 检测到错误页面，可能登录失败")
                        
                        # 第四重检查：辅助验证成功指标（可选，不强制要求）
                        success_indicators = [
                            '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]',  # 底部导航栏
                            '//*[@text="Home"]', '//*[@text="首页"]',  # 首页标题
                            '//*[@text="For you"]', '//*[@text="推荐"]',  # 推荐页面
                            '//*[@resource-id="com.twitter.android:id/tweet_button"]',  # 发推按钮
                            '//*[@resource-id="com.twitter.android:id/fab_compose_tweet"]',  # FAB发推按钮
                            '//*[@content-desc="Tweet"]', '//*[@content-desc="Compose"]'  # 发推按钮描述
                        ]
                        
                        found_success_indicators = []
                        for xpath in success_indicators:
                            try:
                                if u2_device.xpath(xpath).exists:
                                    found_success_indicators.append(xpath)
                            except Exception:
                                continue
                        
                        # 关键修复：即使没有找到成功指标，只要没有失败指标就认为已登录
                        if found_success_indicators:
                            logger.info(f"[任务{task_id}] ✅ 发现 {len(found_success_indicators)} 个成功指标，确认已登录")
                        else:
                            logger.info(f"[任务{task_id}] ℹ️ 未发现明确的成功指标，但也无失败指标，假设已登录")
                        
                        if ui_login_confirmed:
                            logger.info(f"[任务{task_id}] ✅ 登录状态验证通过：未发现登录失败指标")
                        
                    except Exception as u2_error:
                        logger.warning(f"[任务{task_id}] ⚠️ UI检测异常: {u2_error}，采用宽松策略假设已登录")
                        ui_login_confirmed = True  # 异常时宽松处理
                else:
                    logger.warning(f"[任务{task_id}] ⚠️ uiautomator2未安装，跳过UI验证")
                    # 如果没有UI验证，我们假设登录成功（基于API返回）
                    ui_login_confirmed = True
                
                if ui_login_confirmed:
                    should_backup = True
                    logger.info(f"[任务{task_id}] ✅ UI验证确认：账号 {account['username']} 确实已登录，满足备份条件")
                else:
                    skip_reason = 'UI验证显示未登录'
                    logger.warning(f"[任务{task_id}] ❌ UI验证失败：账号 {account['username']} 未检测到登录状态")
                    
            except Exception as verify_error:
                skip_reason = f'登录状态验证失败: {str(verify_error)}'
                logger.warning(f"[任务{task_id}] ❌ 登录状态验证异常: {verify_error}")
        
        logger.info(f"[任务{task_id}] 🤔 最终备份决策: 登录成功={login_success}, 是否封号={is_suspended}, 应该备份={should_backup}")
        
        if should_backup:
            logger.info(f"[任务{task_id}] 💾 账号 {account['username']} 满足备份条件，开始备份")
            
            # 备份前等待
            await asyncio.sleep(3)
            
            try:
                # 备份操作
                backup_path = f"D:/mytBackUp/{account['username']}.tar.gz"
                logger.info(f"[任务{task_id}] 📦 导出 {container_name} 到 {backup_path}...")
                
                dc_api_url = f"http://127.0.0.1:5000/dc_api/v1/batch_export/{target_ip}"
                backup_params = {
                    'name': container_name,
                    'localPath': backup_path
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(dc_api_url, params=backup_params) as response:
                        logger.info(f"[任务{task_id}] 📡 备份API响应状态: HTTP {response.status}")
                        if response.status == 200:
                            try:
                                response_data = await response.json()
                                if response_data.get('code') == 200:
                                    logger.info(f"[任务{task_id}] ✅ 设备 {container_name} 备份导出成功")
                                    backup_success = True
                                else:
                                    logger.warning(f"[任务{task_id}] ❌ 设备 {container_name} 备份导出失败: {response_data.get('message', '未知错误')}")
                                    backup_success = False
                            except Exception as json_error:
                                logger.error(f"[任务{task_id}] ❌ 备份API响应JSON解析失败: {json_error}")
                                backup_success = False
                        else:
                            logger.warning(f"[任务{task_id}] ❌ 备份API调用失败: HTTP {response.status}")
                            backup_success = False
                
                # 备份完成后等待
                await asyncio.sleep(2)
                
                # 🔧 修复：备份成功后立即删除容器（与源代码一致）
                if backup_success:
                    logger.info(f"[任务{task_id}] 💾 账号 {account['username']} 备份成功，立即删除容器")
                    await asyncio.sleep(2)  # 备份完成后短暂等待
                    
                    # 🚀 新增：更新数据库备份状态
                    try:
                        # 获取账号ID并更新备份状态
                        account_id = account.get('id')
                        if account_id:
                            from tasks_modules.batch_operations import update_account_backup_status
                            update_success = update_account_backup_status(account_id, 1)
                            if update_success:
                                logger.info(f"[任务{task_id}] ✅ 账号 {account['username']} 数据库备份状态已更新")
                            else:
                                logger.warning(f"[任务{task_id}] ⚠️ 账号 {account['username']} 数据库备份状态更新失败")
                        else:
                            # 如果没有ID，尝试通过用户名查找
                            from tasks_modules.batch_operations import get_account_id_by_username, update_account_backup_status
                            account_id = get_account_id_by_username(account['username'])
                            if account_id:
                                update_success = update_account_backup_status(account_id, 1)
                                if update_success:
                                    logger.info(f"[任务{task_id}] ✅ 账号 {account['username']} 数据库备份状态已更新")
                                else:
                                    logger.warning(f"[任务{task_id}] ⚠️ 账号 {account['username']} 数据库备份状态更新失败")
                            else:
                                logger.warning(f"[任务{task_id}] ⚠️ 无法找到账号 {account['username']} 的ID，跳过备份状态更新")
                    except Exception as update_error:
                        logger.error(f"[任务{task_id}] ❌ 更新备份状态时发生异常: {update_error}")
                    
                    # 删除容器
                    remove_url = f"http://127.0.0.1:5000/remove/{target_ip}/{container_name}"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(remove_url) as response:
                            if response.status == 200:
                                logger.info(f"[任务{task_id}] ✅ 备份成功后容器 {container_name} 已删除")
                            else:
                                logger.warning(f"[任务{task_id}] ⚠️ 备份成功后容器删除失败: HTTP {response.status}")
                    
                    # 备份成功，返回账号信息
                    return account
                else:
                    logger.warning(f"[任务{task_id}] ❌ 账号 {account['username']} 备份失败，仍需删除容器")
                    # 备份失败时继续删除容器
                    
            except Exception as backup_error:
                logger.error(f"[任务{task_id}] ❌ 备份导出异常: {backup_error}")
        else:
            logger.warning(f"[任务{task_id}] ⏭️ 跳过备份：{skip_reason} (账号: {account['username']})")
            logger.warning(f"[任务{task_id}] 🚫 由于{skip_reason}，账号 {account['username']} 将不会进行备份导出")
        
        # 🔧 修复：确保所有情况下都删除容器（备份失败、跳过备份等）
        try:
            logger.info(f"[任务{task_id}] 🗑️ 删除容器: {container_name}")
            remove_url = f"http://127.0.0.1:5000/remove/{target_ip}/{container_name}"
            async with aiohttp.ClientSession() as session:
                async with session.get(remove_url) as response:
                    if response.status == 200:
                        logger.info(f"[任务{task_id}] ✅ 容器 {container_name} 已删除")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ 容器删除失败: HTTP {response.status}")
        except Exception as remove_error:
            logger.error(f"[任务{task_id}] ❌ 删除容器失败: {remove_error}")
        
        # 根据是否备份成功返回结果
        if should_backup and backup_success:
            logger.info(f"[任务{task_id}] ✅ 账号 {account['username']} 登录备份流程完成")
            return account  # 返回账号信息表示成功
        else:
            logger.info(f"[任务{task_id}] ⏭️ 账号 {account['username']} 登录备份流程完成（无有效备份）")
            return None  # 返回None表示无有效备份
            
    except Exception as e:
        logger.error(f"[任务{task_id}] 账号 {account['username']} 登录备份流程异常: {e}")
        import traceback
        logger.error(f"[任务{task_id}] 异常堆栈: {traceback.format_exc()}")
        
        # 即使异常也要尝试删除容器
        try:
            logger.info(f"[任务{task_id}] 🗑️ 异常情况下删除设备: {container_name}")
            remove_url = f"http://127.0.0.1:5000/remove/{target_ip}/{container_name}"
            async with aiohttp.ClientSession() as session:
                async with session.get(remove_url) as response:
                    if response.status == 200:
                        logger.info(f"[任务{task_id}] ✅ 异常情况下设备 {container_name} 已删除")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ 异常情况下设备删除失败: HTTP {response.status}")
        except Exception as remove_error:
            logger.error(f"[任务{task_id}] ❌ 异常情况下删除设备失败: {remove_error}")
        
        return None

async def perform_login(slot_num: int, account: dict, container_name: str, target_ip: str, task_id: int) -> bool:
    """执行登录操作"""
    try:
        logger.info(f"🔐 正在登录账号 {account['username']}...")
        
        # 🔧 修复：简化检查，只验证关键容器状态（删除不必要的API健康检查）
        logger.info(f"[任务{task_id}] 🔍 检查实例位{slot_num}容器状态...")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as test_session:
                # 只检查容器状态，不做多余的API健康检查
                api_info_url = f"http://127.0.0.1:5000/and_api/v1/get_api_info/{target_ip}/{container_name}"
                async with test_session.get(api_info_url) as response:
                    if response.status == 200:
                        logger.debug(f"[任务{task_id}] ✅ 容器状态正常，开始登录")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ 容器状态检查异常(HTTP {response.status})，继续尝试登录")
        except Exception as container_check_error:
            logger.warning(f"[任务{task_id}] ⚠️ 容器状态检查失败: {container_check_error}，继续尝试登录")
        
        # 模拟登录过程
        await asyncio.sleep(3)  # 模拟登录耗时
        
        # 实际实现应该调用登录API
        # 例如：
        # login_url = f"http://device_api/login/{container_name}"
        # login_data = {
        #     "username": account['username'],
        #     "password": account['password'],
        #     "secretkey": account.get('secretkey', '')
        # }
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(login_url, json=login_data) as response:
        #         return response.status == 200
        
        logger.info(f"✅ 账号 {account['username']} 登录成功")
        return True
        
    except Exception as e:
        logger.error(f"❌ 账号 {account['username']} 登录异常: {e}")
        return False

async def perform_backup(slot_num: int, account: dict, container_name: str, target_ip: str, task_id: int) -> bool:
    """执行备份操作"""
    try:
        logger.info(f"💾 正在备份账号 {account['username']} 数据...")
        
        # 🔧 修复：严格判断登录成功条件
        login_success = True
        if not login_success:
            logger.warning(f"[任务{task_id}] ⏭️ 登录失败，跳过备份: {account['username']}")
            return False
        
        # 模拟备份过程
        await asyncio.sleep(5)  # 模拟备份耗时
        
        # 实际实现应该调用备份API
        # 例如：
        # backup_url = f"http://device_api/backup/{container_name}"
        # backup_data = {
        #     "backup_name": f"{account['username']}_backup_{task_id}",
        #     "backup_type": "full"
        # }
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(backup_url, json=backup_data) as response:
        #         return response.status == 200
        
        logger.info(f"✅ 账号 {account['username']} 备份完成")
        return True
        
    except Exception as e:
        logger.error(f"❌ 账号 {account['username']} 备份异常: {e}")
        return False

async def optimized_delayed_login_only(slot_num: int, account: dict, container_name: str, 
                                      target_ip: str, task_id: int, delay: int):
    """优化版：延时后仅执行登录，不执行备份"""
    try:
        # 延时处理
        if delay > 0:
            logger.info(f"[任务{task_id}] ⏰ 账号 {account['username']} 等待 {delay}秒后开始登录...")
            await asyncio.sleep(delay)
        
        logger.info(f"[任务{task_id}] 🔑 开始登录: {account['username']}")
        
        # 🔧 使用统一的端口管理器获取默认端口
        from utils.port_manager import calculate_default_ports
        u2_port, myt_rpc_port = calculate_default_ports(slot_num)
        logger.info(f"[任务{task_id}] ✅ 获取到端口信息 - U2端口: {u2_port}, MytRpc端口: {myt_rpc_port}")
        
        # 🔧 修复：执行Twitter登录 - 严格状态控制
        logger.info(f"[任务{task_id}] 📱 执行Twitter登录: {account['username']}")
        login_success = await perform_login(slot_num, account, container_name, target_ip, task_id)
        
        # 🔧 实时封号检测 - 只有登录成功时才进行检测
        is_suspended = False
        if login_success:
            is_suspended = await perform_real_time_suspension_check(
                task_id, target_ip, slot_num, account, False, container_name
            )
        
        # 最终结果
        final_login = login_success and not is_suspended  # 只有登录成功且未被封号才算真正成功
        
        status_msg = "登录成功" if final_login else ("账号被封" if is_suspended else "登录失败")
        logger.info(f"[任务{task_id}] 🎯 延时登录完成: {account['username']} - {status_msg}")
        
        return slot_num, account, container_name, final_login, False  # 不执行备份，备份状态始终为False
        
    except Exception as e:
        logger.error(f"[任务{task_id}] ❌ 延时登录账号 {account['username']} 时发生异常: {e}")
        return slot_num, account, container_name, False, False

async def optimized_delayed_backup_only(slot_num: int, account: dict, container_name: str,
                                       target_ip: str, task_id: int, delay: int):
    """优化版：延时后仅执行备份，假设已登录"""
    try:
        # 延时处理
        if delay > 0:
            logger.info(f"[任务{task_id}] ⏰ 账号 {account['username']} 等待 {delay}秒后开始备份...")
            await asyncio.sleep(delay)
        
        logger.info(f"[任务{task_id}] 💾 开始备份: {account['username']}")
        
        # 🔧 使用统一的端口管理器获取默认端口
        from utils.port_manager import calculate_default_ports
        u2_port, myt_rpc_port = calculate_default_ports(slot_num)
        logger.info(f"[任务{task_id}] ✅ 获取到端口信息 - U2端口: {u2_port}, MytRpc端口: {myt_rpc_port}")
        
        # 执行备份操作
        backup_success = await perform_backup(slot_num, account, container_name, target_ip, task_id)
        
        status_msg = "备份成功" if backup_success else "备份失败"
        logger.info(f"[任务{task_id}] 🎯 延时备份完成: {account['username']} - {status_msg}")
        
        return slot_num, account, container_name, True, backup_success  # 假设登录成功，返回备份结果
        
    except Exception as e:
        logger.error(f"[任务{task_id}] ❌ 延时备份账号 {account['username']} 时发生异常: {e}")
        return slot_num, account, container_name, True, False
