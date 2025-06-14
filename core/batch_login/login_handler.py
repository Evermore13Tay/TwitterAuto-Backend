"""
批量登录处理器 - 专门处理账号登录相关逻辑
"""

import time
import logging
import uiautomator2 as u2
import pyotp
from common.mytRpc import MytRpc
from typing import Dict, Any

logger = logging.getLogger("TwitterAutomationAPI")

class BatchLoginHandler:
    """批量登录处理器"""
    
    def __init__(self, database_handler):
        self.database_handler = database_handler
    
    def sync_account_login(self, device_ip: str, u2_port: int, myt_rpc_port: int, 
                          username: str, password: str, secret_key: str, task_id: int) -> bool:
        """🔧 修复版：使用batch_login_test.py验证有效的直接设备连接方法"""
        # 增强重试机制
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                logger.info(f"[任务{task_id}] 🔗 ThreadPool直接连接设备 (尝试 {attempt + 1}/{max_retries}): {username}")
                
                start_time = time.time()
                u2_d = None
                mytapi = None
                
                try:
                    # 连接u2设备
                    u2_d = u2.connect(f"{device_ip}:{u2_port}")
                    if not u2_d:
                        raise Exception("u2设备连接失败")
                        
                    # 验证u2连接
                    screen_info = u2_d.device_info
                    logger.info(f"[任务{task_id}] ✅ ThreadPool u2连接成功: {username}")
                    
                except Exception as u2_error:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool u2连接失败: {username} - {u2_error}")
                    if attempt < max_retries - 1:
                        time.sleep(5)
                        continue
                    else:
                        return False
                
                try:
                    # 连接MytRpc
                    mytapi = MytRpc()
                    connection_timeout = 20
                    if not mytapi.init(device_ip, myt_rpc_port, connection_timeout):
                        raise Exception(f"MytRpc连接失败，超时{connection_timeout}秒")
                    
                    logger.info(f"[任务{task_id}] ✅ ThreadPool MytRpc连接成功: {username}")
                    
                except Exception as rpc_error:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool MytRpc连接失败: {username} - {rpc_error}")
                    if attempt < max_retries - 1:
                        time.sleep(8)
                        continue
                    else:
                        return False
                
                # 获取屏幕尺寸并设置坐标
                try:
                    screen_width, screen_height = u2_d.window_size()
                    U2_COORDS = (0.644, 0.947)
                    mytrpc_x = int(U2_COORDS[0] * screen_width)
                    mytrpc_y = int(U2_COORDS[1] * screen_height)
                    
                    logger.info(f"[任务{task_id}] 📍 ThreadPool坐标转换: u2{U2_COORDS} → MytRpc({mytrpc_x}, {mytrpc_y})")
                    
                except Exception as coord_error:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool坐标转换失败: {username} - {coord_error}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # 重启Twitter应用确保干净状态
                logger.info(f"[任务{task_id}] 🔄 ThreadPool重启Twitter应用: {username}")
                try:
                    mytapi.exec_cmd("am force-stop com.twitter.android")
                    time.sleep(3)
                    mytapi.exec_cmd("am kill com.twitter.android") 
                    time.sleep(1)
                    mytapi.exec_cmd("am start -n com.twitter.android/.StartActivity")
                    time.sleep(10)
                    
                except Exception as app_error:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool重启应用失败: {app_error}")
                
                # 检查是否已经登录
                logger.info(f"[任务{task_id}] 🔍 ThreadPool检查登录状态: {username}")
                login_indicators = [
                    '//*[@content-desc="Show navigation drawer"]',
                    '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]',
                    '//*[@content-desc="Home Tab"]',
                    '//*[@resource-id="com.twitter.android:id/tweet_button"]'
                ]
                
                for xpath in login_indicators:
                    try:
                        if u2_d.xpath(xpath).exists:
                            duration = time.time() - start_time
                            logger.info(f"[任务{task_id}] ✅ ThreadPool账户已经登录: {username} (耗时: {duration:.1f}s)")
                            return True
                    except Exception:
                        continue
                
                # 使用双击方法点击登录按钮
                logger.info(f"[任务{task_id}] 📍 ThreadPool使用双击方法点击登录按钮: {username}")
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
                    time.sleep(12)
                    
                except Exception as click_error:
                    logger.error(f"[任务{task_id}] ❌ ThreadPool点击登录按钮失败: {username} - {click_error}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # 输入用户名
                logger.info(f"[任务{task_id}] 👤 ThreadPool输入用户名: {username}")
                if not self._input_username(u2_d, mytapi, username, task_id):
                    logger.error(f"[任务{task_id}] ❌ ThreadPool输入用户名失败: {username}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # 输入密码
                logger.info(f"[任务{task_id}] 🔐 ThreadPool输入密码: {username}")
                if not self._input_password(u2_d, mytapi, password, task_id):
                    logger.error(f"[任务{task_id}] ❌ ThreadPool输入密码失败: {username}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # 处理2FA验证
                logger.info(f"[任务{task_id}] 🔢 ThreadPool处理2FA验证: {username}")
                if not self._handle_2fa(u2_d, mytapi, secret_key, task_id):
                    logger.error(f"[任务{task_id}] ❌ ThreadPool 2FA验证失败: {username}")
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return False
                
                # 验证登录成功
                logger.info(f"[任务{task_id}] ✅ ThreadPool验证登录状态: {username}")
                if not self._verify_login_success(u2_d, task_id, username, device_ip):
                    logger.error(f"[任务{task_id}] ❌ ThreadPool登录验证失败: {username}")
                    if attempt < max_retries - 1:
                        try:
                            if mytapi:
                                mytapi.setRpaWorkMode(0)
                        except:
                            pass
                        continue
                    else:
                        return False
                
                duration = time.time() - start_time
                logger.info(f"[任务{task_id}] ✅ ThreadPool登录成功: {username} (耗时: {duration:.1f}s)")
                
                # 清理MytRpc连接状态
                try:
                    if mytapi:
                        mytapi.setRpaWorkMode(0)
                        logger.info(f"[任务{task_id}] 🧹 ThreadPool已清理MytRpc状态: {username}")
                except Exception as cleanup_error:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool MytRpc状态清理失败: {cleanup_error}")
                
                return True
                    
            except Exception as e:
                duration = time.time() - start_time if 'start_time' in locals() else 0
                logger.error(f"[任务{task_id}] ❌ ThreadPool登录异常 (尝试 {attempt + 1}/{max_retries}): {username} - {e} (耗时: {duration:.1f}s)")
                
                # 清理资源后重试
                try:
                    if 'mytapi' in locals() and mytapi:
                        mytapi.setRpaWorkMode(0)
                except:
                    pass
                
                if attempt < max_retries - 1:
                    wait_time = 5 + (attempt * 2)
                    logger.info(f"[任务{task_id}] ⏳ ThreadPool等待{wait_time}秒后重试: {username}")
                    time.sleep(wait_time)
                    continue
                else:
                    return False
        
        logger.error(f"[任务{task_id}] ❌ ThreadPool所有重试都失败: {username}")
        return False
    
    def _input_username(self, u2_d, mytapi, username: str, task_id: int) -> bool:
        """ThreadPool版本的用户名输入"""
        try:
            # 查找用户名输入框
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
                logger.error(f"[任务{task_id}] ❌ ThreadPool未找到用户名输入框")
                return False
            
            # 点击输入框
            bounds = username_field.info['bounds']
            center_x = (bounds['left'] + bounds['right']) // 2
            center_y = (bounds['top'] + bounds['bottom']) // 2
            
            mytapi.touchDown(0, center_x, center_y)
            time.sleep(1)
            mytapi.touchUp(0, center_x, center_y)
            time.sleep(1)
            
            # 输入用户名
            self._send_text_char_by_char(mytapi, username)
            
            # 点击Next按钮
            next_button = u2_d.xpath('//*[@resource-id="com.twitter.android:id/cta_button"]//android.widget.Button')
            if next_button.exists:
                next_button.click()
                time.sleep(3)
            
            return True
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool输入用户名异常: {e}")
            return False
    
    def _input_password(self, u2_d, mytapi, password: str, task_id: int) -> bool:
        """ThreadPool版本的密码输入"""
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
                logger.error(f"[任务{task_id}] ❌ ThreadPool未找到密码输入框")
                return False
            
            # 点击输入框
            bounds = password_field.info['bounds']
            center_x = (bounds['left'] + bounds['right']) // 2
            center_y = (bounds['top'] + bounds['bottom']) // 2
            
            mytapi.touchDown(0, center_x, center_y)
            time.sleep(1)
            mytapi.touchUp(0, center_x, center_y)
            time.sleep(1)
            
            # 输入密码
            self._send_text_char_by_char(mytapi, password)
            
            # 点击Login按钮
            login_button = u2_d.xpath('//*[@resource-id="com.twitter.android:id/cta_button"]//android.widget.Button')
            if login_button.exists:
                login_button.click()
                time.sleep(5)
            
            return True
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool输入密码异常: {e}")
            return False
    
    def _handle_2fa(self, u2_d, mytapi, secret_key: str, task_id: int) -> bool:
        """ThreadPool版本的2FA处理"""
        try:
            # 检查是否出现2FA页面
            verification_screen = u2_d.xpath('//*[@resource-id="com.twitter.android:id/primary_text"]')
            if not verification_screen.exists or verification_screen.get_text() != 'Enter your verification code':
                logger.info(f"[任务{task_id}] ⚠️ ThreadPool未检测到2FA页面，可能已经登录或不需要2FA")
                return True
            
            logger.info(f"[任务{task_id}] 🔢 ThreadPool检测到2FA验证页面")
            
            # 生成2FA代码
            totp = pyotp.TOTP(secret_key)
            tfa_code = totp.now()
            logger.info(f"[任务{task_id}] ThreadPool生成2FA代码: {tfa_code}")
            
            # 查找2FA输入框并输入
            tfa_input = u2_d.xpath('//*[@resource-id="com.twitter.android:id/text_field"]//android.widget.FrameLayout')
            if tfa_input.exists:
                tfa_input.click()
                time.sleep(1)
                
                # 输入2FA代码
                self._send_text_char_by_char(mytapi, tfa_code)
                
                # 点击Next按钮
                next_button = u2_d(text="Next")
                if next_button.exists:
                    next_button.click()
                    time.sleep(5)
                
                return True
            else:
                logger.error(f"[任务{task_id}] ❌ ThreadPool未找到2FA输入框")
                return False
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool 2FA处理异常: {e}")
            return False
    
    def _verify_login_success(self, u2_d, task_id: int, username: str = None, device_ip: str = None) -> bool:
        """ThreadPool版本的登录验证"""
        try:
            logger.info(f"[任务{task_id}] 🔍 ThreadPool开始增强版登录验证: {username}")
            
            # 等待页面初始加载
            time.sleep(5)
            
            # 处理可能的Update弹窗
            logger.info(f"[任务{task_id}] 📱 ThreadPool检查Update弹窗...")
            self._handle_update_dialog(u2_d, task_id)
            
            # 处理可能的广告弹窗
            logger.info(f"[任务{task_id}] 📢 ThreadPool检查广告弹窗...")
            self._handle_ads_dialog(u2_d, task_id)
            
            # 检查账号封号状态
            logger.info(f"[任务{task_id}] 🚫 ThreadPool检查封号状态...")
            if self._check_suspension(u2_d, task_id, username, device_ip):
                logger.error(f"[任务{task_id}] ❌ ThreadPool检测到账号封号: {username}")
                return False
            
            # 处理其他模态弹窗
            logger.info(f"[任务{task_id}] 🪟 ThreadPool处理其他弹窗...")
            self._handle_modal_dialogs(u2_d, task_id)
            
            # 等待页面稳定
            time.sleep(3)
            
            # 增强的登录成功检测
            logger.info(f"[任务{task_id}] ✅ ThreadPool进行最终登录状态验证...")
            
            # 检查登录成功的指标（多层检测）
            success_indicators = [
                # 主要指标（权重高）
                {'xpath': '//*[@content-desc="Show navigation drawer"]', 'name': '导航抽屉', 'weight': 10},
                {'xpath': '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]', 'name': '底部导航栏', 'weight': 10},
                {'xpath': '//*[@content-desc="Home Tab"]', 'name': '主页标签', 'weight': 9},
                {'xpath': '//*[@resource-id="com.twitter.android:id/timeline"]', 'name': '时间线', 'weight': 9},
                
                # 次要指标（权重中）
                {'xpath': '//*[@content-desc="Search and Explore"]', 'name': '搜索按钮', 'weight': 7},
                {'xpath': '//*[@resource-id="com.twitter.android:id/composer_write"]', 'name': '发推按钮', 'weight': 7},
                {'xpath': '//*[@resource-id="com.twitter.android:id/tweet_button"]', 'name': '发推浮动按钮', 'weight': 6},
                
                # 辅助指标（权重低）
                {'xpath': '//*[@content-desc="Notifications"]', 'name': '通知按钮', 'weight': 5},
                {'xpath': '//*[@content-desc="Messages"]', 'name': '消息按钮', 'weight': 5},
                {'xpath': '//*[@resource-id="com.twitter.android:id/channels"]', 'name': '频道区域', 'weight': 4},
            ]
            
            found_indicators = []
            total_score = 0
            
            for indicator in success_indicators:
                try:
                    if u2_d.xpath(indicator['xpath']).exists:
                        found_indicators.append(indicator['name'])
                        total_score += indicator['weight']
                        logger.info(f"[任务{task_id}] ✅ ThreadPool发现登录指标: {indicator['name']} (权重: {indicator['weight']})")
                except Exception:
                    continue
            
            # 登录成功判定：总分≥15分且至少有2个指标
            login_success = total_score >= 15 and len(found_indicators) >= 2
            
            if login_success:
                logger.info(f"[任务{task_id}] ✅ ThreadPool登录验证成功: {username} (总分: {total_score}, 指标数: {len(found_indicators)})")
                logger.info(f"[任务{task_id}] 📋 ThreadPool发现的指标: {', '.join(found_indicators)}")
                return True
            
            # 如果第一次检查失败，进行深度检查
            logger.info(f"[任务{task_id}] ⏳ ThreadPool第一次检查未成功，进行深度验证...")
            
            # 检查是否在登录页面（失败指标）
            login_page_indicators = [
                '//*[@text="Log in"]',
                '//*[@text="登录"]', 
                '//*[@text="Sign in"]',
                '//*[@text="Create account"]',
                '//*[@text="Phone, email, or username"]',
                '//*[@text="手机、邮箱或用户名"]',
                '//*[@text="Password"]',
                '//*[@text="密码"]'
            ]
            
            on_login_page = False
            for login_indicator in login_page_indicators:
                try:
                    if u2_d.xpath(login_indicator).exists:
                        logger.warning(f"[任务{task_id}] ❌ ThreadPool检测到登录页面指标: {login_indicator}")
                        on_login_page = True
                        break
                except Exception:
                    continue
            
            if on_login_page:
                logger.error(f"[任务{task_id}] ❌ ThreadPool用户需要重新登录: {username}")
                return False
            
            # 等待更长时间后重新检查
            logger.info(f"[任务{task_id}] ⏳ ThreadPool等待10秒后重新检查...")
            time.sleep(10)
            
            # 轻量级重新处理弹窗（避免过度触发）
            logger.info(f"[任务{task_id}] 🔄 ThreadPool轻量级重新检查弹窗...")
            self._handle_modal_dialogs_light(u2_d, task_id)
            
            # 再次检查登录指标
            found_indicators_retry = []
            total_score_retry = 0
            
            for indicator in success_indicators:
                try:
                    if u2_d.xpath(indicator['xpath']).exists:
                        found_indicators_retry.append(indicator['name'])
                        total_score_retry += indicator['weight']
                        logger.info(f"[任务{task_id}] ✅ ThreadPool重试发现登录指标: {indicator['name']}")
                except Exception:
                    continue
            
            # 重试的成功判定（稍微放宽标准）
            login_success_retry = total_score_retry >= 10 and len(found_indicators_retry) >= 1
            
            if login_success_retry:
                logger.info(f"[任务{task_id}] ✅ ThreadPool重试登录验证成功: {username} (总分: {total_score_retry}, 指标数: {len(found_indicators_retry)})")
                return True
            
            logger.error(f"[任务{task_id}] ❌ ThreadPool登录验证最终失败: {username} (重试总分: {total_score_retry}, 指标数: {len(found_indicators_retry)})")
            return False
            
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool验证登录状态异常: {e}")
            return False
    
    def _handle_update_dialog(self, u2_d, task_id: int) -> None:
        """ThreadPool版本的Update弹窗处理"""
        try:
            update_indicators = [
                {'xpath': '//*[@text="Update now"]', 'name': '立即更新'},
                {'xpath': '//*[@text="Update"]', 'name': '更新'},
                {'xpath': '//*[contains(@text, "update") or contains(@text, "Update")]', 'name': '包含update的文本'}
            ]
            
            for indicator in update_indicators:
                try:
                    if u2_d.xpath(indicator['xpath']).exists:
                        logger.info(f"[任务{task_id}] 📱 ThreadPool检测到Update弹窗: {indicator['name']}")
                        
                        close_buttons = [
                            '//*[@text="Not now"]',
                            '//*[@text="稍后"]',
                            '//*[@text="Later"]',
                            '//*[@text="Skip"]',
                            '//*[@text="跳过"]',
                            '//*[@content-desc="Close"]',
                            '//*[@content-desc="关闭"]',
                            '//*[@content-desc="Dismiss"]'
                        ]
                        
                        closed = False
                        for close_btn in close_buttons:
                            try:
                                if u2_d.xpath(close_btn).click_exists(timeout=2):
                                    logger.info(f"[任务{task_id}] ✅ ThreadPool已关闭Update弹窗: {close_btn}")
                                    closed = True
                                    time.sleep(2)
                                    break
                            except Exception:
                                continue
                        
                        if not closed:
                            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool无法关闭Update弹窗，重启应用...")
                            u2_d.app_stop("com.twitter.android")
                            time.sleep(3)
                            u2_d.app_start("com.twitter.android")
                            time.sleep(8)
                        
                        break
                except Exception:
                    continue
                    
        except Exception as e:
            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool处理Update弹窗异常: {e}")
    
    def _handle_ads_dialog(self, u2_d, task_id: int) -> None:
        """ThreadPool版本的广告弹窗处理"""
        try:
            ads_indicators = [
                {'xpath': '//*[@text="Keep less relevant ads"]', 'name': '保留不太相关的广告'},
                {'xpath': '//*[@text="See fewer ads like this"]', 'name': '减少此类广告'},
                {'xpath': '//*[contains(@text, "ads") or contains(@text, "Ads")]', 'name': '包含ads的文本'},
                {'xpath': '//*[contains(@text, "广告")]', 'name': '包含广告的文本'}
            ]
            
            for indicator in ads_indicators:
                try:
                    if u2_d.xpath(indicator['xpath']).exists:
                        logger.info(f"[任务{task_id}] 📢 ThreadPool检测到广告弹窗: {indicator['name']}")
                        
                        if u2_d.xpath(indicator['xpath']).click_exists(timeout=2):
                            logger.info(f"[任务{task_id}] ✅ ThreadPool已处理广告弹窗: {indicator['name']}")
                            time.sleep(2)
                            break
                except Exception:
                    continue
                    
        except Exception as e:
            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool处理广告弹窗异常: {e}")
    
    def _check_suspension(self, u2_d, task_id: int, username: str = None, device_ip: str = None) -> bool:
        """ThreadPool版本的封号检测"""
        try:
            suspension_indicators = [
                {'xpath': '//*[@resource-id="com.twitter.android:id/alertTitle"]', 'name': '警告标题'},
                {'xpath': '//*[contains(@text, "Suspended") or contains(@text, "suspended")]', 'name': '包含Suspended的文本'},
                {'xpath': '//*[contains(@text, "封停") or contains(@text, "封号")]', 'name': '包含封停的文本'},
                {'xpath': '//*[contains(@text, "违反") or contains(@text, "violation")]', 'name': '违反规则相关文本'}
            ]
            
            for indicator in suspension_indicators:
                try:
                    element = u2_d.xpath(indicator['xpath'])
                    if element.exists:
                        alert_text = element.get_text() if hasattr(element, 'get_text') else "检测到封号指标"
                        logger.warning(f"[任务{task_id}] 🚫 ThreadPool检测到封号指标: {indicator['name']} - {alert_text}")
                        
                        if username and ("Suspended" in alert_text or "suspended" in alert_text or "封停" in alert_text):
                            logger.warning(f"[任务{task_id}] 📝 ThreadPool准备更新封号数据库: {username}")
                            try:
                                self._update_suspension_database(username, alert_text, task_id)
                            except Exception as db_e:
                                logger.error(f"[任务{task_id}] ❌ ThreadPool更新封号数据库失败: {db_e}")
                            
                            return True
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool检查封号状态异常: {e}")
            return False
    
    def _handle_modal_dialogs(self, u2_d, task_id: int) -> None:
        """ThreadPool版本的通用模态弹窗处理（优化版，避免过度触发）"""
        try:
            # 分优先级处理，避免同时触发多个
            priority_buttons = [
                # 第一优先级：最重要的弹窗
                ['//*[@text="Not now"]', '//*[@text="稍后"]'],
                # 第二优先级：确认类弹窗
                ['//*[@text="Got it"]', '//*[@text="知道了"]', '//*[@text="OK"]', '//*[@text="确定"]'],
                # 第三优先级：关闭类弹窗
                ['//*[@text="Dismiss"]', '//*[@content-desc="Dismiss"]', '//*[@text="关闭"]'],
                # 第四优先级：跳过类弹窗
                ['//*[@text="Skip"]', '//*[@text="跳过"]', '//*[@text="Continue"]', '//*[@text="继续"]']
            ]
            
            handled_count = 0
            max_handles = 2  # 最多处理2个弹窗，避免过度操作
            
            for priority_group in priority_buttons:
                if handled_count >= max_handles:
                    break
                    
                for button in priority_group:
                    try:
                        if u2_d.xpath(button).click_exists(timeout=1):
                            logger.info(f"[任务{task_id}] ✅ ThreadPool关闭模态弹窗: {button}")
                            handled_count += 1
                            time.sleep(1.5)  # 增加等待时间，避免过快操作
                            break  # 处理完一个优先级就跳到下一个
                    except Exception:
                        continue
                        
            if handled_count == 0:
                logger.info(f"[任务{task_id}] ℹ️ ThreadPool检查：无需处理的模态弹窗")
            else:
                logger.info(f"[任务{task_id}] 📊 ThreadPool共处理了 {handled_count} 个模态弹窗")
                    
        except Exception as e:
            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool处理模态弹窗异常: {e}")
    
    def _handle_modal_dialogs_light(self, u2_d, task_id: int) -> None:
        """ThreadPool版本的轻量级模态弹窗处理（避免过度触发）"""
        try:
            # 只处理最关键的弹窗，避免重复点击
            critical_buttons = [
                '//*[@text="Not now"]',  # 最常见的"稍后"按钮
                '//*[@text="稍后"]',
                '//*[@content-desc="Dismiss"]'  # 关闭按钮
            ]
            
            handled_any = False
            for button in critical_buttons:
                try:
                    # 只尝试一次，不重复
                    if not handled_any and u2_d.xpath(button).click_exists(timeout=1):
                        logger.info(f"[任务{task_id}] ✅ ThreadPool轻量级处理弹窗: {button}")
                        handled_any = True
                        time.sleep(2)  # 处理完一个就停止，等待
                        break
                except Exception:
                    continue
                    
            if not handled_any:
                logger.info(f"[任务{task_id}] ℹ️ ThreadPool轻量级检查：无需处理的弹窗")
                    
        except Exception as e:
            logger.warning(f"[任务{task_id}] ⚠️ ThreadPool轻量级处理弹窗异常: {e}")
    
    def _update_suspension_database(self, username: str, reason: str, task_id: int) -> None:
        """ThreadPool版本的同步封号数据库更新"""
        try:
            logger.info(f"[任务{task_id}] 📝 ThreadPool开始更新封号数据库: {username} - {reason}")
            
            if hasattr(self, 'database_handler') and self.database_handler:
                success = self.database_handler.add_suspended_account(username, reason)
                if success:
                    logger.info(f"[任务{task_id}] ✅ ThreadPool封号数据库更新成功: {username}")
                    
                    status_updated = self.database_handler.update_account_status(username, "suspended")
                    if status_updated:
                        logger.info(f"[任务{task_id}] ✅ ThreadPool账号状态更新为封号: {username}")
                    else:
                        logger.warning(f"[任务{task_id}] ⚠️ ThreadPool账号状态更新失败: {username}")
                else:
                    logger.warning(f"[任务{task_id}] ⚠️ ThreadPool封号数据库更新失败: {username}")
            else:
                logger.warning(f"[任务{task_id}] ⚠️ ThreadPool数据库处理器不可用")
                
        except Exception as e:
            logger.error(f"[任务{task_id}] ❌ ThreadPool更新封号数据库异常: {username} - {e}")
    
    def _send_text_char_by_char(self, mytapi, text: str, char_delay=0.15):
        """ThreadPool版本的逐字符发送文本"""
        try:
            for char in text:
                if not mytapi.sendText(char):
                    return False
                time.sleep(char_delay)
            time.sleep(1)
            return True
        except Exception as e:
            return False 