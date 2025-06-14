#!/usr/bin/env python3
"""
优化的登录服务模块
基于 batch_login_test.py 中验证成功的登录方法
使用 mytrpc_double 双击策略和验证有效的坐标
"""

import sys
import os
import time
import logging
from datetime import datetime
import uiautomator2 as u2
from common.mytRpc import MytRpc
import pyotp
import traceback

# 导入现有的工具函数
try:
    from common.u2_connection import connect_to_device
    from common.twitter_ui_handlers import handle_update_now_dialog, handle_keep_less_relevant_ads
except ImportError as e:
    logging.warning(f"部分依赖导入失败: {e}")

logger = logging.getLogger("TwitterAutomationAPI")

# 验证成功的配置常量
CLICK_METHOD = "mytrpc_double"  # 根据测试结果，双击方法成功率最高
U2_COORDS = (0.644, 0.947)     # 验证有效的登录按钮坐标
MYTRPC_COORDS = (463, 1212)    # 验证有效的MytRpc绝对坐标

class OptimizedLoginExecutor:
    """优化的登录执行器，基于batch_login_test.py中验证成功的方法"""
    
    def __init__(self, device_ip: str, u2_port: int, myt_rpc_port: int, 
                 username: str, password: str, secret_key: str, status_callback=None):
        self.device_ip = device_ip
        self.u2_port = u2_port
        self.myt_rpc_port = myt_rpc_port
        self.username = username
        self.password = password
        self.secret_key = secret_key
        self.status_callback = status_callback
        
        # 🔧 修复：初始化连接对象
        self.u2_d = None
        self.mytapi = None
        
        # 🔧 修复：使用验证有效的坐标
        self.mytrpc_x = MYTRPC_COORDS[0]  # 直接使用验证有效的绝对坐标
        self.mytrpc_y = MYTRPC_COORDS[1]
        
    def log(self, message: str):
        """日志输出"""
        logger.info(message)
        if self.status_callback and callable(self.status_callback):
            try:
                self.status_callback(message)
            except Exception as e:
                logger.warning(f"状态回调失败: {e}")
                
    def execute_login(self) -> tuple[bool, str]:
        """执行完整的登录流程"""
        try:
            # 步骤1: 建立连接
            if not self.establish_connections():
                return False, "设备连接失败"
            
            # 步骤2: 设置坐标（如果需要动态计算）
            if not self.setup_coordinates():
                return False, "坐标设置失败"
            
            # 步骤3: 检查是否已经登录
            if self.check_already_logged_in():
                self.log("✅ 账户已经登录，无需重新登录")
                return True, "已经登录"
            
            # 步骤4: 执行登录流程
            if not self.execute_login_flow():
                return False, "登录流程执行失败"
            
            # 步骤5: 处理登录后的对话框
            self.handle_post_login_dialogs()
            
            # 步骤6: 验证登录结果
            if self.verify_login_success():
                self.log("✅ 登录验证成功")
                return True, "登录成功"
            else:
                return False, "登录验证失败"
                
        except Exception as e:
            error_msg = f"登录执行异常: {str(e)}"
            self.log(f"❌ {error_msg}")
            return False, error_msg
        finally:
            # 清理连接资源
            self.cleanup_connections()
    
    def establish_connections(self) -> bool:
        """建立设备连接"""
        try:
            self.log("🔗 建立uiautomator2连接...")
            self.u2_d = u2.connect(f"{self.device_ip}:{self.u2_port}")
            
            self.log("🔗 建立MytRpc连接...")
            self.mytapi = MytRpc()
            
            # 🔧 修复：使用与batch_login_test.py相同的连接参数
            if not self.mytapi.init(self.device_ip, self.myt_rpc_port, 30):  # 30秒超时
                raise Exception("MytRpc连接失败")
            
            # 🔧 修复：检查连接状态
            if not self.mytapi.check_connect_state():
                raise Exception("MytRpc连接状态检查失败")
            
            self.log("✅ 设备连接建立成功")
            return True
            
        except Exception as e:
            self.log(f"❌ 设备连接失败: {e}")
            return False
    
    def setup_coordinates(self) -> bool:
        """设置坐标转换"""
        try:
            # 🔧 修复：支持动态坐标转换，但优先使用验证有效的固定坐标
            try:
                # 获取屏幕尺寸用于日志记录
                screen_width, screen_height = self.u2_d.window_size()
                self.log(f"📱 屏幕尺寸: {screen_width}x{screen_height}")
                
                # 计算动态坐标（仅用于对比）
                dynamic_x = int(U2_COORDS[0] * screen_width)
                dynamic_y = int(U2_COORDS[1] * screen_height)
                
                self.log(f"📍 坐标对比: 固定坐标({self.mytrpc_x}, {self.mytrpc_y}) vs 动态坐标({dynamic_x}, {dynamic_y})")
                
                # 🔧 关键修复：如果动态坐标与固定坐标差异很大，使用动态坐标
                if abs(dynamic_x - self.mytrpc_x) > 50 or abs(dynamic_y - self.mytrpc_y) > 50:
                    self.log(f"⚠️ 坐标差异较大，使用动态坐标")
                    self.mytrpc_x = dynamic_x
                    self.mytrpc_y = dynamic_y
                else:
                    self.log(f"✅ 使用验证有效的固定坐标")
                
            except Exception as coord_error:
                self.log(f"⚠️ 动态坐标计算失败，使用固定坐标: {coord_error}")
                # 保持使用验证有效的固定坐标
            
            self.log(f"📍 最终坐标: ({self.mytrpc_x}, {self.mytrpc_y})")
            return True
            
        except Exception as e:
            self.log(f"❌ 坐标设置失败: {e}")
            return False
    
    def check_already_logged_in(self) -> bool:
        """检查是否已经登录"""
        try:
            self.log("🔍 检查账户登录状态...")
            
            login_indicators = [
                '//*[@content-desc="Show navigation drawer"]',
                '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]',
                '//*[@content-desc="Home Tab"]',
                '//*[@resource-id="com.twitter.android:id/tweet_button"]',
                '//*[@content-desc="Search and Explore"]'
            ]
            
            for xpath in login_indicators:
                try:
                    if self.u2_d.xpath(xpath).exists:
                        self.log(f"✅ 发现登录指标: {xpath}")
                        return True
                except Exception:
                    continue
            
            self.log("📝 未发现登录指标，需要执行登录")
            return False
            
        except Exception as e:
            self.log(f"⚠️ 登录状态检查异常: {e}")
            return False
    
    def execute_login_flow(self) -> bool:
        """执行完整登录流程"""
        try:
            # Step 1: 重启Twitter应用
            self.log("🔄 重启Twitter应用...")
            self.restart_twitter_app()
            
            # Step 2: 点击登录按钮
            self.log("📍 点击登录按钮...")
            if not self.click_login_button():
                return False
            
            # Step 3: 输入用户名
            self.log("👤 输入用户名...")
            if not self.input_username():
                return False
            
            # Step 4: 输入密码
            self.log("🔐 输入密码...")
            if not self.input_password():
                return False
            
            # Step 5: 处理2FA验证
            self.log("🔢 处理2FA验证...")
            if not self.handle_2fa():
                return False
            
            # Step 6: 处理可能的对话框
            self.log("🔧 处理登录后对话框...")
            self.handle_post_login_dialogs()
            
            return True
            
        except Exception as e:
            self.log(f"❌ 登录流程异常: {e}")
            return False
    
    def restart_twitter_app(self):
        """重启Twitter应用"""
        try:
            self.mytapi.exec_cmd("am force-stop com.twitter.android")
            time.sleep(3)
            self.mytapi.exec_cmd("am start -n com.twitter.android/.StartActivity")
            time.sleep(10)
            self.log("✅ Twitter应用重启完成")
        except Exception as e:
            self.log(f"⚠️ 重启应用失败: {e}")
    
    def click_login_button(self) -> bool:
        """使用验证有效的双击方法点击登录按钮"""
        try:
            self.log(f"📍 使用{CLICK_METHOD}方法点击登录按钮...")
            
            if CLICK_METHOD == "mytrpc_double":
                # 第一次点击
                self.mytapi.touchDown(0, self.mytrpc_x, self.mytrpc_y)
                time.sleep(1.5)
                self.mytapi.touchUp(0, self.mytrpc_x, self.mytrpc_y)
                time.sleep(1)
                
                # 第二次点击（增强成功率）
                self.mytapi.touchDown(0, self.mytrpc_x, self.mytrpc_y)
                time.sleep(1.5)
                self.mytapi.touchUp(0, self.mytrpc_x, self.mytrpc_y)
                
                self.log("✅ 双击登录按钮完成，等待页面跳转")
                
                # 🔧 增强页面跳转等待和验证
                max_wait_time = 20  # 最多等待20秒
                wait_interval = 2   # 每2秒检查一次
                
                for wait_cycle in range(max_wait_time // wait_interval):
                    time.sleep(wait_interval)
                    
                    # 检查是否到达用户名输入页面
                    try:
                        if (self.u2_d(textContains='Phone, email, or username').exists or 
                            self.u2_d(textContains='手机、邮箱或用户名').exists or
                            self.u2_d(className='android.widget.EditText').exists):
                            self.log(f"✅ 页面跳转成功 (等待{(wait_cycle + 1) * wait_interval}秒)")
                            break
                    except Exception:
                        pass
                    
                    if wait_cycle == (max_wait_time // wait_interval) - 1:
                        self.log(f"⚠️ 页面跳转可能较慢，总共等待了{max_wait_time}秒")
                else:
                    # 如果循环正常结束（没有break），额外等待
                    time.sleep(2)
                
            elif CLICK_METHOD == "mytrpc_single":
                self.mytapi.touchDown(0, self.mytrpc_x, self.mytrpc_y)
                time.sleep(1.5)
                self.mytapi.touchUp(0, self.mytrpc_x, self.mytrpc_y)
                time.sleep(8)
                
            return True
            
        except Exception as e:
            self.log(f"❌ 点击登录按钮异常: {e}")
            return False
    
    def input_username(self) -> bool:
        """输入用户名"""
        try:
            # 🔧 增强页面等待和重试机制
            self.log("🔍 等待用户名输入页面加载...")
            time.sleep(5)  # 额外等待页面完全加载
            
            # 🔧 多次重试查找用户名输入框
            username_selectors = [
                {'method': 'textContains', 'value': 'Phone, email, or username'},
                {'method': 'textContains', 'value': '手机、邮箱或用户名'},
                {'method': 'textContains', 'value': 'Username'},
                {'method': 'textContains', 'value': '用户名'},
                {'method': 'class', 'value': 'android.widget.EditText'}
            ]
            
            username_field = None
            max_retries = 3
            
            for retry in range(max_retries):
                self.log(f"🔍 尝试查找用户名输入框 (第{retry + 1}次)")
                
                for selector in username_selectors:
                    try:
                        if selector['method'] == 'textContains':
                            username_field = self.u2_d(textContains=selector['value'])
                        elif selector['method'] == 'class':
                            username_field = self.u2_d(className=selector['value'])
                        
                        if username_field and username_field.exists:
                            self.log(f"✅ 找到用户名输入框: {selector['value']}")
                            break
                        else:
                            username_field = None
                    except Exception:
                        continue
                
                if username_field and username_field.exists:
                    break
                    
                if retry < max_retries - 1:
                    self.log(f"⏳ 未找到输入框，等待2秒后重试...")
                    time.sleep(2)
            
            if not username_field or not username_field.exists:
                self.log("❌ 多次重试后仍未找到用户名输入框")
                return False
            
            # 点击输入框
            bounds = username_field.info['bounds']
            center_x = (bounds['left'] + bounds['right']) // 2
            center_y = (bounds['top'] + bounds['bottom']) // 2
            
            self.mytapi.touchDown(0, center_x, center_y)
            time.sleep(1)
            self.mytapi.touchUp(0, center_x, center_y)
            time.sleep(1)
            
            # 🔧 修复：使用MytRpc逐字符输入用户名，与batch_login_test.py保持一致
            self.log(f"⌨️ 输入用户名: {self.username}")
            if not self.send_text_char_by_char(self.username):
                self.log("❌ 用户名输入失败")
                return False
            
            # 点击Next按钮
            next_button = self.u2_d.xpath('//*[@resource-id="com.twitter.android:id/cta_button"]//android.widget.Button')
            if next_button.exists:
                next_button.click()
                time.sleep(3)
                self.log("✅ 用户名输入完成，点击Next")
            
            return True
            
        except Exception as e:
            self.log(f"❌ 输入用户名异常: {e}")
            return False
    
    def input_password(self) -> bool:
        """输入密码"""
        try:
            # 查找密码输入框
            password_field = self.u2_d(text="Password")
            if not password_field.exists:
                password_field = self.u2_d(textContains="密码")
            if not password_field.exists:
                password_field = self.u2_d(className="android.widget.EditText", focused=True)
            if not password_field.exists:
                edit_texts = self.u2_d(className="android.widget.EditText")
                if edit_texts.count > 1:
                    password_field = edit_texts[1]
            
            if not password_field.exists:
                self.log("❌ 未找到密码输入框")
                return False
            
            # 点击输入框
            bounds = password_field.info['bounds']
            center_x = (bounds['left'] + bounds['right']) // 2
            center_y = (bounds['top'] + bounds['bottom']) // 2
            
            self.mytapi.touchDown(0, center_x, center_y)
            time.sleep(1)
            self.mytapi.touchUp(0, center_x, center_y)
            time.sleep(1)
            
            # 🔧 修复：使用MytRpc逐字符输入密码，与batch_login_test.py保持一致
            self.log(f"⌨️ 输入密码: {'*' * len(self.password)}")
            if not self.send_text_char_by_char(self.password):
                self.log("❌ 密码输入失败")
                return False
            
            # 点击Login按钮
            login_button = self.u2_d.xpath('//*[@resource-id="com.twitter.android:id/cta_button"]//android.widget.Button')
            if login_button.exists:
                login_button.click()
                time.sleep(5)
                self.log("✅ 密码输入完成，点击Login")
            
            return True
            
        except Exception as e:
            self.log(f"❌ 输入密码异常: {e}")
            return False
    
    def handle_2fa(self) -> bool:
        """🔧 修复：处理2FA验证，与batch_login_test.py保持一致"""
        try:
            # 等待页面加载
            time.sleep(3)
            
            # 🔧 修复：检查多种2FA页面指标
            tfa_indicators = [
                '//*[@resource-id="com.twitter.android:id/primary_text"]',
                '//*[@text="Enter your verification code"]',
                '//*[@text="输入验证码"]',
                '//*[contains(@text, "verification")]',
                '//*[contains(@text, "验证")]'
            ]
            
            found_2fa_page = False
            for indicator in tfa_indicators:
                try:
                    if self.u2_d.xpath(indicator).exists:
                        self.log(f"🔢 检测到2FA验证页面: {indicator}")
                        found_2fa_page = True
                        break
                except Exception:
                    continue
            
            if not found_2fa_page:
                self.log("⚠️ 未检测到2FA页面，可能已经登录或不需要2FA")
                return True
            
            # 检查是否有secret_key
            if not self.secret_key or len(self.secret_key.strip()) == 0:
                self.log("⚠️ 未提供2FA密钥，跳过2FA验证")
                return True
            
            # 🔧 修复：生成2FA代码
            try:
                import pyotp
                totp = pyotp.TOTP(self.secret_key.strip())
                tfa_code = totp.now()
                self.log(f"🔑 生成2FA代码: {tfa_code}")
            except Exception as totp_error:
                self.log(f"❌ 2FA代码生成失败: {totp_error}")
                return False
            
            # 🔧 修复：查找2FA输入框（尝试多种选择器）
            tfa_input_selectors = [
                '//*[@resource-id="com.twitter.android:id/text_field"]//android.widget.FrameLayout',
                '//*[@resource-id="com.twitter.android:id/text_field"]',
                '//*[@class="android.widget.EditText"]',
                '//*[contains(@resource-id, "verification")]'
            ]
            
            tfa_input = None
            for selector in tfa_input_selectors:
                try:
                    element = self.u2_d.xpath(selector)
                    if element.exists:
                        tfa_input = element
                        self.log(f"✅ 找到2FA输入框: {selector}")
                        break
                except Exception:
                    continue
            
            if not tfa_input:
                self.log("❌ 未找到2FA输入框")
                return False
            
            # 点击输入框
            try:
                bounds = tfa_input.info['bounds']
                center_x = (bounds['left'] + bounds['right']) // 2
                center_y = (bounds['top'] + bounds['bottom']) // 2
                
                self.mytapi.touchDown(0, center_x, center_y)
                time.sleep(1)
                self.mytapi.touchUp(0, center_x, center_y)
                time.sleep(1)
                
                self.log("✅ 点击2FA输入框成功")
            except Exception as click_error:
                self.log(f"⚠️ 点击2FA输入框失败，尝试直接输入: {click_error}")
            
            # 输入2FA代码
            if not self.send_text_char_by_char(tfa_code):
                self.log("❌ 2FA代码输入失败")
                return False
            
            # 🔧 修复：查找并点击Next按钮
            next_button_selectors = [
                '//*[@text="Next"]',
                '//*[@text="下一步"]',
                '//*[@resource-id="com.twitter.android:id/cta_button"]//android.widget.Button',
                '//*[contains(@text, "Next")]'
            ]
            
            next_clicked = False
            for selector in next_button_selectors:
                try:
                    button = self.u2_d.xpath(selector)
                    if button.exists:
                        button.click()
                        time.sleep(5)
                        self.log(f"✅ 点击Next按钮成功: {selector}")
                        next_clicked = True
                        break
                except Exception:
                    continue
            
            if not next_clicked:
                self.log("⚠️ 未找到Next按钮，尝试直接按Enter")
                try:
                    self.mytapi.pressEnter()
                    time.sleep(5)
                    self.log("✅ 按Enter键完成2FA验证")
                except Exception as enter_error:
                    self.log(f"❌ 按Enter键失败: {enter_error}")
                    return False
            
            self.log("✅ 2FA验证完成")
            return True
            
        except Exception as e:
            self.log(f"❌ 2FA处理异常: {e}")
            return False
    
    def handle_post_login_dialogs(self):
        """处理登录后可能出现的对话框"""
        try:
            # 使用现有的对话框处理函数
            if hasattr(handle_update_now_dialog, '__call__'):
                handle_update_now_dialog(self.u2_d, self.mytapi, self.status_callback)
            if hasattr(handle_keep_less_relevant_ads, '__call__'):
                handle_keep_less_relevant_ads(self.u2_d, self.mytapi, self.status_callback)
        except Exception as e:
            self.log(f"⚠️ 处理登录后对话框异常: {e}")
    
    def verify_login_success(self) -> bool:
        """验证登录是否成功"""
        try:
            # 等待页面加载
            time.sleep(5)
            
            # 🚀 [关键修复] 在检测登录成功指标之前，先处理可能的弹窗（参考twitter_ui_handlers.py）
            logger.info(f"🔍 [BATCH_COMPATIBLE] 检查并处理登录后弹窗...")
            if self.status_callback:
                self.status_callback("🔍 检查并处理登录后弹窗...")
            
            # 处理"Keep less relevant ads"对话框
            try:
                if self.u2_d(text="Keep less relevant ads").exists:
                    logger.info(f"✅ [BATCH_COMPATIBLE] 检测到'保留不太相关的广告'对话框，尝试关闭...")
                    if self.status_callback:
                        self.status_callback("✅ 检测到广告偏好对话框，尝试关闭...")
                    
                    if self.u2_d(text="Keep less relevant ads").click_exists(timeout=2):
                        logger.info(f"✅ [BATCH_COMPATIBLE] 已点击'保留不太相关的广告'按钮")
                        if self.status_callback:
                            self.status_callback("✅ 已处理广告偏好对话框")
                        time.sleep(2)
                    else:
                        logger.warning(f"⚠️ [BATCH_COMPATIBLE] 未能点击'保留不太相关的广告'按钮")
            except Exception as ads_error:
                logger.warning(f"⚠️ [BATCH_COMPATIBLE] 处理广告对话框时出错: {ads_error}")
            
            # 处理其他可能的弹窗
            try:
                # 处理"Turn on personalized ads"对话框
                if self.u2_d(text="Turn on personalized ads").exists:
                    logger.info(f"✅ [BATCH_COMPATIBLE] 检测到个性化广告对话框，尝试关闭...")
                    self.u2_d(text="Turn on personalized ads").click_exists(timeout=2)
                    time.sleep(2)
                
                # 处理通知权限对话框
                if self.u2_d.xpath('//*[@text="Turn on notifications"]').exists:
                    logger.info(f"✅ [BATCH_COMPATIBLE] 检测到通知权限对话框，尝试跳过...")
                    if self.u2_d.xpath('//*[@text="Not now"]').click_exists(timeout=2):
                        logger.info(f"✅ [BATCH_COMPATIBLE] 已跳过通知权限")
                    elif self.u2_d.xpath('//*[@text="Skip"]').click_exists(timeout=2):
                        logger.info(f"✅ [BATCH_COMPATIBLE] 已跳过通知设置")
                    time.sleep(2)
                
                # 处理更新对话框
                if self.u2_d.xpath('//*[@text="Update now"]').exists:
                    logger.info(f"✅ [BATCH_COMPATIBLE] 检测到更新对话框，尝试关闭...")
                    if self.u2_d.xpath('//*[@text="Not now"]').click_exists(timeout=2):
                        logger.info(f"✅ [BATCH_COMPATIBLE] 已点击'不，谢谢'按钮")
                    elif self.u2_d.xpath('//*[@text="Later"]').click_exists(timeout=2):
                        logger.info(f"✅ [BATCH_COMPATIBLE] 已点击'稍后'按钮")
                    time.sleep(2)
                
                # 处理其他常见的模态对话框
                modal_dialogs = [
                    '//*[@text="Got it"]',
                    '//*[@text="OK"]',
                    '//*[@text="Continue"]',
                    '//*[@text="Dismiss"]',
                    '//*[@content-desc="Dismiss"]'
                ]
                
                for dialog_xpath in modal_dialogs:
                    if self.u2_d.xpath(dialog_xpath).exists:
                        logger.info(f"✅ [BATCH_COMPATIBLE] 检测到对话框，尝试关闭: {dialog_xpath}")
                        if self.u2_d.xpath(dialog_xpath).click_exists(timeout=2):
                            logger.info(f"✅ [BATCH_COMPATIBLE] 已关闭对话框")
                            time.sleep(1)
                            
            except Exception as dialog_error:
                logger.warning(f"⚠️ [BATCH_COMPATIBLE] 处理其他弹窗时出错: {dialog_error}")
            
            # 🔍 现在开始检测登录成功的指标
            logger.info(f"🔍 [BATCH_COMPATIBLE] 弹窗处理完成，开始检测登录成功指标...")
            if self.status_callback:
                self.status_callback("🔍 开始检测登录成功指标...")
            
            # 检查登录成功的指标
            success_indicators = [
                '//*[@content-desc="Show navigation drawer"]',
                '//*[@content-desc="Home Tab"]',
                '//*[@resource-id="com.twitter.android:id/timeline"]',
                '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]',
                '//*[@content-desc="Search and Explore"]',
                '//*[@resource-id="com.twitter.android:id/composer_write"]'
            ]
            
            login_success = False
            for xpath in success_indicators:
                try:
                    if self.u2_d.xpath(xpath).exists:
                        logger.info(f"✅ [BATCH_COMPATIBLE] 发现登录成功指标: {xpath}")
                        login_success = True
                        break
                except Exception:
                    continue
            
            if not login_success:
                # 如果第一次检查失败，等待更长时间再检查
                logger.info(f"⏳ [BATCH_COMPATIBLE] 第一次检查未成功，等待10秒后重试...")
                if self.status_callback:
                    self.status_callback("⏳ 等待登录完成...")
                time.sleep(10)
                
                for xpath in success_indicators:
                    try:
                        if self.u2_d.xpath(xpath).exists:
                            logger.info(f"✅ [BATCH_COMPATIBLE] 第二次检查发现登录成功指标: {xpath}")
                            login_success = True
                            break
                    except Exception:
                        continue
            
            if login_success:
                # 🔧 **封号检测2** - 登录成功后进行封号检测
                logger.info(f"🔍 [BATCH_COMPATIBLE] 登录成功，开始封号检测...")
                if self.status_callback:
                    self.status_callback("🔍 进行登录后封号检测...")
                
                is_suspended = self._check_suspension_status(self.u2_d, self.username, self.device_ip, self.u2_port, getattr(self, 'task_id', None), self.status_callback)
                if is_suspended:
                    error_msg = f"登录成功但账户 {self.username} 已被封号"
                    logger.warning(f"🚫 [BATCH_COMPATIBLE] {error_msg}")
                    if self.status_callback:
                        self.status_callback(f"🚫 {error_msg}")
                    return False, error_msg
                
                if self.status_callback:
                    self.status_callback("✅ 登录验证成功且账户状态正常")
                return True, "登录成功"
            else:
                error_msg = "未发现登录成功指标"
                logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
                return False, error_msg
            
        except Exception as e:
            error_msg = f"验证登录状态异常: {e}"
            logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
            return False, error_msg
    
    def send_text_char_by_char(self, text: str, char_delay: float = 0.15) -> bool:
        """🔧 修复：逐字符发送文本，与batch_login_test.py保持一致"""
        try:
            for i, char in enumerate(text):
                success = self.mytapi.sendText(char)
                if not success:
                    self.log(f"❌ 发送字符失败: {char} (位置 {i+1}/{len(text)})")
                    return False
                time.sleep(char_delay)
            
            # 发送完成后稍作等待
            time.sleep(1)
            self.log(f"✅ 文本输入完成: {len(text)} 个字符")
            return True
            
        except Exception as e:
            self.log(f"❌ 发送文本异常: {e}")
            return False
    
    def cleanup_connections(self):
        """🔧 强化版连接资源清理 - 防止Windows连接重置错误"""
        try:
            self.log("🧹 开始强化版连接资源清理...")
            
            # 1. 清理MytRpc连接
            if self.mytapi:
                try:
                    # 🔧 强化：设置RPA工作模式
                    self.mytapi.setRpaWorkMode(0)
                    self.log("✅ MytRpc工作模式已重置")
                    
                    # 🔧 新增：强制断开连接
                    if hasattr(self.mytapi, 'disconnect'):
                        self.mytapi.disconnect()
                        self.log("✅ MytRpc连接已主动断开")
                        
                    # 🔧 新增：清理连接状态
                    if hasattr(self.mytapi, '_socket') and self.mytapi._socket:
                        try:
                            self.mytapi._socket.close()
                            self.log("✅ MytRpc socket已关闭")
                        except Exception as socket_error:
                            self.log(f"⚠️ MytRpc socket关闭警告: {socket_error}")
                            
                except ConnectionResetError as conn_error:
                    self.log(f"⚠️ MytRpc连接重置（预期行为）: {conn_error}")
                except OSError as os_error:
                    # Windows平台网络错误处理
                    if "10054" in str(os_error) or "connection" in str(os_error).lower():
                        self.log(f"⚠️ Windows网络连接已断开（预期行为）: {os_error}")
                    else:
                        self.log(f"⚠️ MytRpc OS错误: {os_error}")
                except Exception as e:
                    self.log(f"⚠️ MytRpc清理异常: {e}")
                finally:
                    self.mytapi = None
                    
            # 2. 清理U2连接
            if self.u2_d:
                try:
                    # 🔧 新增：强制关闭u2连接
                    if hasattr(self.u2_d, 'http'):
                        try:
                            # 关闭HTTP会话
                            self.u2_d.http.close()
                            self.log("✅ U2 HTTP会话已关闭")
                        except Exception as http_error:
                            self.log(f"⚠️ U2 HTTP关闭警告: {http_error}")
                    
                    # 🔧 强化：清理服务连接
                    if hasattr(self.u2_d, '_service') and self.u2_d._service:
                        try:
                            self.u2_d._service.stop()
                            self.log("✅ U2服务已停止")
                        except Exception as service_error:
                            self.log(f"⚠️ U2服务停止警告: {service_error}")
                            
                except ConnectionResetError as conn_error:
                    self.log(f"⚠️ U2连接重置（预期行为）: {conn_error}")
                except OSError as os_error:
                    # Windows平台网络错误处理
                    if "10054" in str(os_error) or "connection" in str(os_error).lower():
                        self.log(f"⚠️ Windows U2连接已断开（预期行为）: {os_error}")
                    else:
                        self.log(f"⚠️ U2 OS错误: {os_error}")
                except Exception as e:
                    self.log(f"⚠️ U2清理异常: {e}")
                finally:
                    self.u2_d = None
            
            # 3. 🔧 Windows平台额外清理
            try:
                import time
                import gc
                
                # Windows平台需要额外等待，确保连接完全关闭
                time.sleep(0.5)
                
                # 强制垃圾回收
                gc.collect()
                
                self.log("✅ Windows平台额外清理完成")
                
            except Exception as cleanup_error:
                self.log(f"⚠️ 额外清理警告: {cleanup_error}")
                
            self.log("🧹 强化版连接资源清理完成")
            
        except Exception as e:
            self.log(f"⚠️ 清理连接异常: {e}")
            # 即使清理失败，也要重置连接对象避免后续使用
            self.mytapi = None
            self.u2_d = None

    def _check_suspension_status(self, u2_device, username: str, device_ip: str, u2_port: int, task_id: int, status_callback) -> bool:
        """检查账户封号状态"""
        try:
            logger.info(f"[任务{task_id if task_id else 'N/A'}] 🔍 开始封号检测: {username}")
            
            # UI封号检测
            try:
                from common.twitter_ui_handlers import check_account_suspended
                
                def ui_status_callback(message):
                    logger.debug(f"[任务{task_id if task_id else 'N/A'}] UI检测: {message}")
                
                is_suspended = check_account_suspended(
                    u2_device, None, ui_status_callback, 
                    f"[{device_ip}:{u2_port}]", username, f"TwitterAutomation_{device_ip.replace('.', '_')}"
                )
                
                if is_suspended:
                    logger.warning(f"[任务{task_id if task_id else 'N/A'}] 🚫 UI检测发现账号 {username} 已被封号")
                    
                    # 🔧 修复：使用同步方式更新数据库，避免async/await错误
                    if task_id:
                        logger.info(f"[任务{task_id}] 📝 检测到封号，同步更新数据库记录...")
                        self._sync_update_suspension_database(username, "登录时检测到封号", task_id)
                    
                    return True
                else:
                    logger.info(f"[任务{task_id if task_id else 'N/A'}] ✅ UI检测确认账号 {username} 状态正常")
                    
            except Exception as ui_error:
                logger.warning(f"[任务{task_id if task_id else 'N/A'}] ⚠️ UI封号检测失败: {ui_error}")
            
            logger.info(f"[任务{task_id if task_id else 'N/A'}] ✅ 封号检测完成，账号 {username} 状态正常")
            return False
            
        except Exception as e:
            logger.error(f"[任务{task_id if task_id else 'N/A'}] ❌ 封号检测异常: {e}")
            # 检测异常时保守返回False，避免误判
            return False
    
    def _sync_update_suspension_database(self, username: str, reason: str, task_id: int):
        """同步方式更新封号数据库记录"""
        try:
            import threading
            
            def db_update_operation():
                try:
                    from core.database_handler import DatabaseHandler
                    
                    logger.info(f"[任务{task_id}] 📝 开始同步更新封号数据库: {username} - {reason}")
                    
                    db_handler = DatabaseHandler()
                    success = db_handler.add_suspended_account(username, reason)
                    
                    if success:
                        logger.info(f"[任务{task_id}] ✅ 封号数据库更新成功: {username} - {reason}")
                        
                        # 🔧 同时更新账号状态为封号
                        logger.info(f"[任务{task_id}] 📝 同步更新账号状态为封号: {username}")
                        status_updated = db_handler.update_account_status(username, "suspended")
                        if status_updated:
                            logger.info(f"[任务{task_id}] ✅ 账号状态更新成功: {username} → status=suspended")
                        else:
                            logger.warning(f"[任务{task_id}] ⚠️ 账号状态更新失败: {username}")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ 封号数据库更新失败: {username}")
                        
                except Exception as e:
                    logger.error(f"[任务{task_id}] ❌ 同步更新封号数据库异常: {e}")
            
            # 在线程中执行数据库操作
            db_thread = threading.Thread(target=db_update_operation)
            db_thread.daemon = True
            db_thread.start()
            db_thread.join(timeout=10)  # 最多等待10秒
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ 同步更新封号数据库异常: {e}")


def run_optimized_login_task(status_callback, device_ip: str, u2_port: int, myt_rpc_port: int,
                           username: str, password: str, secret_key: str) -> tuple[bool, str]:
    """🚀 [优化版] 使用OptimizedLoginExecutor执行登录，性能更优"""
    try:
        logger.info(f"🚀 [OPTIMIZED] 启动优化登录任务: {device_ip}:{u2_port}/{myt_rpc_port} - {username}")
        
        # 创建优化登录执行器
        executor = OptimizedLoginExecutor(
            device_ip=device_ip,
            u2_port=u2_port,
            myt_rpc_port=myt_rpc_port,
            username=username,
            password=password,
            secret_key=secret_key,
            status_callback=status_callback
        )
        
        # 执行登录
        success, message = executor.execute_login()
        
        # 清理连接
        executor.cleanup_connections()
        
        if success:
            logger.info(f"✅ [OPTIMIZED] 登录成功: {username}")
            return True, "登录成功"
        else:
            logger.error(f"❌ [OPTIMIZED] 登录失败: {username} - {message}")
            return False, message
            
    except Exception as e:
        error_msg = f"优化登录任务异常: {e}"
        logger.error(f"❌ [OPTIMIZED] {error_msg}")
        import traceback
        tb = traceback.format_exc()
        logger.error(tb)
        return False, f"{error_msg}\n{tb}"


async def run_batch_login_test_compatible_task(status_callback, device_ip: str, u2_port: int, myt_rpc_port: int,
                                       username: str, password: str, secret_key: str, task_id: int = None) -> tuple[bool, str]:
    """
    🚀 [100%兼容] 完全基于batch_login_test.py成功配置的登录方法
    逐步复制batch_login_test.py中的每个细节
    """
    logger.info(f"🚀 [BATCH_COMPATIBLE] 启动登录: {device_ip}:{u2_port}/{myt_rpc_port} - {username}")
    
    try:
        # 🔧 **任务取消检查1** - 开始前检查
        if task_id and _check_task_cancellation(task_id, status_callback):
            return False, "任务已被取消"
        
        # Step 1: 连接设备（完全匹配batch_login_test.py）
        logger.info(f"🔗 [BATCH_COMPATIBLE] 开始连接设备...")
        if status_callback:
            status_callback("🔗 正在连接设备...")
        
        u2_d = u2.connect(f"{device_ip}:{u2_port}")
        mytapi = MytRpc()
        
        if not mytapi.init(device_ip, myt_rpc_port, 10):
            error_msg = f"MytRpc连接失败"
            logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
            return False, error_msg
        
        logger.info(f"✅ [BATCH_COMPATIBLE] 设备连接成功")
        if status_callback:
            status_callback("✅ 设备连接成功")
        
        # 🔧 **任务取消检查2** - 连接后检查
        if task_id and _check_task_cancellation(task_id, status_callback):
            return False, "任务已被取消"
        
        # Step 2: 获取屏幕尺寸并设置坐标（完全匹配batch_login_test.py）
        screen_width, screen_height = u2_d.window_size()
        logger.info(f"📱 [BATCH_COMPATIBLE] 屏幕尺寸: {screen_width}x{screen_height}")
        
        # 使用batch_login_test.py中验证成功的坐标
        U2_COORDS = (0.644, 0.947)
        mytrpc_x = int(U2_COORDS[0] * screen_width)
        mytrpc_y = int(U2_COORDS[1] * screen_height)
        logger.info(f"📍 [BATCH_COMPATIBLE] 坐标转换: u2{U2_COORDS} → MytRpc({mytrpc_x}, {mytrpc_y})")
        
        if status_callback:
            status_callback(f"📍 坐标设置: ({mytrpc_x}, {mytrpc_y})")
        
        # Step 3: 重启Twitter应用确保干净状态（完全匹配batch_login_test.py）
        logger.info(f"🔄 [BATCH_COMPATIBLE] 重启Twitter应用...")
        if status_callback:
            status_callback("🔄 重启Twitter应用...")
        
        try:
            mytapi.exec_cmd("am force-stop com.twitter.android")
            time.sleep(3)
            mytapi.exec_cmd("am start -n com.twitter.android/.StartActivity")
            time.sleep(10)
        except Exception as e:
            logger.warning(f"⚠️ [BATCH_COMPATIBLE] 重启应用失败: {e}")
        
        # 🔧 **任务取消检查3** - 重启应用后检查
        if task_id and _check_task_cancellation(task_id, status_callback):
            return False, "任务已被取消"
        
        # Step 4: 检查是否已经登录（完全匹配batch_login_test.py）
        logger.info(f"🔍 [BATCH_COMPATIBLE] 检查登录状态...")
        if status_callback:
            status_callback("🔍 检查当前登录状态...")
        
        login_indicators = [
            '//*[@content-desc="Show navigation drawer"]',
            '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]',
            '//*[@content-desc="Home Tab"]',
            '//*[@resource-id="com.twitter.android:id/tweet_button"]'
        ]
        
        for xpath in login_indicators:
            try:
                if u2_d.xpath(xpath).exists:
                    logger.info(f"✅ [BATCH_COMPATIBLE] 账户已经登录，进行封号检测...")
                    
                    # 🔧 **封号检测1** - 登录状态检查时进行封号检测
                    is_suspended = await _check_suspension_status(u2_d, username, device_ip, u2_port, task_id, status_callback)
                    if is_suspended:
                        error_msg = f"账户 {username} 已被封号"
                        logger.warning(f"🚫 [BATCH_COMPATIBLE] {error_msg}")
                        if status_callback:
                            status_callback(f"🚫 {error_msg}")
                        return False, error_msg
                    
                    if status_callback:
                        status_callback("✅ 账户已经登录且状态正常")
                    return True, "账户已经登录"
            except Exception:
                continue
        
        # Step 5: 使用验证成功的双击方法（CLICK_METHOD = "mytrpc_double"）
        logger.info(f"📍 [BATCH_COMPATIBLE] 使用mytrpc_double方法点击登录按钮...")
        if status_callback:
            status_callback("📍 点击登录按钮...")
        
        try:
            # 第一次点击
            mytapi.touchDown(0, mytrpc_x, mytrpc_y)
            time.sleep(1.5)
            mytapi.touchUp(0, mytrpc_x, mytrpc_y)
            time.sleep(1)
            
            # 第二次点击
            mytapi.touchDown(0, mytrpc_x, mytrpc_y)
            time.sleep(1.5)
            mytapi.touchUp(0, mytrpc_x, mytrpc_y)
            time.sleep(12)  # 等待页面跳转
            
            logger.info(f"✅ [BATCH_COMPATIBLE] 登录按钮双击完成")
            if status_callback:
                status_callback("✅ 登录按钮点击完成")
        except Exception as e:
            error_msg = f"点击登录按钮异常: {e}"
            logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
            return False, error_msg
        
        # 🔧 **任务取消检查4** - 点击登录按钮后检查
        if task_id and _check_task_cancellation(task_id, status_callback):
            return False, "任务已被取消"
        
        # Step 6: 输入用户名（完全匹配batch_login_test.py的逻辑）
        logger.info(f"👤 [BATCH_COMPATIBLE] 输入用户名...")
        if status_callback:
            status_callback("👤 输入用户名...")
        
        try:
            # 查找用户名输入框（使用batch_login_test.py相同的选择器）
            username_selectors = [
                {'method': 'textContains', 'value': 'Phone, email, or username'},
                {'method': 'textContains', 'value': '手机、邮箱或用户名'},
                {'method': 'textContains', 'value': 'Username'},
                {'method': 'class', 'value': 'android.widget.EditText'}
            ]
            
            username_field = None
            for selector in username_selectors:
                try:
                    if selector['method'] == 'textContains':
                        username_field = u2_d(textContains=selector['value'])
                    elif selector['method'] == 'class':
                        username_field = u2_d(className=selector['value'])
                    
                    if username_field and username_field.exists:
                        break
                    else:
                        username_field = None
                except Exception:
                    continue
            
            if not username_field or not username_field.exists:
                error_msg = "未找到用户名输入框"
                logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
                return False, error_msg
            
            # 点击输入框
            bounds = username_field.info['bounds']
            center_x = (bounds['left'] + bounds['right']) // 2
            center_y = (bounds['top'] + bounds['bottom']) // 2
            
            mytapi.touchDown(0, center_x, center_y)
            time.sleep(1)
            mytapi.touchUp(0, center_x, center_y)
            time.sleep(1)
            
            # 输入用户名（使用batch_login_test.py相同的逐字符输入）
            for char in username:
                # 🔧 **任务取消检查5** - 输入用户名时检查（每个字符）
                if task_id and _check_task_cancellation(task_id, status_callback):
                    return False, "任务已被取消"
                
                if not mytapi.sendText(char):
                    error_msg = f"发送字符失败: {char}"
                    logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
                    return False, error_msg
                time.sleep(0.15)
            time.sleep(1)
            
            # 点击Next按钮
            next_button = u2_d.xpath('//*[@resource-id="com.twitter.android:id/cta_button"]//android.widget.Button')
            if next_button.exists:
                next_button.click()
                time.sleep(3)
            
            logger.info(f"✅ [BATCH_COMPATIBLE] 用户名输入完成")
            if status_callback:
                status_callback("✅ 用户名输入完成")
                
        except Exception as e:
            error_msg = f"输入用户名异常: {e}"
            logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
            return False, error_msg
        
        # Step 7: 输入密码（完全匹配batch_login_test.py的逻辑）
        logger.info(f"🔐 [BATCH_COMPATIBLE] 输入密码...")
        if status_callback:
            status_callback("🔐 输入密码...")
        
        try:
            # 查找密码输入框
            password_field = u2_d(text="Password")
            if not password_field.exists:
                password_field = u2_d(className="android.widget.EditText", focused=True)
                if not password_field.exists:
                    edit_texts = u2_d(className="android.widget.EditText")
                    if edit_texts.count > 1:
                        password_field = edit_texts[1]
            
            if not password_field.exists:
                error_msg = "未找到密码输入框"
                logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
                return False, error_msg
            
            # 点击输入框
            bounds = password_field.info['bounds']
            center_x = (bounds['left'] + bounds['right']) // 2
            center_y = (bounds['top'] + bounds['bottom']) // 2
            
            mytapi.touchDown(0, center_x, center_y)
            time.sleep(1)
            mytapi.touchUp(0, center_x, center_y)
            time.sleep(1)
            
            # 输入密码
            for char in password:
                # 🔧 **任务取消检查6** - 输入密码时检查（每个字符）
                if task_id and _check_task_cancellation(task_id, status_callback):
                    return False, "任务已被取消"
                    
                if not mytapi.sendText(char):
                    error_msg = f"发送字符失败: {char}"
                    logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
                    return False, error_msg
                time.sleep(0.15)
            time.sleep(1)
            
            # 点击Login按钮
            login_button = u2_d.xpath('//*[@resource-id="com.twitter.android:id/cta_button"]//android.widget.Button')
            if login_button.exists:
                login_button.click()
                time.sleep(5)
            
            logger.info(f"✅ [BATCH_COMPATIBLE] 密码输入完成")
            if status_callback:
                status_callback("✅ 密码输入完成")
                
        except Exception as e:
            error_msg = f"输入密码异常: {e}"
            logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
            return False, error_msg
        
        # Step 8: 处理2FA验证（完全匹配batch_login_test.py的逻辑）
        logger.info(f"🔢 [BATCH_COMPATIBLE] 处理2FA验证...")
        if status_callback:
            status_callback("🔢 处理2FA验证...")
        
        # 🔧 **任务取消检查7** - 2FA前检查
        if task_id and _check_task_cancellation(task_id, status_callback):
            return False, "任务已被取消"
        
        try:
            # 检查是否出现2FA页面
            verification_screen = u2_d.xpath('//*[@resource-id="com.twitter.android:id/primary_text"]')
            if not verification_screen.exists or verification_screen.get_text() != 'Enter your verification code':
                logger.info(f"⚠️ [BATCH_COMPATIBLE] 未检测到2FA页面，可能已经登录或不需要2FA")
                if status_callback:
                    status_callback("⚠️ 未需要2FA验证")
            else:
                logger.info(f"🔢 [BATCH_COMPATIBLE] 检测到2FA验证页面")
                if status_callback:
                    status_callback("🔢 检测到2FA验证页面")
                
                # 生成2FA代码
                totp = pyotp.TOTP(secret_key)
                tfa_code = totp.now()
                logger.info(f"生成2FA代码: {tfa_code}")
                
                # 查找2FA输入框并输入
                tfa_input = u2_d.xpath('//*[@resource-id="com.twitter.android:id/text_field"]//android.widget.FrameLayout')
                if tfa_input.exists:
                    tfa_input.click()
                    time.sleep(1)
                    
                    # 输入2FA代码
                    for char in tfa_code:
                        # 🔧 **任务取消检查8** - 输入2FA时检查（每个字符）
                        if task_id and _check_task_cancellation(task_id, status_callback):
                            return False, "任务已被取消"
                            
                        if not mytapi.sendText(char):
                            error_msg = f"发送2FA字符失败: {char}"
                            logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
                            return False, error_msg
                        time.sleep(0.15)
                    time.sleep(1)
                    
                    # 点击Next按钮
                    next_button = u2_d(text="Next")
                    if next_button.exists:
                        next_button.click()
                        time.sleep(5)
                    
                    logger.info(f"✅ [BATCH_COMPATIBLE] 2FA验证完成")
                    if status_callback:
                        status_callback("✅ 2FA验证完成")
                else:
                    error_msg = "未找到2FA输入框"
                    logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
                    return False, error_msg
                    
        except Exception as e:
            error_msg = f"2FA处理异常: {e}"
            logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
            return False, error_msg
        
        # Step 9: 验证登录成功（完全匹配batch_login_test.py的验证逻辑）
        logger.info(f"✅ [BATCH_COMPATIBLE] 验证登录状态...")
        if status_callback:
            status_callback("✅ 验证登录状态...")
        
        # 🔧 **任务取消检查9** - 验证前检查
        if task_id and _check_task_cancellation(task_id, status_callback):
            return False, "任务已被取消"
        
        try:
            # 等待页面加载
            time.sleep(5)
            
            # 🚀 [关键修复] 在检测登录成功指标之前，先处理可能的弹窗（参考twitter_ui_handlers.py）
            logger.info(f"🔍 [BATCH_COMPATIBLE] 检查并处理登录后弹窗...")
            if status_callback:
                status_callback("🔍 检查并处理登录后弹窗...")
            
            # 处理"Keep less relevant ads"对话框
            try:
                if u2_d(text="Keep less relevant ads").exists:
                    logger.info(f"✅ [BATCH_COMPATIBLE] 检测到'保留不太相关的广告'对话框，尝试关闭...")
                    if status_callback:
                        status_callback("✅ 检测到广告偏好对话框，尝试关闭...")
                    
                    if u2_d(text="Keep less relevant ads").click_exists(timeout=2):
                        logger.info(f"✅ [BATCH_COMPATIBLE] 已点击'保留不太相关的广告'按钮")
                        if status_callback:
                            status_callback("✅ 已处理广告偏好对话框")
                        time.sleep(2)
                    else:
                        logger.warning(f"⚠️ [BATCH_COMPATIBLE] 未能点击'保留不太相关的广告'按钮")
            except Exception as ads_error:
                logger.warning(f"⚠️ [BATCH_COMPATIBLE] 处理广告对话框时出错: {ads_error}")
            
            # 🔍 现在开始检测登录成功的指标
            logger.info(f"🔍 [BATCH_COMPATIBLE] 弹窗处理完成，开始检测登录成功指标...")
            if status_callback:
                status_callback("🔍 开始检测登录成功指标...")
            
            # 检查登录成功的指标
            success_indicators = [
                '//*[@content-desc="Show navigation drawer"]',
                '//*[@content-desc="Home Tab"]',
                '//*[@resource-id="com.twitter.android:id/timeline"]',
                '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]',
                '//*[@content-desc="Search and Explore"]',
                '//*[@resource-id="com.twitter.android:id/composer_write"]'
            ]
            
            login_success = False
            for xpath in success_indicators:
                try:
                    if u2_d.xpath(xpath).exists:
                        logger.info(f"✅ [BATCH_COMPATIBLE] 发现登录成功指标: {xpath}")
                        login_success = True
                        break
                except Exception:
                    continue
            
            if not login_success:
                # 如果第一次检查失败，等待更长时间再检查
                logger.info(f"⏳ [BATCH_COMPATIBLE] 第一次检查未成功，等待10秒后重试...")
                if status_callback:
                    status_callback("⏳ 等待登录完成...")
                time.sleep(10)
                
                for xpath in success_indicators:
                    try:
                        if u2_d.xpath(xpath).exists:
                            logger.info(f"✅ [BATCH_COMPATIBLE] 第二次检查发现登录成功指标: {xpath}")
                            login_success = True
                            break
                    except Exception:
                        continue
            
            if login_success:
                # 🔧 **封号检测2** - 登录成功后进行封号检测
                logger.info(f"🔍 [BATCH_COMPATIBLE] 登录成功，开始封号检测...")
                if status_callback:
                    status_callback("🔍 进行登录后封号检测...")
                
                is_suspended = await _check_suspension_status(u2_d, username, device_ip, u2_port, task_id, status_callback)
                if is_suspended:
                    error_msg = f"登录成功但账户 {username} 已被封号"
                    logger.warning(f"🚫 [BATCH_COMPATIBLE] {error_msg}")
                    if status_callback:
                        status_callback(f"🚫 {error_msg}")
                    return False, error_msg
                
                if status_callback:
                    status_callback("✅ 登录验证成功且账户状态正常")
                return True, "登录成功"
            else:
                error_msg = "未发现登录成功指标"
                logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
                return False, error_msg
            
        except Exception as e:
            error_msg = f"验证登录状态异常: {e}"
            logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
            return False, error_msg
            
    except Exception as e:
        error_msg = f"登录流程异常: {e}"
        logger.error(f"❌ [BATCH_COMPATIBLE] {error_msg}")
        import traceback
        tb = traceback.format_exc()
        logger.error(tb)
        return False, f"{error_msg}\n{tb}"


def _check_task_cancellation(task_id: int, status_callback) -> bool:
    """检查任务是否被取消"""
    try:
        from utils.task_cancellation import TaskCancellationChecker
        checker = TaskCancellationChecker(task_id)
        
        if checker.is_cancelled():
            logger.info(f"[任务{task_id}] ❌ 登录过程中检测到任务已被取消")
            if status_callback:
                status_callback("❌ 任务已被取消")
            return True
        return False
    except Exception as e:
        logger.warning(f"[任务{task_id}] 检查取消状态异常: {e}")
        return False


async def _check_suspension_status(u2_device, username: str, device_ip: str, u2_port: int, task_id: int, status_callback) -> bool:
    """检查账户封号状态"""
    try:
        logger.info(f"[任务{task_id if task_id else 'N/A'}] 🔍 开始封号检测: {username}")
        
        # UI封号检测
        try:
            from common.twitter_ui_handlers import check_account_suspended
            
            def ui_status_callback(message):
                logger.debug(f"[任务{task_id if task_id else 'N/A'}] UI检测: {message}")
            
            is_suspended = check_account_suspended(
                u2_device, None, ui_status_callback, 
                f"[{device_ip}:{u2_port}]", username, f"TwitterAutomation_{device_ip.replace('.', '_')}"
            )
            
            if is_suspended:
                logger.warning(f"[任务{task_id if task_id else 'N/A'}] 🚫 UI检测发现账号 {username} 已被封号")
                
                # 🔧 修复：使用同步方式更新数据库，避免async/await错误
                if task_id:
                    logger.info(f"[任务{task_id}] 📝 检测到封号，同步更新数据库记录...")
                    # 使用loop.run_in_executor在异步函数中执行同步操作
                    import asyncio
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, _sync_update_suspension_database_sync, username, "登录时检测到封号", task_id)
                
                return True
            else:
                logger.info(f"[任务{task_id if task_id else 'N/A'}] ✅ UI检测确认账号 {username} 状态正常")
                
        except Exception as ui_error:
            logger.warning(f"[任务{task_id if task_id else 'N/A'}] ⚠️ UI封号检测失败: {ui_error}")
        
        logger.info(f"[任务{task_id if task_id else 'N/A'}] ✅ 封号检测完成，账号 {username} 状态正常")
        return False
        
    except Exception as e:
        logger.error(f"[任务{task_id if task_id else 'N/A'}] ❌ 封号检测异常: {e}")
        # 检测异常时保守返回False，避免误判
        return False


def _sync_update_suspension_database_sync(username: str, reason: str, task_id: int):
    """真正的同步方式更新封号数据库记录"""
    try:
        from core.database_handler import DatabaseHandler
        
        logger.info(f"[任务{task_id}] 📝 开始同步更新封号数据库: {username} - {reason}")
        
        db_handler = DatabaseHandler()
        success = db_handler.add_suspended_account(username, reason)
        
        if success:
            logger.info(f"[任务{task_id}] ✅ 封号数据库更新成功: {username} - {reason}")
            
            # 🔧 同时更新账号状态为封号
            logger.info(f"[任务{task_id}] 📝 同步更新账号状态为封号: {username}")
            status_updated = db_handler.update_account_status(username, "suspended")
            if status_updated:
                logger.info(f"[任务{task_id}] ✅ 账号状态更新成功: {username} → status=suspended")
            else:
                logger.warning(f"[任务{task_id}] ⚠️ 账号状态更新失败: {username}")
        else:
            logger.warning(f"[任务{task_id}] ⚠️ 封号数据库更新失败: {username}")
            
    except Exception as e:
        logger.error(f"[任务{task_id}] ❌ 同步更新封号数据库异常: {e}")


async def _update_suspension_database(username: str, reason: str, task_id: int):
    """异步方式更新封号数据库记录（保留原接口）"""
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _sync_update_suspension_database_sync, username, reason, task_id)
    except Exception as e:
        logger.error(f"[任务{task_id}] ❌ 异步更新封号数据库异常: {e}") 