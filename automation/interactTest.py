import os
import sys
from datetime import datetime
import time
import traceback
import uiautomator2 as u2
from common.mytRpc import MytRpc
import random
from common.u2_connection import connect_to_device
from common.twitter_ui_handlers import handle_update_now_dialog, handle_keep_less_relevant_ads, ensure_twitter_app_running_and_logged_in

_LOG_DIR_SCRIPT_INTERACT = "."
try:
    _LOG_DIR_SCRIPT_INTERACT = os.path.dirname(sys.executable) # For bundled app
except Exception:
    _LOG_DIR_SCRIPT_INTERACT = os.path.abspath(os.path.dirname(__file__))

_SCRIPT_LOG_PATH_INTERACT = os.path.join(_LOG_DIR_SCRIPT_INTERACT, "INTERACTTest_execution.log")

def script_log_interact(message):
    try:
        with open(_SCRIPT_LOG_PATH_INTERACT, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] [INTERACTTest] {message}\n")
            f.flush()
    except Exception as e:
        print(f"Error writing to INTERACTTest log: {e}")

script_log_interact(f"--- interactTest.py started ---")
script_log_interact(f"sys.executable: {sys.executable}")
script_log_interact(f"os.getcwd(): {os.getcwd()}")
if hasattr(sys, '_MEIPASS'):
    script_log_interact(f"sys._MEIPASS (from interactTest.py): {sys._MEIPASS}")
else:
    script_log_interact("interactTest.py: Not running from _MEIPASS bundle (no sys._MEIPASS attribute).")

# Device IP - (Will be passed as a parameter)
# DEVICE_IP = "192.168.8.74"

# XPaths and Selectors (kept as module constants)
LIKE_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/inline_like"]/android.widget.FrameLayout[1]/android.widget.ImageView[1]'
TWEET_AREA_XPATH = '//*[@resource-id="android:id/list"]/android.view.ViewGroup[2]/android.widget.LinearLayout[1]'
COMMENT_ICON_XPATH = '//*[@resource-id="com.twitter.android:id/inline_reply"]/android.widget.FrameLayout[1]/android.widget.ImageView[1]'
# COMMENT_TEXT_INPUT_CLICK_XPATH = '//android.widget.ScrollView/android.view.View[1]' # Old, less reliable
COMMENT_REPLY_INPUT_PROMPT_TEXT = "Tweet your reply"
POST_REPLY_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/composer_toolbar"]/android.widget.LinearLayout[1]'
NAVIGATE_UP_DESCRIPTION = "Navigate up"

# New Post Button XPaths - 顶部新推文按钮的精确XPath
NEW_POST_BUTTON_XPATHS = [
    '//*[@resource-id="com.twitter.android:id/banner_text"]',  # 🎯 精确的顶部posted按钮XPath
    '//*[@text="posted"]',  # 备用：文本匹配
    '//*[@text="Show new posts"]',  # 备用：其他可能的文本
    '//*[@text="Show new Post"]', 
    '//*[@text="Show new Tweets"]',
    '//*[@text="New posts"]',
    '//*[@text="New Tweets"]',
    '//*[contains(@text, "posted")]',
    '//*[contains(@text, "new post")]'
]

# Page Detection XPaths - 页面检测元素
MAIN_TIMELINE_INDICATORS = [
    '//*[@resource-id="com.twitter.android:id/channels"]',  # 底部导航栏
    '//*[@content-desc="Home"]',  # Home按钮
    '//*[@resource-id="com.twitter.android:id/timeline"]'  # 时间线容器
]

DETAIL_PAGE_INDICATORS = [
    '//*[@content-desc="Navigate up"]',  # 返回按钮（详情页特有）
    '//*[@resource-id="com.twitter.android:id/composer_toolbar"]',  # 回复工具栏
    '//*[@text="Tweet your reply"]'  # 回复输入框
]

# Probabilities and Settings (will be adjusted based on parameters)
# PROBABILITY_TO_INTERACT_WITH_TWEET = 0.30 
# PROBABILITY_TO_LIKE_ONCE_OPENED = 0.60
# PROBABILITY_TO_COMMENT_ONCE_OPENED = 0.40
# COMMENT_TEXT = "1"  # This value is now passed as a parameter

