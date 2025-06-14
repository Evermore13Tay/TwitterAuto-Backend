import time
import sys
import uiautomator2 as u2
from common.mytRpc import MytRpc
import random
import traceback
from common.u2_connection import connect_to_device
from common.twitter_ui_handlers import handle_update_now_dialog, handle_keep_less_relevant_ads, ensure_twitter_app_running_and_logged_in

# --- Constants for Selectors ---
SEARCH_EXPLORE_BUTTON_XPATH = '//*[@content-desc="Search and Explore"]/android.view.View[1]'
QUERY_VIEW_XPATH = '//*[@resource-id="com.twitter.android:id/query_view"]'
ACTIVE_SEARCH_INPUT_XPATH = '//*[@resource-id="com.twitter.android:id/query"]'
# USER_PROFILE_TEXT_XPATH_TEMPLATE will be formatted with the username
FOLLOW_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/button_bar_follow"]'
NAVIGATE_UP_BUTTON_DESC = "Navigate up"
CHANNELS_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/channels"]'

DEFAULT_USERNAME_TO_FOLLOW = "taylorswift13"

def click_element_center_mytapi_refactored(myt_rpc, u2_element, status_callback):
    try:
        bounds = u2_element.info['bounds']
        center_x = (bounds['left'] + bounds['right']) // 2
        center_y = (bounds['top'] + bounds['bottom']) // 2
        status_callback(f"Clicking at element center ({center_x}, {center_y}) using MytRpc...")
        finger_id = 0
        myt_rpc.touchDown(finger_id, center_x, center_y)
        time.sleep(random.uniform(0.05, 0.15))
        myt_rpc.touchUp(finger_id, center_x, center_y)
        status_callback("Clicked successfully with MytRpc.")
        return True
    except Exception as e:
        status_callback(f"Error during MytRpc click: {e}")
        return False

def send_text_char_by_char(myt_rpc_device, text_to_send, status_callback, char_delay=0.1):
    status_callback(f"Simulating typing: {text_to_send}")
    for char_index, char in enumerate(text_to_send):
        if not myt_rpc_device.sendText(char):
            status_callback(f"MytRpc sendText failed for character: '{char}' at index {char_index}")
            return False
        time.sleep(char_delay)
    status_callback("Simulated typing complete.")
    return True

def clear_text_field_long_click(u2_d, field_xpath_obj, status_callback):
    status_callback("Checking if text field needs to be cleared...")
    try:
        current_text = field_xpath_obj.get_text()
        # Skip clearing for placeholder text "Search Twitter" or empty field
        if current_text and len(current_text) > 0 and current_text != "Search Twitter" and current_text != "搜索 Twitter":
            status_callback(f"Field has real user-entered text ('{current_text}'). Proceeding with clear.")
            field_xpath_obj.long_click()
            time.sleep(1.0)

            select_all_button = u2_d(textContains="Select all")
            if not select_all_button.wait(timeout=2.0):
                status_callback("'Select all' not found, trying Chinese '全选'...")
                select_all_button = u2_d(textContains="全选")
            
            if select_all_button.wait(timeout=2.0):
                status_callback("'Select all' (or equivalent) button found. Clicking it...")
                select_all_button.click()
                time.sleep(0.5)
                status_callback("Pressing delete to clear selected text...")
                u2_d.press("delete")
                time.sleep(0.5)
                status_callback("Text clearing attempt (select all + delete) finished.")
                return True
            else:
                status_callback("'Select all' (or equivalent) button not found. Falling back to sending backspaces.")
                # The original fallback to backspaces is still here if select all fails after long click
                if field_xpath_obj.get_text() and field_xpath_obj.get_text() != "Search Twitter" and field_xpath_obj.get_text() != "搜索 Twitter": # Re-check text before backspacing
                    status_callback(f"Fallback: Current text is '{field_xpath_obj.get_text()}'. Sending backspaces...")
                    for _ in range(len(field_xpath_obj.get_text()) + 5): # Send a few extra backspaces
                        u2_d.press("delete") # 'delete' key event often acts as backspace
                        time.sleep(0.05)
                    status_callback("Fallback: Backspace sequence completed.")
                else:
                    status_callback("Fallback: Field is already empty, has placeholder, or get_text() returned empty after failed select all.")
                return True # Fallback attempted
        else:
            if current_text == "Search Twitter" or current_text == "搜索 Twitter":
                status_callback(f"Field only has placeholder text ('{current_text}'). No clearing needed.")
            elif not current_text:
                status_callback("Field is already empty. No clearing needed.")
            else:
                status_callback(f"Field has text '{current_text}', but recognized as placeholder. No clearing needed.")
            return True # No action needed, field has placeholder or is empty

    except Exception as e:
        status_callback(f"Error during text field clearing: {e}")
        return False

