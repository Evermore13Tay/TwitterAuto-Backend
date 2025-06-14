import time
import os
import sys
from datetime import datetime
from sqlalchemy.orm import Session
from db.database import SessionLocal
from suspended_account import SuspendedAccount

def handle_update_now_dialog(u2_d, mytapi, status_callback, device_info=""):
    """检查Twitter更新对话框，如果存在则关闭并重新打开应用"""
    try:
        if u2_d.xpath('//*[@text="Update now"]').exists:
            status_callback(f"{device_info}检测到'立即更新'对话框，关闭并重新启动Twitter...")
            
            # 关闭Twitter应用
            u2_d.app_stop("com.twitter.android")
            status_callback(f"{device_info}已关闭Twitter应用")
            time.sleep(5)
            
            # 重新启动Twitter应用
            u2_d.app_start("com.twitter.android")
            status_callback(f"{device_info}已重新启动Twitter应用")
            time.sleep(5)  # 等待应用启动
    except Exception as e:
        status_callback(f"{device_info}处理更新对话框时出错: {e}")

def handle_keep_less_relevant_ads(u2_d, mytapi, status_callback, device_info=""):
    """处理'保留不太相关的广告'对话框"""
    try:
        # 检查是否存在"Keep less relevant ads"对话框
        if u2_d(text="Keep less relevant ads").exists:
            status_callback(f"{device_info}检测到'保留不太相关的广告'对话框，尝试关闭...")
            
            # 使用click_exists()直接点击按钮
            if u2_d(text="Keep less relevant ads").click_exists(timeout=1.0):
                status_callback(f"{device_info}已点击'保留不太相关的广告'按钮")
                time.sleep(1)
            else:
                status_callback(f"{device_info}未找到'保留不太相关的广告'按钮")
    except Exception as e:
        status_callback(f"{device_info}处理广告对话框时出错: {e}")

def check_account_suspended(u2_d, mytapi, status_callback, device_info="", username=None, device_name=None):
    """
    检查Twitter账户是否被封停，如果被封停则记录到数据库中
    
    Args:
        u2_d: uiautomator2设备对象
        mytapi: MytRpc对象
        status_callback: 状态回调函数
        device_info: 设备信息前缀，用于日志显示
        username: 用户名，用于记录到数据库
        device_name: 设备名称，用于记录到数据库
    
    Returns:
        bool: 如果账户被封停返回True，否则返回False
    """
    try:
        status_callback(f"{device_info}检查账户是否被封停...")
        
        # 检查是否存在标题为 "Suspended" 的警告对话框
        suspended_alert = u2_d.xpath('//*[@resource-id="com.twitter.android:id/alertTitle"]')
        
        if suspended_alert.exists:
            alert_text = suspended_alert.get_text()
            status_callback(f"{device_info}发现警告对话框: {alert_text}")
            
            # 检查对话框内容是否包含 "suspended" 字样
            if "Suspended" in alert_text or "suspended" in alert_text:
                status_callback(f"{device_info}账户已被封停！")
                
                # 尝试获取账户名称
                account_name = None
                try:
                    # 尝试从对话框内容中提取账户名
                    account_text_element = u2_d.xpath('//*[@resource-id="android:id/message"]')
                    if account_text_element.exists:
                        message_text = account_text_element.get_text()
                        status_callback(f"{device_info}封停消息: {message_text}")
                        
                        # 尝试从消息中提取账户名 (@username)
                        import re
                        account_match = re.search(r'@([\w\d_]+)', message_text)
                        if account_match:
                            account_name = account_match.group(1)
                            status_callback(f"{device_info}从消息中提取的账户名: {account_name}")
                except Exception as e:
                    status_callback(f"{device_info}提取账户名时出错: {e}")
                
                # 如果无法从消息中提取账户名，则使用传入的username参数
                if not account_name and username:
                    account_name = username
                    status_callback(f"{device_info}使用传入的账户名: {account_name}")
                
                # 将封停账户信息保存到数据库
                if account_name:
                    try:
                        device_ip = device_info.strip('[]').split(':')[0] if device_info else ""
                        
                        # 创建数据库会话
                        db = SessionLocal()
                        
                        # 检查是否已存在该账户的记录
                        existing_record = db.query(SuspendedAccount).filter(
                            SuspendedAccount.username == account_name
                        ).first()
                        
                        if not existing_record:
                            # 创建新记录
                            suspended_account = SuspendedAccount(
                                username=account_name,
                                device_ip=device_ip,
                                device_name=device_name,
                                suspended_at=datetime.utcnow(),
                                details=message_text if 'message_text' in locals() else "Account suspended"
                            )
                            db.add(suspended_account)
                            db.commit()
                            status_callback(f"{device_info}已将封停账户 {account_name} 记录到数据库")
                        else:
                            status_callback(f"{device_info}账户 {account_name} 已存在于封停记录中")
                            
                        db.close()
                    except Exception as e:
                        status_callback(f"{device_info}保存封停账户到数据库时出错: {e}")
                
                return True
        
        return False
    except Exception as e:
        status_callback(f"{device_info}检查账户封停状态时出错: {e}")
        return False