# New Post Check Settings
NEW_POST_CHECK_INTERVAL = 60  # 检查新推文按钮的间隔（秒）

# 全局变量跟踪已预热的设备
_warmed_up_devices = set()

def clear_warmup_cache():
    """清理预热缓存，强制所有设备重新预热"""
    global _warmed_up_devices
    _warmed_up_devices.clear()
    print("🔄 预热缓存已清理，所有设备将重新预热")

def get_warmed_up_devices():
    """获取已预热的设备列表"""
    global _warmed_up_devices
    return list(_warmed_up_devices)

def remove_device_from_warmup_cache(device_ip, u2_port):
    """从预热缓存中移除特定设备"""
    global _warmed_up_devices
    device_key = f"{device_ip}:{u2_port}"
    if device_key in _warmed_up_devices:
        _warmed_up_devices.remove(device_key)
        print(f"🔄 设备 {device_key} 已从预热缓存中移除")

def is_on_main_timeline(u2_device):
    """
    检查当前是否在主时间线页面（而不是推文详情页或其他页面）
    
    Returns:
        bool: True表示在主时间线，False表示在其他页面
    """
    try:
        # 首先检查是否有主时间线的特征元素
        is_main_timeline = False
        for indicator in MAIN_TIMELINE_INDICATORS:
            try:
                if u2_device.xpath(indicator).exists:
                    is_main_timeline = True
                    break
            except Exception:
                continue
        
        # 如果检测到主时间线特征，再检查是否在详情页
        if is_main_timeline:
            for indicator in DETAIL_PAGE_INDICATORS:
                try:
                    if u2_device.xpath(indicator).exists:
                        return False  # 在详情页，不是主时间线
                except Exception:
                    continue
        
        return is_main_timeline
        
    except Exception:
        return False