def hide_keyboard(u2_d, mytapi, status_callback, retry_context=""):
    """
    关闭输入法键盘 - 通过停止输入法应用实现
    
    Args:
        u2_d: uiautomator2设备对象 (unused in this version, kept for signature compatibility)
        mytapi: MytRpc对象
        status_callback: 状态回调函数
        retry_context: 可选的上下文说明，用于日志
    """
    keyboard_package_name = "com.iflytek.inputmethod"
    status_callback(f"尝试关闭输入法键盘 {retry_context}通过停止应用: {keyboard_package_name}...")
    try:
        # 使用 MytRpc 执行 am force-stop 命令
        command = f"am force-stop {keyboard_package_name}"
        status_callback(f"执行命令: {command}")
        if mytapi.exec_cmd(command):
            status_callback(f"成功发送 force-stop 命令给 {keyboard_package_name}.")
            time.sleep(1.0) # 等待应用停止
        else:
            status_callback(f"发送 force-stop 命令给 {keyboard_package_name} 失败.")

        status_callback("键盘关闭流程 (force-stop) 结束.")
    except Exception as e:
        status_callback(f"关闭输入法键盘 (force-stop) 时出错: {e}")

def run_follow_user(status_callback, device_ip_address, u2_port, myt_rpc_port, username_to_follow):
    device_info = f"[{device_ip_address}:{u2_port}] "
    status_callback(f"{device_info}--- 关注用户开始 ---")
    mytapi = MytRpc()
    status_callback(f"{device_info}MytRpc SDK 版本: {mytapi.get_sdk_version()}")
    
    u2_d = None
    action_successful = True

    # 连接到设备
    u2_d, connect_success = connect_to_device(device_ip_address, u2_port, status_callback)
    if not connect_success:
        status_callback(f"{device_info}无法连接到uiautomator2设备，退出关注用户流程")
        return False

    if not mytapi.init(device_ip_address, myt_rpc_port, 10, max_retries=3):
        status_callback(f"{device_info}MytRpc failed to connect to device {device_ip_address} on port {myt_rpc_port}. Exiting.")
        return False
    
    if not mytapi.check_connect_state():
        status_callback(f"{device_info}MytRpc connection is disconnected. Exiting.")
        return False
    status_callback(f"{device_info}MytRpc connected and connection state is normal.")
    
    # 检查Twitter应用是否运行并已登录
    if not ensure_twitter_app_running_and_logged_in(u2_d, mytapi, status_callback, device_info):
        status_callback(f"{device_info}Twitter应用未运行或用户未登录，退出关注用户流程")
        return False
    
    # 处理可能出现的对话框
    handle_update_now_dialog(u2_d, mytapi, status_callback, device_info)
    handle_keep_less_relevant_ads(u2_d, mytapi, status_callback, device_info)

    # Step 0: Ensure on Home/Main screen by clicking Channels button
    status_callback(f"Step 0: Ensuring on Home screen by clicking Channels button (XPath: {CHANNELS_BUTTON_XPATH})")
    channels_button_home_obj = u2_d.xpath(CHANNELS_BUTTON_XPATH)
    if channels_button_home_obj.wait(timeout=7.0):
        if not click_element_center_mytapi_refactored(mytapi, channels_button_home_obj, status_callback):
            status_callback("Warning: Failed to click Channels button to ensure home screen. Continuing...")
            # Not necessarily fatal, script might still work if already on a suitable page.
        else:
            status_callback("Clicked Channels button successfully."); time.sleep(2) # Allow UI to settle
    else:
        status_callback("Warning: Channels button for ensuring home screen not found. Continuing...")

    # Step 1: Click Search and Explore
    if action_successful:
        status_callback(f"Step 1: Clicking Search/Explore button (XPath: {SEARCH_EXPLORE_BUTTON_XPATH})")
        search_explore_obj = u2_d.xpath(SEARCH_EXPLORE_BUTTON_XPATH)
        if search_explore_obj.wait(timeout=7.0):
            if not click_element_center_mytapi_refactored(mytapi, search_explore_obj, status_callback):
                action_successful = False; status_callback("Failed to click Search/Explore button.")
            else: time.sleep(2)
        else:
            action_successful = False; status_callback("Search/Explore button not found.")

    # Step 2: Click Query View
    if action_successful:
        status_callback(f"Step 2: Clicking Query View (XPath: {QUERY_VIEW_XPATH})")
        query_view_obj = u2_d.xpath(QUERY_VIEW_XPATH)
        if query_view_obj.wait(timeout=5.0):
            if not click_element_center_mytapi_refactored(mytapi, query_view_obj, status_callback):
                action_successful = False; status_callback("Failed to click Query View.")
            else: time.sleep(1)
        else:
            action_successful = False; status_callback("Query View not found.")

    # Step 3: Input text (username_to_follow)
    if action_successful:
        status_callback(f"Step 3: Targeting active search input field '{ACTIVE_SEARCH_INPUT_XPATH}' to clear and input username '{username_to_follow}'.")
        # After clicking query_view (Step 2), the actual input field is ACTIVE_SEARCH_INPUT_XPATH
        active_search_input_obj = u2_d.xpath(ACTIVE_SEARCH_INPUT_XPATH)
        
        if active_search_input_obj.wait(timeout=7.0): # Increased timeout for it to appear
            status_callback(f"Active search input field '{ACTIVE_SEARCH_INPUT_XPATH}' found.")
            if clear_text_field_long_click(u2_d, active_search_input_obj, status_callback):
                status_callback(f"Attempting to type '{username_to_follow}' using MytRpc (char_delay=0.5s)...")
                if send_text_char_by_char(mytapi, username_to_follow, status_callback, char_delay=0.5):
                    status_callback(f"Successfully typed '{username_to_follow}' using MytRpc.")
                    time.sleep(1) # Short wait for input to be processed
                    
                    # 关闭输入法键盘
                    hide_keyboard(u2_d, mytapi, status_callback)
                    
                    time.sleep(2.5) # Wait for search results
                else:
                    status_callback(f"MytRpc typing failed for '{username_to_follow}'. Trying uiautomator2 fallback...")
                    # Fallback to uiautomator2 char-by-char
                    typing_success_u2 = True
                    for char_to_send in username_to_follow:
                        try:
                            u2_d.send_keys(char_to_send)
                            time.sleep(0.5) # 0.5s delay for u2 fallback
                        except Exception as e_char_send_u2:
                            status_callback(f"Error sending character '{char_to_send}' with uiautomator2: {e_char_send_u2}")
                            typing_success_u2 = False
                            break
                    if typing_success_u2:
                        status_callback(f"Successfully typed '{username_to_follow}' using uiautomator2 fallback.")
                        time.sleep(1) # Short wait for input to be processed
                        
                        # 关闭输入法键盘
                        hide_keyboard(u2_d, mytapi, status_callback)
                        
                        time.sleep(2.5)
                    else:
                        status_callback(f"Both MytRpc and uiautomator2 typing failed for '{username_to_follow}'.")
                        action_successful = False

            else:
                action_successful = False; status_callback(f"Failed to prepare text field for input.")
        else:
            # Try clicking search again then looking for the input field
            status_callback("Input field not found. Trying to click query view again...")
            query_view_retry = u2_d.xpath(QUERY_VIEW_XPATH)
            if query_view_retry.wait(timeout=5.0):
                if click_element_center_mytapi_refactored(mytapi, query_view_retry, status_callback):
                    time.sleep(2)
                    # Now try the toolbar_search as a different selector
                    toolbar_search = u2_d.xpath('//*[@resource-id="com.twitter.android:id/toolbar_search"]')
                    if toolbar_search.wait(timeout=5.0):
                        if click_element_center_mytapi_refactored(mytapi, toolbar_search, status_callback):
                            time.sleep(1)
                            # After clicking toolbar_search, try sending keys (MytRpc primary, u2 fallback)
                            try:
                                status_callback("Attempting to type in retry: MytRpc primary (char_delay=0.5s)...")
                                if send_text_char_by_char(mytapi, username_to_follow, status_callback, char_delay=0.5):
                                    status_callback("Successfully typed in retry using MytRpc.")
                                    time.sleep(1) # Short wait for input to be processed
                                    
                                    # 关闭输入法键盘
                                    hide_keyboard(u2_d, mytapi, status_callback, "(retry)")
                                    
                                    time.sleep(3) # Longer wait
                                else:
                                    status_callback("MytRpc typing failed in retry. Trying uiautomator2 fallback...")
                                    retry_typing_success_u2 = True
                                    for char_to_send_retry in username_to_follow:
                                        try:
                                            u2_d.send_keys(char_to_send_retry)
                                            time.sleep(0.5)
                                        except Exception as e_retry_char_send_u2:
                                            status_callback(f"Error sending char '{char_to_send_retry}' in u2 retry: {e_retry_char_send_u2}")
                                            retry_typing_success_u2 = False
                                            break
                                    if retry_typing_success_u2:
                                        status_callback("Successfully typed in retry using uiautomator2 fallback.")
                                        time.sleep(1) # Short wait for input to be processed
                                        
                                        # 关闭输入法键盘
                                        hide_keyboard(u2_d, mytapi, status_callback, "(retry-u2)")
                                        
                                        time.sleep(3)
                                    else:
                                        status_callback("Both MytRpc and uiautomator2 typing failed in retry.")
                                        action_successful = False
                            except Exception as e_retry_input_block:
                                status_callback(f"Error during text input block in retry: {e_retry_input_block}")
                        else:
                            action_successful = False; status_callback("Failed to click toolbar_search in retry.")
                    else:
                        action_successful = False; status_callback("toolbar_search not found in retry.")
                else:
                    action_successful = False; status_callback("Failed to click query_view in retry.")
            else:
                action_successful = False; status_callback(f"Query view not found in retry. Search flow cannot continue.")

    # Step 4: Click the user profile text (e.g., @taylorswift13)
    if action_successful:
        # Username in results often appears with '@' prefix
        user_profile_text_to_find = f"@{username_to_follow}"
        user_profile_xpath = f'//*[@text="{user_profile_text_to_find}"]'
        status_callback(f"Step 4: Checking existence and clicking user profile text (XPath: {user_profile_xpath})")
        user_profile_obj = u2_d.xpath(user_profile_xpath)
        
        # Use .exists to check immediately
        if user_profile_obj.exists:
            status_callback(f"User profile '{user_profile_text_to_find}' found. Clicking...")
            if not click_element_center_mytapi_refactored(mytapi, user_profile_obj, status_callback):
                action_successful = False; status_callback(f"Failed to click user profile '{user_profile_text_to_find}'.")
            else: 
                time.sleep(3) # Wait for profile to load
        else:
            action_successful = False
            status_callback(f"User profile text '{user_profile_text_to_find}' not found immediately.")
            status_callback("执行 '未找到用户' 回退操作...")
            # Click Collapse
            collapse_desc = "Collapse"
            status_callback(f"  尝试点击 '{collapse_desc}'...")
            if u2_d(description=collapse_desc).click_exists(timeout=3.0):
                status_callback(f"  已点击 '{collapse_desc}'.")
                time.sleep(1.0)
            else:
                status_callback(f"  '{collapse_desc}' 未找到或点击失败.")
            # Click Navigate up
            status_callback(f"  尝试点击 '{NAVIGATE_UP_BUTTON_DESC}'...")
            if u2_d(description=NAVIGATE_UP_BUTTON_DESC).click_exists(timeout=3.0):
                status_callback(f"  已点击 '{NAVIGATE_UP_BUTTON_DESC}'.")
                time.sleep(1.0)
            else:
                status_callback(f"  '{NAVIGATE_UP_BUTTON_DESC}' 未找到或点击失败.")
            # Click Channels button
            status_callback(f"  尝试点击 Channels 按钮 ({CHANNELS_BUTTON_XPATH})...")
            if u2_d.xpath(CHANNELS_BUTTON_XPATH).click_exists(timeout=3.0):
                status_callback("  已点击 Channels 按钮.")
                time.sleep(1.0)
            else:
                status_callback("  Channels 按钮未找到或点击失败.")
            # Log specific message
            status_callback("没有找到该用户")

    # Step 5: Click Follow button using u2.click_exists()
    if action_successful:
        status_callback(f"Step 5: Attempting to click Follow button (XPath: {FOLLOW_BUTTON_XPATH}) using u2.click_exists()")
        follow_button = u2_d.xpath(FOLLOW_BUTTON_XPATH)
        if follow_button.click_exists(timeout=5.0):
            status_callback("Follow button clicked (or was already followed/not present in expected state).")
            time.sleep(2)
        else:
            status_callback("Follow button click_exists failed or timed out. Might already be followed or button not found.")
            # Not necessarily setting action_successful to False, as it might be a non-critical failure if already following.

    # Step 6: Click Navigate up
    if action_successful: # Even if follow was ambiguous, try to navigate back
        status_callback(f"Step 6: Clicking Navigate up button (Desc: {NAVIGATE_UP_BUTTON_DESC})")
        nav_up_obj = u2_d(description=NAVIGATE_UP_BUTTON_DESC)
        if nav_up_obj.wait(timeout=5.0):
            # Using u2_d click for navigation is often simpler
            nav_up_obj.click()
            status_callback("Clicked Navigate up."); time.sleep(2)
        else:
            status_callback("Navigate up button not found after follow attempt.")
            # Potentially not fatal for the whole script's success if the main goal (follow) might have occurred.

    # Step 7: Click Channels button
    if action_successful: # Attempt to return to a known state
        status_callback(f"Step 7: Clicking Channels button (XPath: {CHANNELS_BUTTON_XPATH})")
        channels_obj = u2_d.xpath(CHANNELS_BUTTON_XPATH)
        if channels_obj.wait(timeout=5.0):
            if not click_element_center_mytapi_refactored(mytapi, channels_obj, status_callback):
                 status_callback("Failed to click Channels button at the end.") # Log, but don't fail the whole script based on this last nav
            else: time.sleep(1)
        else:
            status_callback("Channels button not found at the end.")

    status_callback(f"{device_info}--- Follow User Script Finished for '{username_to_follow}'. Overall Status: {'SUCCESS' if action_successful else 'FAILURES ENCOUNTERED'} ---")
    return action_successful

