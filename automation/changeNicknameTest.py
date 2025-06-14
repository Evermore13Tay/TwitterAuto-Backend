import time
import sys
import os
import traceback
import subprocess
import uiautomator2 as u2
from common.mytRpc import MytRpc
import random
from common.u2_connection import connect_to_device
from common.twitter_ui_handlers import handle_update_now_dialog, handle_keep_less_relevant_ads, ensure_twitter_app_running_and_logged_in

# --- Constants for Selectors (can be adjusted as needed) ---
# Shared with changeProfileTest.py initially
CHANNELS_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/channels"]'
NAVIGATION_DRAWER_DESCRIPTION = "Show navigation drawer"
PROFILE_SCROLL_VIEW_XPATH = '//*[@resource-id="com.twitter.android:id/compose_content"]/android.view.View[1]/android.view.View[1]/android.widget.ScrollView[1]/android.view.View[1]'
EDIT_PROFILE_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/button_edit_profile"]'

# Nickname specific (will need actual XPaths/selectors from UI inspection)
NICKNAME_INPUT_FIELD_XPATH = '//*[@resource-id="com.twitter.android:id/edit_name"]' # Updated XPath
SAVE_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/save"]' # Shared with profile photo change
# Potentially a "Navigate up" or similar after saving if needed.

DEFAULT_NEW_NICKNAME = "TestNickname123"

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