def slow_scroll_down_and_interact(status_callback, myt_rpc, u2_device, device_info="", total_duration_seconds=160, 
                                  enable_liking=True, enable_commenting=True, 
                                  prob_interact_tweet=0.30, prob_like_opened=0.60, prob_comment_opened=0.40, comment_text="1"):
    screen_width, screen_height = u2_device.window_size()
    if not screen_width or not screen_height:
        status_callback(f"{device_info}错误: 无法获取屏幕尺寸。"); return False

    start_x, start_y, end_y = int(screen_width / 2), int(screen_height * 0.8), int(screen_height * 0.2)
    status_callback(f"{device_info}开始滚动和互动，持续约{total_duration_seconds}秒。点赞: {enable_liking}, 评论: {enable_commenting}")
    loop_start_time = time.time()
    last_new_post_check = time.time()  # 上次检查new post按钮的时间
    swipes_done, interaction_attempts, likes_done, comments_done = 0, 0, 0, 0

    # Adjust probabilities based on enable flags
    actual_prob_like = prob_like_opened if enable_liking else 0
    actual_prob_comment = prob_comment_opened if enable_commenting else 0

    while time.time() - loop_start_time < total_duration_seconds:
        time_left_total = total_duration_seconds - (time.time() - loop_start_time)
        if time_left_total <= 0: break

        # 🆕 每隔1分钟检查是否有new post按钮 - 智能策略：只在主时间线检查
        current_time = time.time()
        if current_time - last_new_post_check >= NEW_POST_CHECK_INTERVAL:
            try:
                # 智能检查：只在主时间线页面检查新推文按钮
                if is_on_main_timeline(u2_device):
                    status_callback(f"{device_info}🔄 在主时间线，检查是否有新推文可用...")
                    
                    # 使用精确XPath和MytRpc点击顶部新推文按钮
                    new_post_clicked = False
                    
                    for xpath in NEW_POST_BUTTON_XPATHS:
                        try:
                            new_post_element = u2_device.xpath(xpath)
                            if new_post_element.exists:
                                try:
                                    # 获取按钮位置信息
                                    bounds = new_post_element.info['bounds']
                                    button_x = (bounds['left'] + bounds['right']) // 2
                                    button_y = (bounds['top'] + bounds['bottom']) // 2
                                    
                                    status_callback(f"{device_info}✅ 发现顶部新推文按钮 (XPath: {xpath})，使用MytRpc点击...")
                                    status_callback(f"{device_info}🎯 点击位置: ({button_x}, {button_y})")
                                    
                                    # 使用MytRpc进行点击
                                    myt_rpc.touchDown(0, button_x, button_y)
                                    time.sleep(random.uniform(0.05, 0.15))
                                    myt_rpc.touchUp(0, button_x, button_y)
                                    
                                    status_callback(f"{device_info}✅ 顶部新推文按钮点击完成，等待页面刷新...")
                                    time.sleep(random.uniform(1.5, 3.0))  # 等待页面刷新
                                    new_post_clicked = True
                                    break
                                    
                                except Exception as e:
                                    status_callback(f"{device_info}⚠️ MytRpc点击顶部按钮失败: {e}")
                                    continue
                        except Exception as e:
                            continue
                    
                    if not new_post_clicked:
                        status_callback(f"{device_info}ℹ️ 主时间线没有发现新推文按钮")
                else:
                    status_callback(f"{device_info}📱 当前在推文详情页或其他页面，跳过新推文检查")
                
            except Exception as e:
                status_callback(f"{device_info}⚠️ 检查新推文按钮异常: {e}")
            
            last_new_post_check = current_time

        swipe_anim_ms = random.randint(800, 1600)
        # 简化滑动日志：只在每10次滑动时打印一次
        if (swipes_done + 1) % 10 == 0 or swipes_done == 0:
            status_callback(f"{device_info}滑动进度: 第{swipes_done + 1}次，剩余时间: {time_left_total:.0f}秒")
        myt_rpc.exec_cmd(f"input swipe {start_x} {start_y} {start_x} {end_y} {swipe_anim_ms}")
        swipes_done += 1
        time.sleep(min(swipe_anim_ms / 1000, time_left_total))
        time_left_total = total_duration_seconds - (time.time() - loop_start_time);
        if time_left_total <= 0: break

        pause_s = random.uniform(0.3, 1.5)
        actual_pause = min(pause_s, time_left_total)
        if actual_pause > 0: time.sleep(actual_pause)
        time_left_total = total_duration_seconds - (time.time() - loop_start_time);
        if time_left_total <= 0: break

        if random.random() < prob_interact_tweet:
            # 简化互动日志
            interaction_attempts += 1
            tweet_elements = u2_device.xpath(TWEET_AREA_XPATH).all()
            if not tweet_elements:
                continue
            
            target_tweet_element = tweet_elements[0]
            try:
                bounds = target_tweet_element.info['bounds']
                cx, cy = (bounds['left'] + bounds['right']) // 2, (bounds['top'] + bounds['bottom']) // 2
                myt_rpc.touchDown(0, cx, cy)
                time.sleep(random.uniform(0.05,0.15))
                myt_rpc.touchUp(0, cx, cy)

                time_left_for_actions = total_duration_seconds - (time.time() - loop_start_time)
                if time_left_for_actions <= 3:
                    if not u2_device(description=NAVIGATE_UP_DESCRIPTION).click_exists(timeout=3.0): myt_rpc.pressBack()
                    time.sleep(min(1.0, time_left_for_actions if time_left_for_actions > 0 else 0.1))
                    continue
                
                wait_inside_s = random.uniform(5.0, 20.0)
                actual_wait = min(wait_inside_s, time_left_for_actions - 3)
                if actual_wait > 0: time.sleep(actual_wait)
                
                time_left_for_actions = total_duration_seconds - (time.time() - loop_start_time)
                if time_left_for_actions <= 1:
                    if not u2_device(description=NAVIGATE_UP_DESCRIPTION).click_exists(timeout=1.0): myt_rpc.pressBack()
                    break 

                do_like = random.random() < actual_prob_like
                do_comment = random.random() < actual_prob_comment

                # 简化决定浏览的日志
                if not do_like and not do_comment: pass

                if do_like:
                    like_action_done_in_detail = False
                    
                    # 首先检查当前页面是否有点赞按钮
                    like_els_detail = u2_device.xpath(LIKE_BUTTON_XPATH).all()
                    if like_els_detail:
                        try:
                            lb = like_els_detail[0].info['bounds']
                            lcx, lcy = (lb['left']+lb['right'])//2, (lb['top']+lb['bottom'])//2
                            myt_rpc.touchDown(0, lcx, lcy)
                            time.sleep(random.uniform(0.05,0.15))
                            myt_rpc.touchUp(0, lcx, lcy)
                            likes_done +=1
                            like_action_done_in_detail = True
                            time_after_like_click = total_duration_seconds-(time.time()-loop_start_time)
                            if time_after_like_click > 0: time.sleep(min(random.uniform(0.5,1.0), time_after_like_click))
                        except Exception as e: 
                            pass  # 简化错误日志
                    else:
                        pass  # 简化搜索日志
                        
                        # 如果当前页面没有找到点赞按钮，最多尝试5次小滚动
                        max_mini_swipes = 5
                        for i in range(max_mini_swipes):
                            if like_action_done_in_detail:
                                break  # 如果已完成点赞操作，跳出循环
                            
                            time_left_for_detail_action = total_duration_seconds - (time.time() - loop_start_time)
                            if time_left_for_detail_action < 1.0:
                                break
                            
                            detail_swipe_start_y = int(screen_height * 0.7)
                            detail_swipe_end_y = int(screen_height * 0.3)
                            detail_swipe_anim_ms = random.randint(300, 600)
                            
                            myt_rpc.exec_cmd(f"input swipe {start_x} {detail_swipe_start_y} {start_x} {detail_swipe_end_y} {detail_swipe_anim_ms}")
                            sleep_duration_after_detail_scroll = min((detail_swipe_anim_ms / 1000) + 0.3, time_left_for_detail_action - 0.2)
                            if sleep_duration_after_detail_scroll > 0:
                                time.sleep(sleep_duration_after_detail_scroll)
                            else: 
                                if time_left_for_detail_action <= 0: break 
                                else: continue

                            like_els_detail = u2_device.xpath(LIKE_BUTTON_XPATH).all()
                            if like_els_detail:
                                try:
                                    lb = like_els_detail[0].info['bounds']
                                    lcx, lcy = (lb['left']+lb['right'])//2, (lb['top']+lb['bottom'])//2
                                    myt_rpc.touchDown(0, lcx, lcy)
                                    time.sleep(random.uniform(0.05,0.15))
                                    myt_rpc.touchUp(0, lcx, lcy)
                                    likes_done +=1
                                    like_action_done_in_detail = True
                                    time_after_like_click = total_duration_seconds-(time.time()-loop_start_time)
                                    if time_after_like_click > 0: time.sleep(min(random.uniform(0.5,1.0), time_after_like_click))
                                    break  # 找到点赞按钮并点击后跳出循环
                                except Exception as e: 
                                    pass  # 简化错误日志
                            else:
                                pass  # 简化小滚动结果日志
                    
                    if not like_action_done_in_detail:
                        pass  # 简化未找到点赞按钮的日志
                
                time_left_for_actions = total_duration_seconds - (time.time() - loop_start_time)
                if time_left_for_actions <= (2 if do_comment else 1):
                    if not u2_device(description=NAVIGATE_UP_DESCRIPTION).click_exists(timeout=1.0): myt_rpc.pressBack()
                    if time_left_for_actions <=0: break
                    else: continue

                if do_comment:
                    comment_icons = u2_device.xpath(COMMENT_ICON_XPATH).all()
                    if comment_icons:
                        try:
                            cb = comment_icons[0].info['bounds']
                            ccx, ccy = (cb['left']+cb['right'])//2, (cb['top']+cb['bottom'])//2
                            myt_rpc.touchDown(0,ccx,ccy)
                            time.sleep(random.uniform(0.05,0.15))
                            myt_rpc.touchUp(0,ccx,ccy)
                            time.sleep(1.0)

                            reply_input_field_ui_obj = u2_device(textContains=COMMENT_REPLY_INPUT_PROMPT_TEXT)
                            
                            if reply_input_field_ui_obj.exists:
                                try:
                                    input_bounds = reply_input_field_ui_obj.info['bounds']
                                    input_cx = (input_bounds['left'] + input_bounds['right']) // 2
                                    input_cy = (input_bounds['top'] + input_bounds['bottom']) // 2
                                    status_callback(f"{device_info}点击回复输入框 ({input_cx}, {input_cy})...")
                                    myt_rpc.touchDown(0, input_cx, input_cy)
                                    time.sleep(random.uniform(0.05,0.15))
                                    myt_rpc.touchUp(0, input_cx, input_cy)
                                    time.sleep(0.5)

                                    status_callback(f"{device_info}输入评论内容: '{comment_text}'...")
                                    if myt_rpc.sendText(comment_text):
                                        status_callback(f"{device_info}评论文本发送成功。")
                                        time.sleep(0.5)
                                        
                                        status_callback(f"{device_info}寻找发布回复按钮，XPath: {POST_REPLY_BUTTON_XPATH}...")
                                        post_reply_button_element = u2_device.xpath(POST_REPLY_BUTTON_XPATH)
                                        
                                        if post_reply_button_element.exists:
                                            try:
                                                prb_bounds = post_reply_button_element.info['bounds']
                                                prb_cx = (prb_bounds['left']+prb_bounds['right'])//2
                                                prb_cy = (prb_bounds['top']+prb_bounds['bottom'])//2
                                                status_callback(f"{device_info}点击发布回复按钮 ({prb_cx},{prb_cy})...")
                                                myt_rpc.touchDown(0,prb_cx,prb_cy)
                                                time.sleep(random.uniform(0.05,0.15))
                                                myt_rpc.touchUp(0,prb_cx,prb_cy)
                                                status_callback(f"{device_info}评论已发布。"); comments_done +=1
                                                
                                                # Check for and handle "Got it" dialog after posting a comment
                                                status_callback(f"{device_info}检查是否存在 'Got it' 按钮")
                                                time.sleep(1.5)  # Wait for potential "Got it" dialog to appear
                                                got_it_button_xpath = '//*[@text="Got it"]'
                                                status_callback(f"{device_info}检查是否存在 'Got it' 按钮: {got_it_button_xpath}")
                                                got_it_button_obj = u2_device.xpath(got_it_button_xpath)
                                                if got_it_button_obj.exists:
                                                    status_callback(f"{device_info}找到 'Got it' 按钮，尝试点击...")
                                                    time.sleep(0.5)  # Brief pause before clicking
                                                    try:
                                                        got_it_bounds = got_it_button_obj.info['bounds']
                                                        got_it_cx = (got_it_bounds['left'] + got_it_bounds['right']) // 2
                                                        got_it_cy = (got_it_bounds['top'] + got_it_bounds['bottom']) // 2
                                                        status_callback(f"{device_info}点击 'Got it' 按钮 ({got_it_cx}, {got_it_cy})...")
                                                        myt_rpc.touchDown(0, got_it_cx, got_it_cy)
                                                        time.sleep(random.uniform(0.05, 0.15))
                                                        myt_rpc.touchUp(0, got_it_cx, got_it_cy)
                                                        status_callback(f"{device_info}成功点击 'Got it' 按钮")
                                                        time.sleep(1.0)  # Wait after clicking
                                                    except Exception as e_got_it:
                                                        status_callback(f"{device_info}点击 'Got it' 按钮失败: {e_got_it}")
                                                else:
                                                    status_callback(f"{device_info}未找到 'Got it' 按钮 (如果之前已关闭提示，这是正常的)")
                                                
                                                time_after_comment_post = total_duration_seconds-(time.time()-loop_start_time)
                                                if time_after_comment_post > 0: time.sleep(min(random.uniform(1.0,2.0), time_after_comment_post))
                                            except Exception as e_post_reply:
                                                status_callback(f"{device_info}点击发布回复按钮错误 (XPath存在但点击失败): {e_post_reply}")
                                        else:
                                            status_callback(f"{device_info}未找到发布回复按钮，XPath: {POST_REPLY_BUTTON_XPATH}")
                                    else:
                                        status_callback(f"{device_info}通过MytRpc发送评论文本失败。")
                                except Exception as e_input_field:
                                    status_callback(f"{device_info}与回复输入框交互错误: {e_input_field}")
                            else:
                                status_callback(f"{device_info}未找到包含文本 '{COMMENT_REPLY_INPUT_PROMPT_TEXT}' 的回复输入框。")
                        except Exception as e: status_callback(f"{device_info}评论初始化或输入过程错误: {e}")
                    else: status_callback(f"{device_info}详情页未找到评论图标。")
                    pass  # 简化评论完成日志

                # 简化返回流程日志
                # 检查是否在Quote Tweet界面，如果是则点击返回
                if u2_device.xpath('//*[@text="Quote Tweet"]').exists:
                    screen_width_nav, screen_height_nav = u2_device.window_size() # Use different var names to avoid conflict
                    if screen_width_nav and screen_height_nav:
                        abs_x = int(0.163 * screen_width_nav)
                        abs_y = int(0.496 * screen_height_nav)
                        myt_rpc.touchDown(0, abs_x, abs_y)
                        time.sleep(random.uniform(0.05, 0.15))
                        myt_rpc.touchUp(0, abs_x, abs_y)
                    else:
                        u2_device.click(0.163, 0.496)
                
                # 先尝试点击退出按钮
                if u2_device.xpath('//*[@resource-id="com.twitter.android:id/exit_button"]').click_exists(timeout=3.0):
                    time.sleep(1.0)
                
                # 然后尝试点击导航返回按钮，但不使用pressBack避免退出应用
                if u2_device(description=NAVIGATE_UP_DESCRIPTION).click_exists(timeout=3.0):
                    pass  # 简化返回按钮日志
                
                # 避免调用myt_rpc.pressBack()，因为这可能会导致退出Twitter应用
                
                time_left_after_back = total_duration_seconds - (time.time() - loop_start_time)
                if time_left_after_back > 0: time.sleep(min(random.uniform(1.0, 2.0), time_left_after_back))
            
            except Exception as e_interact: status_callback(f"{device_info}主要推文互动过程错误: {e_interact}")
            time_left_total = total_duration_seconds - (time.time() - loop_start_time)
            if time_left_total <= 0: break

    status_callback(f"{device_info}[完成] 互动统计：滑动{swipes_done}次，互动{interaction_attempts}次，点赞{likes_done}个，评论{comments_done}个")
    return True # Indicate success

