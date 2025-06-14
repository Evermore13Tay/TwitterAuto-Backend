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

# --- Constants for Selectors --- 
CHANNELS_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/channels"]'
NAVIGATION_DRAWER_DESCRIPTION = "Show navigation drawer"
PROFILE_SCROLL_VIEW_XPATH = '//*[@resource-id="com.twitter.android:id/compose_content"]/android.view.View[1]/android.view.View[1]/android.widget.ScrollView[1]/android.view.View[1]'
EDIT_PROFILE_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/button_edit_profile"]'

SIGNATURE_INPUT_FIELD_XPATH = '//*[@resource-id="com.twitter.android:id/edit_bio"]' # Specific for Bio/Signature
SAVE_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/save"]' 

DEFAULT_NEW_SIGNATURE = "This is a test bio!"

def click_element_center_mytapi_refactored(myt_rpc, u2_element, status_callback, device_info=""):
    try:
        bounds = u2_element.info['bounds']
        center_x = (bounds['left'] + bounds['right']) // 2
        center_y = (bounds['top'] + bounds['bottom']) // 2
        status_callback(f"{device_info}Clicking at element center ({center_x}, {center_y}) using MytRpc...")
        finger_id = 0
        myt_rpc.touchDown(finger_id, center_x, center_y)
        time.sleep(random.uniform(0.05, 0.15))
        myt_rpc.touchUp(finger_id, center_x, center_y)
        status_callback(f"{device_info}Clicked successfully with MytRpc.")
        return True
    except Exception as e:
        status_callback(f"{device_info}Error during MytRpc click: {e}")
        return False

def send_text_char_by_char(myt_rpc_device, text_to_send, status_callback, char_delay=0.1, device_info=""):
    status_callback(f"{device_info}Simulating typing: {text_to_send}")
    for char_index, char in enumerate(text_to_send):
        if not myt_rpc_device.sendText(char):
            status_callback(f"{device_info}MytRpc sendText failed for character: '{char}' at index {char_index}")
            return False
        time.sleep(char_delay)
    status_callback(f"{device_info}Simulated typing complete.")
    return True