def run_change_nickname(status_callback, device_ip_address, u2_port, myt_rpc_port, new_nickname):
    device_info = f"[{device_ip_address}:{u2_port}] "
    status_callback(f"{device_info}--- 修改昵称开始 ---")
    u2_d = None
    mytapi = MytRpc()
    action_successful = True

    status_callback(f"{device_info}MytRpc SDK 版本: {mytapi.get_sdk_version()}")
    
    # 使用通用函数连接到uiautomator2设备
    u2_d, connect_success = connect_to_device(device_ip_address, u2_port, status_callback)
    if not connect_success:
        status_callback(f"{device_info}无法连接到uiautomator2设备，退出修改昵称流程")
        return False

    if not mytapi.init(device_ip_address, myt_rpc_port, 10, max_retries=3):
        status_callback(f"MytRpc failed to connect to device {device_ip_address} on port {myt_rpc_port}. Exiting.")
        return False
    
    if not mytapi.check_connect_state():
        status_callback("MytRpc connection is disconnected. Exiting.")
        return False
    status_callback("MytRpc connected and connection state is normal.")

    # 检查Twitter应用是否运行并已登录
    if not ensure_twitter_app_running_and_logged_in(u2_d, mytapi, status_callback, device_info):
        status_callback(f"{device_info}Twitter应用未运行或用户未登录，退出修改昵称流程")
        return False

    # 使用通用函数处理Update Now对话框
    handle_update_now_dialog(u2_d, mytapi, status_callback, device_info)
    handle_keep_less_relevant_ads(u2_d, mytapi, status_callback, device_info)

    # ---- Navigation to Edit Profile Screen ----
    # Click 'channels' button
    status_callback(f"Attempting to find and click element with XPath: {CHANNELS_BUTTON_XPATH}")
    channels_element_xpath_obj = u2_d.xpath(CHANNELS_BUTTON_XPATH)
    if channels_element_xpath_obj.wait(timeout=5.0):
        if click_element_center_mytapi_refactored(mytapi, channels_element_xpath_obj, status_callback):
            status_callback("Successfully clicked channels element."); time.sleep(3.5)
        else: status_callback(f"Failed to click channels (XPath: {CHANNELS_BUTTON_XPATH})."); action_successful = False
    else: status_callback(f"Element (XPath: {CHANNELS_BUTTON_XPATH}) not found."); action_successful = False

    # Click 'Show navigation drawer'
    if action_successful:
        status_callback(f"Attempting to find and click element with content-desc: '{NAVIGATION_DRAWER_DESCRIPTION}'")
        nav_drawer_ui_obj = u2_d(description=NAVIGATION_DRAWER_DESCRIPTION)
        if nav_drawer_ui_obj.wait(timeout=5.0):
            if click_element_center_mytapi_refactored(mytapi, nav_drawer_ui_obj, status_callback):
                status_callback("Successfully clicked navigation drawer element."); time.sleep(3.5)
            else: status_callback(f"Failed to click navigation drawer ('{NAVIGATION_DRAWER_DESCRIPTION}')."); action_successful = False
        else: status_callback(f"Element ('{NAVIGATION_DRAWER_DESCRIPTION}') not found."); action_successful = False
    
    # Click profile scroll view area
    if action_successful:
        status_callback(f"Attempting to click profile scroll view area (XPath: {PROFILE_SCROLL_VIEW_XPATH})")
        profile_scroll_obj = u2_d.xpath(PROFILE_SCROLL_VIEW_XPATH)
        if profile_scroll_obj.wait(timeout=5.0):
            if click_element_center_mytapi_refactored(mytapi, profile_scroll_obj, status_callback):
                status_callback("Clicked profile scroll view area."); time.sleep(3.5)
            else: status_callback("Failed to click profile scroll view area."); action_successful = False
        else: status_callback("Profile scroll view area not found."); action_successful = False
    
    # Click edit profile button
    if action_successful:
        status_callback(f"Attempting to click edit profile button (XPath: {EDIT_PROFILE_BUTTON_XPATH})")
        edit_profile_obj = u2_d.xpath(EDIT_PROFILE_BUTTON_XPATH)
        if edit_profile_obj.wait(timeout=5.0):
            if click_element_center_mytapi_refactored(mytapi, edit_profile_obj, status_callback):
                status_callback("Clicked edit profile button."); time.sleep(3.5) # Wait for edit screen
            else: status_callback("Failed to click edit profile button."); action_successful = False
        else: status_callback("Edit profile button not found."); action_successful = False
    # ---- End Navigation to Edit Profile Screen ----

    # ---- Change Nickname Logic ----
    if action_successful:
        status_callback("Locating nickname input field...")
        nickname_field_xpath_obj = u2_d.xpath(NICKNAME_INPUT_FIELD_XPATH)
        if nickname_field_xpath_obj.wait(timeout=5.0):
            status_callback("Nickname field found.")
            # Click the field first to ensure focus, using MytRpc as per original structure for clicks
            if click_element_center_mytapi_refactored(mytapi, nickname_field_xpath_obj, status_callback):
                time.sleep(1.0) # Pause for focus
                status_callback(f"Attempting to clear (via long-press, select all, delete) and set new nickname to: {new_nickname}")
                try:
                    # --- New clear logic: Long-press, Select All, Delete ---
                    status_callback("Performing long click on nickname field for text selection...")
                    nickname_field_xpath_obj.long_click() # Removed duration argument
                    time.sleep(1.0) # Wait for context menu or selection handles

                    # Attempt to click "Select all"
                    # Common English text. If device is in Chinese, this might be different (e.g., "全选")
                    select_all_button = u2_d(textContains="Select all") # Using textContains for flexibility
                    if not select_all_button.wait(timeout=2.0):
                        # Fallback for Chinese if English "Select all" is not found
                        status_callback("'Select all' not found, trying Chinese '全选'...")
                        select_all_button = u2_d(textContains="全选")
                    
                    if select_all_button.wait(timeout=2.0): # Check again with potentially new selector
                        status_callback("'Select all' (or equivalent) button found. Clicking it...")
                        select_all_button.click()
                        time.sleep(0.5) # Wait for text to be selected
                        status_callback("Pressing delete to clear selected text...")
                        u2_d.press("delete")
                        time.sleep(0.5) # Pause after deleting
                        status_callback("Text clearing attempt (select all + delete) finished.")
                    else:
                        status_callback("'Select all' (or equivalent) button not found after long click. Falling back to sending backspaces as previous attempt.")
                        # Fallback to old backspace method if select all fails
                        current_text = nickname_field_xpath_obj.get_text()
                        if current_text:
                            status_callback(f"Fallback: Current text is '{current_text}'. Sending backspaces...")
                            for _ in range(len(current_text) + 5):
                                u2_d.press("delete")
                                time.sleep(0.05)
                            status_callback("Fallback: Backspace sequence completed.")
                            time.sleep(0.5)
                        else:
                            status_callback("Fallback: Nickname field is already empty or get_text() returned empty.")
                    # --- End new clear logic ---

                    status_callback(f"Typing new nickname (via MytRpc): {new_nickname}")
                    if send_text_char_by_char(mytapi, new_nickname, status_callback):
                        status_callback(f"Successfully typed nickname '{new_nickname}' via MytRpc.")
                        time.sleep(2) # User requested sleep

                    # Click Save button
                    status_callback(f"Locating and clicking Save button (XPath: {SAVE_BUTTON_XPATH})...")
                    save_button_obj = u2_d.xpath(SAVE_BUTTON_XPATH)
                    if save_button_obj.wait(timeout=5.0):
                        if click_element_center_mytapi_refactored(mytapi, save_button_obj, status_callback): # Using MytRpc for click as per pattern
                            status_callback("Save button clicked.")
                            time.sleep(2) # User requested sleep
                            
                            # Click Navigate up
                            status_callback("Attempting to click 'Navigate up' button after save...")
                            # Using descriptionContains for flexibility as it's a common pattern
                            navigate_up_after_save_obj = u2_d(descriptionContains="Navigate up") 
                            if navigate_up_after_save_obj.wait(timeout=5.0):
                                # Click using u2_d directly for this navigation as it's simpler
                                navigate_up_after_save_obj.click()
                                status_callback("'Navigate up' button clicked after saving nickname.")
                            else:
                                status_callback("'Navigate up' button not found after saving nickname.")
                                # Not critical enough to set action_successful to False perhaps
                        else: 
                            status_callback("Failed to click Save button."); action_successful = False
                    else: 
                        status_callback("Save button not found."); action_successful = False
                except Exception as e_set_text:
                    status_callback(f"Error during nickname editing (clear or type): {e_set_text}")
                    action_successful = False
            else: 
                status_callback("Failed to click/focus nickname input field."); action_successful = False
        else: 
            status_callback(f"Nickname input field (XPath: {NICKNAME_INPUT_FIELD_XPATH}) not found."); action_successful = False
    # ---- End Change Nickname Logic ----

    status_callback(f"--- Change Nickname Script Finished ('{'SUCCESS' if action_successful else 'FAILURES ENCOUNTERED'}') ---")
    return action_successful