def run_interaction(status_callback, device_ip_address, u2_port, myt_rpc_port, duration_seconds, 
                    enable_liking_param, enable_commenting_param, comment_text_param="1"):
    """
    执行推特互动脚本
    """
    global _warmed_up_devices
    
    device_info = f"[{device_ip_address}:{u2_port}] "
    device_key = f"{device_ip_address}:{u2_port}"  # 使用IP和端口作为设备唯一标识
    
    status_callback(f"{device_info}开始推特互动脚本...")
    mytapi = MytRpc()
    status_callback(f"{device_info}MytRpc SDK 版本: {mytapi.get_sdk_version()}")
    u2_d = None
    
    # 使用通用连接函数连接uiautomator2设备
    u2_d, connect_success = connect_to_device(device_ip_address, u2_port, status_callback)
    if not connect_success:
        status_callback(f"{device_info}无法连接到uiautomator2设备，退出互动流程")
        return False
    
    if not mytapi.init(device_ip_address, myt_rpc_port, 10, max_retries=3):
        status_callback(f"{device_info}MytRpc无法连接到 {device_ip_address} 端口 {myt_rpc_port}。")
        return False
    
    if not mytapi.check_connect_state():
        status_callback(f"{device_info}MytRpc连接断开。")
        return False
    status_callback(f"{device_info}MytRpc已连接且连接状态正常。")
    
    # 检查Twitter应用是否运行并已登录
    initial_check_success = ensure_twitter_app_running_and_logged_in(u2_d, mytapi, status_callback, device_info)
    if not initial_check_success:
        status_callback(f"{device_info}⚠️ 初始检查显示Twitter应用可能有弹窗，但继续执行预热流程...")
        # 不立即返回False，而是继续执行预热流程，因为预热过程会多次重启应用并处理弹窗
    
    # 检查并处理Twitter对话框
    handle_update_now_dialog(u2_d, mytapi, status_callback, device_info)
    handle_keep_less_relevant_ads(u2_d, mytapi, status_callback, device_info)
    
    # 🆕 养号优化：智能预热 - 避免重复预热同一设备
    if device_key not in _warmed_up_devices:
        status_callback(f"{device_info}开始养号预热：执行关闭/打开APP操作（1次）...")
        twitter_package = "com.twitter.android"
        
        for i in range(1):
            try:
                status_callback(f"{device_info}预热操作 {i+1}/1：关闭Twitter应用...")
                
                # 使用uiautomator2关闭应用
                u2_d.app_stop(twitter_package)
                close_wait = random.uniform(2, 5)  # 随机等待2-5秒
                status_callback(f"{device_info}预热操作 {i+1}/1：等待应用关闭 {close_wait:.1f} 秒...")
                time.sleep(close_wait)
                
                # 额外确保应用完全关闭
                try:
                    u2_d.shell(f"am force-stop {twitter_package}")
                    time.sleep(random.uniform(1, 2))
                except Exception:
                    pass
                
                status_callback(f"{device_info}预热操作 {i+1}/1：启动Twitter应用...")
                
                # 启动Twitter应用
                u2_d.app_start(twitter_package)
                startup_wait = random.uniform(4, 8)  # 随机等待4-8秒，让应用完全加载
                status_callback(f"{device_info}预热操作 {i+1}/1：等待应用启动 {startup_wait:.1f} 秒...")
                time.sleep(startup_wait)
                
                # 检查应用是否成功启动
                try:
                    current_app = u2_d.app_current()
                    if current_app and current_app.get('package') == twitter_package:
                        status_callback(f"{device_info}预热操作 {i+1}/1：Twitter应用启动成功")
                    else:
                        status_callback(f"{device_info}预热操作 {i+1}/1：Twitter应用启动异常，当前应用: {current_app}")
                except Exception:
                    status_callback(f"{device_info}预热操作 {i+1}/1：无法检查当前应用状态")
                
                # 处理可能出现的对话框
                handle_update_now_dialog(u2_d, mytapi, status_callback, device_info)
                handle_keep_less_relevant_ads(u2_d, mytapi, status_callback, device_info)
                
                # 模拟用户浏览行为：随机轻微滑动
                try:
                    screen_width, screen_height = u2_d.window_size()
                    if screen_width and screen_height:
                        # 执行1-2次轻微滑动，模拟用户快速浏览
                        scroll_count = random.randint(1, 2)
                        for j in range(scroll_count):
                            start_x = int(screen_width / 2)
                            start_y = int(screen_height * random.uniform(0.6, 0.8))
                            end_y = int(screen_height * random.uniform(0.2, 0.4))
                            scroll_duration = random.randint(500, 1200)
                            
                            mytapi.exec_cmd(f"input swipe {start_x} {start_y} {start_x} {end_y} {scroll_duration}")
                            scroll_pause = random.uniform(0.8, 2.0)
                            time.sleep(scroll_pause)
                        
                        status_callback(f"{device_info}预热操作 {i+1}/1：执行了 {scroll_count} 次模拟浏览滑动")
                except Exception as e:
                    status_callback(f"{device_info}预热操作 {i+1}/1：模拟滑动异常: {e}")
                
                # 在应用内随机等待，模拟用户查看内容
                browse_time = random.uniform(2, 5)  # 只有一次操作，使用较短的等待时间
                
                status_callback(f"{device_info}预热操作 {i+1}/1：模拟用户浏览 {browse_time:.1f} 秒...")
                time.sleep(browse_time)
                
            except Exception as e:
                status_callback(f"{device_info}预热操作 {i+1}/1 出现异常: {e}")
                # 如果出错，尝试简单的重启
                try:
                    u2_d.app_start(twitter_package)
                    time.sleep(3)
                except Exception:
                    pass
        
        # 标记该设备已完成预热
        _warmed_up_devices.add(device_key)
        status_callback(f"{device_info}养号预热完成，开始正式互动...")
    else:
        status_callback(f"{device_info}🔥 设备已预热过，跳过预热步骤，直接开始互动...")
    
    # 🆕 最后检查Twitter应用状态 - 更宽松的检查方式
    status_callback(f"{device_info}进行最终状态检查...")
    final_check_success = ensure_twitter_app_running_and_logged_in(u2_d, mytapi, status_callback, device_info)
    
    if not final_check_success:
        status_callback(f"{device_info}⚠️ 最终检查未通过，但可能只是弹窗问题，尝试继续执行...")
        
        # 尝试基本的弹窗清理
        try:
            status_callback(f"{device_info}尝试最后的弹窗清理...")
            
            # 处理常见弹窗
            if u2_d.xpath('//*[@text="Update now"]').exists:
                if u2_d.xpath('//*[@text="Not now"]').click_exists(timeout=2):
                    status_callback(f"{device_info}关闭了更新弹窗")
                    time.sleep(2)
            
            if u2_d(text="Keep less relevant ads").exists:
                if u2_d(text="Keep less relevant ads").click_exists(timeout=2):
                    status_callback(f"{device_info}处理了广告弹窗")
                    time.sleep(2)
            
            # 检查是否有基本的Twitter界面元素
            basic_ui_elements = [
                '//*[@resource-id="com.twitter.android:id/channels"]',
                '//*[@content-desc="Home"]',
                '//*[@resource-id="com.twitter.android:id/timeline"]'
            ]
            
            has_basic_ui = False
            for element_xpath in basic_ui_elements:
                if u2_d.xpath(element_xpath).exists:
                    status_callback(f"{device_info}✅ 检测到基本UI元素: {element_xpath}")
                    has_basic_ui = True
                    break
            
            if has_basic_ui:
                status_callback(f"{device_info}✅ 检测到Twitter基本界面，继续执行互动...")
            else:
                status_callback(f"{device_info}❌ 未检测到Twitter基本界面，但仍尝试继续执行...")
                
        except Exception as e:
            status_callback(f"{device_info}最终清理尝试失败: {e}")
    else:
        status_callback(f"{device_info}✅ 最终检查通过，Twitter应用状态正常")
    
    # 再次处理可能的对话框
    handle_update_now_dialog(u2_d, mytapi, status_callback, device_info)
    handle_keep_less_relevant_ads(u2_d, mytapi, status_callback, device_info)
    
    if u2_d:
        result = slow_scroll_down_and_interact(status_callback, mytapi, u2_d, device_info,
                                      total_duration_seconds=duration_seconds,
                                      enable_liking=enable_liking_param,
                                      enable_commenting=enable_commenting_param,
                                      prob_like_opened=0.60, 
                                      prob_comment_opened=0.40,
                                      comment_text=comment_text_param
                                      )
        status_callback(f"{device_info}--- 互动脚本完成 ---")
        return result
    else: 
        status_callback(f"{device_info}uiautomator2设备不可用，无法执行滚动互动。")
        return False