def ensure_twitter_app_running_and_logged_in(u2_d, mytapi, status_callback, device_info="", username=None, device_name=None):
    """
    确保Twitter应用正在运行且用户已登录
    
    Args:
        u2_d: uiautomator2设备对象
        mytapi: MytRpc对象
        status_callback: 状态回调函数
        device_info: 设备信息前缀，用于日志显示
        username: 用户名，用于检查账户封停
        device_name: 设备名称，用于记录封停账户
    
    Returns:
        bool: 如果应用正在运行且已登录，则返回True；否则返回False
    """
    twitter_package = "com.twitter.android"
    status_callback(f"{device_info}检查Twitter应用是否运行并已登录...")
    
    # 🆕 增强重试机制：最多重试3次
    max_retries = 3
    
    for retry_count in range(max_retries):
        try:
            status_callback(f"{device_info}尝试 {retry_count + 1}/{max_retries}：检查Twitter应用状态...")
            
            # 第一次尝试或重试时都重启应用
            status_callback(f"{device_info}重启Twitter应用以清除可能的弹窗...")
            u2_d.app_stop(twitter_package)
            time.sleep(3)  # 等待应用完全关闭
            
            u2_d.app_start(twitter_package)
            time.sleep(6)  # 等待应用启动和加载
            
            # 检查账户是否被封停
            if check_account_suspended(u2_d, mytapi, status_callback, device_info, username, device_name):
                status_callback(f"{device_info}检测到账户被封停，停止后续操作")
                return False
            
            # 🆕 强化弹窗处理 - 检查并处理各种可能的弹窗
            status_callback(f"{device_info}检查并处理可能的弹窗...")
            
            # 处理更新对话框
            if u2_d.xpath('//*[@text="Update now"]').exists:
                status_callback(f"{device_info}检测到'立即更新'对话框，尝试关闭...")
                # 尝试点击"不，谢谢"或关闭按钮
                if u2_d.xpath('//*[@text="Not now"]').click_exists(timeout=2):
                    status_callback(f"{device_info}已点击'不，谢谢'按钮")
                elif u2_d.xpath('//*[@text="Later"]').click_exists(timeout=2):
                    status_callback(f"{device_info}已点击'稍后'按钮")
                elif u2_d.xpath('//*[@content-desc="Close"]').click_exists(timeout=2):
                    status_callback(f"{device_info}已点击关闭按钮")
                else:
                    status_callback(f"{device_info}无法找到关闭更新对话框的按钮，跳过此次检查")
                    continue  # 重试
                time.sleep(2)
            
            # 处理广告相关对话框
            if u2_d(text="Keep less relevant ads").exists:
                status_callback(f"{device_info}检测到'保留不太相关的广告'对话框...")
                if u2_d(text="Keep less relevant ads").click_exists(timeout=2):
                    status_callback(f"{device_info}已点击'保留不太相关的广告'按钮")
                time.sleep(2)
            
            # 处理可能的权限请求对话框
            if u2_d.xpath('//*[@text="Allow"]').exists:
                status_callback(f"{device_info}检测到权限请求对话框，点击允许...")
                u2_d.xpath('//*[@text="Allow"]').click_exists(timeout=2)
                time.sleep(2)
            
            # 处理通知权限对话框
            if u2_d.xpath('//*[@text="Turn on notifications"]').exists:
                status_callback(f"{device_info}检测到通知权限对话框...")
                # 尝试点击"不，谢谢"或跳过
                if u2_d.xpath('//*[@text="Not now"]').click_exists(timeout=2):
                    status_callback(f"{device_info}已跳过通知权限")
                elif u2_d.xpath('//*[@text="Skip"]').click_exists(timeout=2):
                    status_callback(f"{device_info}已跳过通知设置")
                time.sleep(2)
            
            # 🆕 检查是否有其他模态对话框需要关闭
            modal_dialogs = [
                '//*[@text="Got it"]',
                '//*[@text="OK"]',
                '//*[@text="Continue"]',
                '//*[@text="Dismiss"]',
                '//*[@content-desc="Dismiss"]',
                '//*[@resource-id="com.twitter.android:id/dismiss_button"]'
            ]
            
            for dialog_xpath in modal_dialogs:
                if u2_d.xpath(dialog_xpath).exists:
                    status_callback(f"{device_info}检测到对话框，尝试关闭: {dialog_xpath}")
                    if u2_d.xpath(dialog_xpath).click_exists(timeout=2):
                        status_callback(f"{device_info}已关闭对话框")
                        time.sleep(1)
            
            # 等待界面稳定
            time.sleep(3)
            
            # 🆕 增强登录状态检测
            status_callback(f"{device_info}检测登录状态...")
            
            # 检查是否已登录（通过检查关键UI元素）
            login_indicators = [
                {'type': 'xpath', 'value': '//*[@resource-id="com.twitter.android:id/channels"]', 'name': '底部导航栏'},
                {'type': 'xpath', 'value': '//*[@content-desc="Search and Explore"]', 'name': '搜索按钮'}, 
                {'type': 'xpath', 'value': '//*[@resource-id="com.twitter.android:id/composer_write"]', 'name': '发推按钮'},
                {'type': 'xpath', 'value': '//*[@content-desc="Home"]', 'name': '主页按钮'},
                {'type': 'xpath', 'value': '//*[@resource-id="com.twitter.android:id/timeline"]', 'name': '时间线'}
            ]
            
            logged_in = False
            found_indicators = []
            
            for indicator in login_indicators:
                try:
                    if indicator['type'] == 'xpath':
                        element = u2_d.xpath(indicator['value'])
                        if element.exists:
                            status_callback(f"{device_info}✅ 检测到登录指示器: {indicator['name']}")
                            found_indicators.append(indicator['name'])
                            logged_in = True
                except Exception as e:
                    status_callback(f"{device_info}检查登录指示器 {indicator['name']} 时出错: {e}")
            
            if logged_in:
                status_callback(f"{device_info}✅ 确认Twitter应用已运行且用户已登录 (发现指示器: {', '.join(found_indicators)})")
                return True
            
            # 检查是否在登录页面
            login_page_indicators = [
                '//*[@text="Log in"]',
                '//*[@text="登录"]',
                '//*[@text="Sign in"]',
                '//*[@text="Create account"]',
                '//*[@text="创建账户"]'
            ]
            
            on_login_page = False
            for login_indicator in login_page_indicators:
                if u2_d.xpath(login_indicator).exists:
                    status_callback(f"{device_info}❌ 检测到登录页面指示器: {login_indicator}")
                    on_login_page = True
                    break
            
            if on_login_page:
                status_callback(f"{device_info}❌ 用户需要重新登录")
                return False
            
            # 如果既没有登录指示器，也没有登录页面指示器，可能是页面还在加载或有其他弹窗
            status_callback(f"{device_info}⚠️ 未明确检测到登录状态，第 {retry_count + 1} 次尝试未成功")
            
            if retry_count < max_retries - 1:
                status_callback(f"{device_info}等待 3 秒后重试...")
                time.sleep(3)
                continue
            else:
                status_callback(f"{device_info}❌ 经过 {max_retries} 次尝试，仍无法确认登录状态")
                return False
                
        except Exception as e:
            status_callback(f"{device_info}尝试 {retry_count + 1} 时出错: {e}")
            if retry_count < max_retries - 1:
                status_callback(f"{device_info}等待 3 秒后重试...")
                time.sleep(3)
                continue
            else:
                status_callback(f"{device_info}❌ 所有重试都失败了")
                return False
    
    return False 