def run_change_signature(status_callback, device_ip_address, u2_port, myt_rpc_port, new_signature):
    device_info = f"[{device_ip_address}:{u2_port}] "
    status_callback(f"{device_info}--- 修改简介开始 ---")
    mytapi = MytRpc()
    action_successful = True
    
    # 创建设备特定的回调函数，自动添加设备信息前缀
    def device_status_callback(message):
        status_callback(f"{device_info}{message}")
    
    device_status_callback(f"MytRpc SDK 版本: {mytapi.get_sdk_version()}")
    
    # 使用通用函数连接到UIAutomator2设备
    u2_d, connect_success = connect_to_device(device_ip_address, u2_port, status_callback)
    if not connect_success:
        device_status_callback("无法连接到uiautomator2设备，退出修改简介流程")
        return False
    
    if not mytapi.init(device_ip_address, myt_rpc_port, 10, max_retries=3):
        device_status_callback(f"MytRpc无法连接到设备 {device_ip_address} 端口 {myt_rpc_port}。退出。")
        return False
    
    if not mytapi.check_connect_state():
        device_status_callback("MytRpc连接已断开。退出。")
        return False
    device_status_callback("MytRpc已连接且连接状态正常。")
    
    # 检查Twitter应用是否运行并已登录
    if not ensure_twitter_app_running_and_logged_in(u2_d, mytapi, device_status_callback, device_info):
        device_status_callback("Twitter应用未运行或用户未登录，退出修改简介流程")
        return False
    
    # 检查并处理Twitter对话框
    handle_update_now_dialog(u2_d, mytapi, device_status_callback, device_info)
    handle_keep_less_relevant_ads(u2_d, mytapi, device_status_callback, device_info)

    # ---- Check for 'app is out of date' pop-up using u2_d ----
    if u2_d:
        device_status_callback("Checking for 'app is out of date' pop-up via uiautomator2...")
        try:
            primary_text_element = u2_d.xpath('//*[@resource-id="com.twitter.android:id/primary_text"]')
            if primary_text_element.wait(timeout=5.0):
                if primary_text_element.get_text() == 'This app is out of date.':
                    device_status_callback("'This app is out of date.' pop-up detected. Attempting to handle...")
                    navigate_up_btn = u2_d(description="Navigate up")
                    if navigate_up_btn.wait(timeout=3.0):
                        device_status_callback("Clicking 'Navigate up' button for pop-up.")
                        navigate_up_btn.click(); time.sleep(1)
                    primary_button_popup = u2_d.xpath('//*[@resource-id="com.twitter.android:id/primary_button"]')
                    if primary_button_popup.wait(timeout=3.0):
                        device_status_callback("Clicking 'primary_button' on pop-up.")
                        primary_button_popup.click()
                        device_status_callback("Waiting 10 seconds after clicking primary button..."); time.sleep(10)
                    final_navigate_up_btn = u2_d(descriptionContains="Navigate up")
                    if final_navigate_up_btn.wait(timeout=5.0):
                        device_status_callback("Clicking general 'Navigate up' button after pop-up handling.")
                        final_navigate_up_btn.click()
                    device_status_callback("Pop-up handling attempted.")
        except Exception as e_popup_check:
            device_status_callback(f"Error during 'app is out of date' pop-up check: {e_popup_check}")
    # ---- End of pop-up check ----

    # ---- Navigation to Edit Profile Screen ----
    device_status_callback(f"Attempting to find and click element with XPath: {CHANNELS_BUTTON_XPATH}")
    channels_element_xpath_obj = u2_d.xpath(CHANNELS_BUTTON_XPATH)
    if channels_element_xpath_obj.wait(timeout=5.0):
        if click_element_center_mytapi_refactored(mytapi, channels_element_xpath_obj, device_status_callback, device_info):
            device_status_callback("Successfully clicked channels element."); time.sleep(3.5)
        else: device_status_callback(f"Failed to click channels (XPath: {CHANNELS_BUTTON_XPATH})."); action_successful = False
    else: device_status_callback(f"Element (XPath: {CHANNELS_BUTTON_XPATH}) not found."); action_successful = False

    if action_successful:
        device_status_callback(f"Attempting to find and click element with content-desc: '{NAVIGATION_DRAWER_DESCRIPTION}'")
        nav_drawer_ui_obj = u2_d(description=NAVIGATION_DRAWER_DESCRIPTION)
        if nav_drawer_ui_obj.wait(timeout=5.0):
            if click_element_center_mytapi_refactored(mytapi, nav_drawer_ui_obj, device_status_callback, device_info):
                device_status_callback("Successfully clicked navigation drawer element."); time.sleep(3.5)
            else: device_status_callback(f"Failed to click navigation drawer ('{NAVIGATION_DRAWER_DESCRIPTION}')."); action_successful = False
        else: device_status_callback(f"Element ('{NAVIGATION_DRAWER_DESCRIPTION}') not found."); action_successful = False
    
    if action_successful:
        device_status_callback(f"Attempting to click profile scroll view area (XPath: {PROFILE_SCROLL_VIEW_XPATH})")
        profile_scroll_obj = u2_d.xpath(PROFILE_SCROLL_VIEW_XPATH)
        if profile_scroll_obj.wait(timeout=5.0):
            if click_element_center_mytapi_refactored(mytapi, profile_scroll_obj, device_status_callback, device_info):
                device_status_callback("Clicked profile scroll view area."); time.sleep(3.5)
            else: device_status_callback("Failed to click profile scroll view area."); action_successful = False
        else: device_status_callback("Profile scroll view area not found."); action_successful = False
    
    if action_successful:
        device_status_callback(f"Attempting to click edit profile button (XPath: {EDIT_PROFILE_BUTTON_XPATH})")
        edit_profile_obj = u2_d.xpath(EDIT_PROFILE_BUTTON_XPATH)
        if edit_profile_obj.wait(timeout=5.0):
            if click_element_center_mytapi_refactored(mytapi, edit_profile_obj, device_status_callback, device_info):
                device_status_callback("Clicked edit profile button."); time.sleep(3.5) # Wait for edit screen
            else: device_status_callback("Failed to click edit profile button."); action_successful = False
        else: device_status_callback("Edit profile button not found."); action_successful = False
    # ---- End Navigation to Edit Profile Screen ----

    # ---- Change Signature/Bio Logic ----
    if action_successful:
        device_status_callback("Locating signature/bio input field...")
        signature_field_xpath_obj = u2_d.xpath(SIGNATURE_INPUT_FIELD_XPATH)
        if signature_field_xpath_obj.wait(timeout=5.0):
            device_status_callback("Signature/bio field found.")
            if click_element_center_mytapi_refactored(mytapi, signature_field_xpath_obj, device_status_callback, device_info):
                time.sleep(1.0) 
                device_status_callback(f"Attempting to clear and set new signature to: {new_signature}")
                try:
                    device_status_callback("Performing long click on signature field for text selection...")
                    signature_field_xpath_obj.long_click()
                    time.sleep(1.0) 
                    select_all_button = u2_d(textContains="Select all")
                    if not select_all_button.wait(timeout=2.0):
                        device_status_callback("'Select all' not found, trying Chinese '全选'...")
                        select_all_button = u2_d(textContains="全选")
                    if select_all_button.wait(timeout=2.0):
                        device_status_callback("'Select all' (or equivalent) button found. Clicking it...")
                        select_all_button.click()
                        time.sleep(0.5)
                        device_status_callback("Pressing delete to clear selected text...")
                        u2_d.press("delete")
                        time.sleep(0.5)
                        device_status_callback("Text clearing attempt (select all + delete) finished.")
                    else:
                        device_status_callback("'Select all' (or equivalent) button not found after long click. Falling back to sending backspaces...")
                        current_text = signature_field_xpath_obj.get_text()
                        if current_text:
                            device_status_callback(f"Fallback: Current text is '{current_text}'. Sending backspaces...")
                            for _ in range(len(current_text) + 5):
                                u2_d.press("delete")
                                time.sleep(0.05)
                            device_status_callback("Fallback: Backspace sequence completed."); time.sleep(0.5)
                        else:
                            device_status_callback("Fallback: Signature field is already empty or get_text() returned empty.")
                    
                    device_status_callback(f"Typing new signature (via MytRpc): {new_signature}")
                    if send_text_char_by_char(mytapi, new_signature, device_status_callback, device_info=device_info):
                        device_status_callback(f"Successfully typed signature '{new_signature}' via MytRpc."); time.sleep(2)
                        device_status_callback(f"Locating and clicking Save button (XPath: {SAVE_BUTTON_XPATH})...")
                        save_button_obj = u2_d.xpath(SAVE_BUTTON_XPATH)
                        if save_button_obj.wait(timeout=5.0):
                            if click_element_center_mytapi_refactored(mytapi, save_button_obj, device_status_callback, device_info):
                                device_status_callback("Save button clicked."); time.sleep(2)
                                device_status_callback("Attempting to click 'Navigate up' button after save...")
                                navigate_up_after_save_obj = u2_d(descriptionContains="Navigate up")
                                if navigate_up_after_save_obj.wait(timeout=5.0):
                                    navigate_up_after_save_obj.click()
                                    device_status_callback("'Navigate up' button clicked after saving signature.")
                                else:
                                    device_status_callback("'Navigate up' button not found after saving signature.")
                            else: device_status_callback("Failed to click Save button."); action_successful = False
                        else: device_status_callback("Save button not found."); action_successful = False
                    else:
                        device_status_callback(f"Failed to type new signature '{new_signature}' via MytRpc."); action_successful = False
                except Exception as e_edit_signature:
                    device_status_callback(f"Error during signature editing: {e_edit_signature}"); action_successful = False
            else: device_status_callback("Failed to click signature input field."); action_successful = False
        else: device_status_callback(f"Signature input field (XPath: {SIGNATURE_INPUT_FIELD_XPATH}) not found."); action_successful = False
    # ---- End Change Signature/Bio Logic ----

    device_status_callback(f"--- Change Signature/Bio Script Finished ('{'SUCCESS' if action_successful else 'FAILURES ENCOUNTERED'}') ---")
    return action_successful