if __name__ == '__main__':
    def console_status_callback(message):
        __builtins__.print(message)

    console_status_callback("Running interactTest.py as a standalone script.")

    if len(sys.argv) < 7: # ip, u2_port, myt_port, duration, liking, commenting
        console_status_callback("Usage: python interactTest.py <device_ip> <u2_port> <myt_rpc_port> <duration_seconds> <enable_liking (true/false)> <enable_commenting (true/false)> [comment_text]")
        sys.exit(1)

    test_device_ip = sys.argv[1]
    try:
        test_u2_port = int(sys.argv[2])
        test_myt_rpc_port = int(sys.argv[3])
        test_duration = int(sys.argv[4])
    except ValueError:
        console_status_callback("Error: Ports and Duration must be integers.")
        sys.exit(1)
    test_enable_liking = sys.argv[5].lower() == 'true'
    test_enable_commenting = sys.argv[6].lower() == 'true'
    
    # Use the optional comment_text argument if provided
    test_comment_text = sys.argv[7] if len(sys.argv) > 7 else "1"

    success = run_interaction(console_status_callback, test_device_ip, test_u2_port, test_myt_rpc_port, test_duration, test_enable_liking, test_enable_commenting, test_comment_text)
    
    if success:
        console_status_callback("Standalone interaction script completed.")
    else:
        console_status_callback("Standalone interaction script failed or encountered an issue.")
    sys.exit(0 if success else 1) 