if __name__ == '__main__':
    def console_status_callback(message):
        print(message)

    console_status_callback("Running changeNicknameTest.py as a standalone script.")

    # Default values
    test_device_ip = "192.168.8.74"
    test_u2_port = 5006
    test_myt_rpc_port = 11060
    test_new_nickname = DEFAULT_NEW_NICKNAME # Use the constant defined at the top

    if len(sys.argv) == 5:
        console_status_callback("Using command-line arguments.")
        test_device_ip = sys.argv[1]
        try:
            test_u2_port = int(sys.argv[2])
            test_myt_rpc_port = int(sys.argv[3])
        except ValueError:
            console_status_callback("Error: u2_port and myt_rpc_port must be integers when provided via command line. Exiting.")
            sys.exit(1)
        test_new_nickname = sys.argv[4]
    elif len(sys.argv) > 1 and len(sys.argv) < 5:
        console_status_callback("Warning: Insufficient command-line arguments. Expected 4 (device_ip u2_port myt_rpc_port new_nickname) or 0 for defaults.")
        console_status_callback(f"Using default values: IP={test_device_ip}, u2Port={test_u2_port}, mytPort={test_myt_rpc_port}, Nickname={test_new_nickname}")
    else: # len(sys.argv) == 1 or len(sys.argv) > 5 (treat as using defaults if too many either)
        console_status_callback(f"No command-line arguments or incorrect number provided. Using default values: IP={test_device_ip}, u2Port={test_u2_port}, mytPort={test_myt_rpc_port}, Nickname={test_new_nickname}")

    success = run_change_nickname(console_status_callback, test_device_ip, test_u2_port, test_myt_rpc_port, test_new_nickname)
    
    if success:
        console_status_callback("Standalone nickname change script completed successfully.")
    else:
        console_status_callback("Standalone nickname change script encountered issues or failed.")
    sys.exit(0 if success else 1) 