if __name__ == '__main__':
    def console_status_callback(message):
        print(message)

    console_status_callback("Running changeSignatureTest.py as a standalone script.")

    test_device_ip = "192.168.8.74"
    test_u2_port = 5006
    test_myt_rpc_port = 11060
    test_new_signature = DEFAULT_NEW_SIGNATURE

    if len(sys.argv) == 5:
        console_status_callback("Using command-line arguments for signature change.")
        test_device_ip = sys.argv[1]
        try:
            test_u2_port = int(sys.argv[2])
            test_myt_rpc_port = int(sys.argv[3])
        except ValueError:
            console_status_callback("Error: u2_port and myt_rpc_port must be integers. Exiting."); sys.exit(1)
        test_new_signature = sys.argv[4]
    elif len(sys.argv) > 1 and len(sys.argv) < 5:
        console_status_callback("Warning: Insufficient CLI args. Using defaults for signature change.")
    else:
        console_status_callback(f"No/wrong CLI args. Using defaults for signature change: IP={test_device_ip}, Signature='{test_new_signature}'")

    success = run_change_signature(console_status_callback, test_device_ip, test_u2_port, test_myt_rpc_port, test_new_signature)
    
    if success:
        console_status_callback("Standalone signature change script completed successfully.")
    else:
        console_status_callback("Standalone signature change script encountered issues or failed.")
    sys.exit(0 if success else 1) 