if __name__ == '__main__':
    def console_status_callback(message):
        print(message)

    console_status_callback("Running followTest.py as a standalone script.")

    test_device_ip = "192.168.8.74"
    test_u2_port = 5006
    test_myt_rpc_port = 11060
    username_arg = DEFAULT_USERNAME_TO_FOLLOW

    # Args: ip u2_port myt_port [username_to_follow]
    if len(sys.argv) >= 5:
        console_status_callback("Using command-line arguments.")
        test_device_ip = sys.argv[1]
        try:
            test_u2_port = int(sys.argv[2])
            test_myt_rpc_port = int(sys.argv[3])
        except ValueError:
            console_status_callback("Error: u2_port and myt_rpc_port must be integers. Exiting."); sys.exit(1)
        username_arg = sys.argv[4]
    elif len(sys.argv) > 1 and len(sys.argv) < 4 : # Handles cases like 2 or 3 args but not enough for username
        console_status_callback(f"Warning: Insufficient command-line arguments. Expected 0 or 4. Using defaults.")
    else:
        console_status_callback(f"No/default command-line arguments. Using default values: IP={test_device_ip}, Username='{username_arg}'")

    success = run_follow_user(console_status_callback, test_device_ip, test_u2_port, test_myt_rpc_port, username_arg)
    
    if success:
        console_status_callback(f"Standalone follow user script for '{username_arg}' completed successfully.")
    else:
        console_status_callback(f"Standalone follow user script for '{username_arg}' encountered issues or failed.")
    sys.exit(0 if success else 1) 