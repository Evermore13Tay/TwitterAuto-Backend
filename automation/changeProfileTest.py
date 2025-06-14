import time
import sys
import uiautomator2 as u2
from common.mytRpc import MytRpc
import random
import os
import traceback
import subprocess
from common.u2_connection import connect_to_device
from common.twitter_ui_handlers import handle_update_now_dialog, handle_keep_less_relevant_ads, ensure_twitter_app_running_and_logged_in

# Device IP - (Will be passed as a parameter)
# DEVICE_IP = "192.168.8.74"

# XPaths and Selectors (kept as module constants)
CHANNELS_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/channels"]'
NAVIGATION_DRAWER_DESCRIPTION = "Show navigation drawer"
PROFILE_SCROLL_VIEW_XPATH = '//*[@resource-id="com.twitter.android:id/compose_content"]/android.view.View[1]/android.view.View[1]/android.widget.ScrollView[1]/android.view.View[1]'
EDIT_PROFILE_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/button_edit_profile"]'
AVATAR_IMAGE_XPATH = '//*[@resource-id="com.twitter.android:id/avatar_image"]'
CHOOSE_PHOTO_TEXT_XPATH = '//*[@text="Choose existing photo"]'
PERMISSION_ALLOW_BUTTON_XPATH = '//*[@resource-id="com.android.permissioncontroller:id/permission_allow_button"]';
DONE_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/done"]' # Added from previous steps
SAVE_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/save"]' # Added
NOT_NOW_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/not_now"]' # Added
NAVIGATE_UP_BTN_DESC_FINAL = "Navigate up" # Added, specific for final step

# Device path for photo (can be kept constant or made a parameter if more flexibility is needed)
DEVICE_TARGET_PHOTO_DIR = "/storage/emulated/0/Pictures/" # Changed to target directory

def click_element_center_mytapi_refactored(myt_rpc, u2_element, status_callback): # Added status_callback
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

def run_change_profile_photo(status_callback, device_ip_address, u2_port, myt_rpc_port, local_photo_path_param):
    device_info = f"[{device_ip_address}:{u2_port}] "
    status_callback(f"{device_info}--- 修改头像开始 ---")
    mytapi = MytRpc()
    action_successful = True
    status_callback(f"{device_info}MytRpc SDK 版本: {mytapi.get_sdk_version()}")

    # 使用通用连接函数连接到UIAutomator2设备
    u2_d, connect_success = connect_to_device(device_ip_address, u2_port, status_callback)
    if not connect_success:
        status_callback(f"{device_info}无法连接到uiautomator2设备，退出修改头像流程")
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
        status_callback(f"{device_info}Twitter应用未运行或用户未登录，退出修改头像流程")
        return False

    # 检查并处理Twitter对话框 (Update Now 和 Less Relevant Ads)
    handle_update_now_dialog(u2_d, mytapi, status_callback, device_info)
    handle_keep_less_relevant_ads(u2_d, mytapi, status_callback, device_info)

    # ---- Check for 'app is out of date' pop-up using u2_d ----
    if u2_d: # Ensure u2_d is available
        status_callback(f"{device_info}通过uiautomator2检查'应用已过期'弹窗...")
        try:
            primary_text_element = u2_d.xpath('//*[@resource-id="com.twitter.android:id/primary_text"]')
            if primary_text_element.wait(timeout=5.0): # Wait up to 5 seconds for the element
                if primary_text_element.get_text() == 'This app is out of date.':
                    status_callback(f"{device_info}检测到'应用已过期'弹窗，尝试处理...")
                    
                    # Click sequence to handle the pop-up
                    navigate_up_btn = u2_d(description="Navigate up") # Or descriptionContains if more flexible
                    if navigate_up_btn.wait(timeout=3.0):
                        status_callback(f"{device_info}点击'导航返回'按钮（通常是弹窗上的X或返回箭头）。")
                        navigate_up_btn.click()
                        time.sleep(1) # Short pause after click
                    else:
                        status_callback(f"{device_info}未快速找到弹窗的'导航返回'按钮。")

                    primary_button_popup = u2_d.xpath('//*[@resource-id="com.twitter.android:id/primary_button"]')
                    if primary_button_popup.wait(timeout=3.0):
                        status_callback(f"{device_info}点击弹窗上的'主要按钮'。")
                        primary_button_popup.click()
                        status_callback(f"{device_info}点击主要按钮后等待10秒...")
                        time.sleep(10)
                    else:
                        status_callback(f"{device_info}未找到弹窗上的'主要按钮'。")

                    # This final navigate up might be for a screen after the pop-up handling
                    final_navigate_up_btn = u2_d(descriptionContains="Navigate up") # Using descriptionContains
                    if final_navigate_up_btn.wait(timeout=5.0):
                        status_callback(f"{device_info}处理弹窗后点击通用'导航返回'按钮。")
                        final_navigate_up_btn.click()
                    else:
                        status_callback(f"{device_info}弹窗处理后未找到通用'导航返回'按钮。")
                    status_callback(f"{device_info}已尝试处理弹窗。")
                else:
                    status_callback(f"{device_info}找到弹窗主文本，但内容为：'{primary_text_element.get_text()}'（与预期不符）。跳过弹窗处理。")
            else:
                status_callback(f"{device_info}未找到'应用已过期'弹窗（primary_text）。假定无弹窗。")
        except Exception as e_popup_check:
            status_callback(f"{device_info}检查'应用已过期'弹窗时出错: {e_popup_check}")
    else:
        status_callback(f"{device_info}u2_d（uiautomator2设备）不可用，跳过'应用已过期'弹窗检查。")
    # ---- End of pop-up check ----

    # ---- Upload Photo ----
    if not local_photo_path_param or not os.path.exists(local_photo_path_param):
        status_callback(f"{device_info}错误：本地照片路径无效或文件不存在: {local_photo_path_param}")
        return False

    local_photo_filename = os.path.basename(local_photo_path_param)
    device_photo_full_path = os.path.join(DEVICE_TARGET_PHOTO_DIR, local_photo_filename).replace("\\\\", "/")
    status_callback(f"{device_info}目标设备路径: {device_photo_full_path}")

    adb_serial = None
    if u2_d and hasattr(u2_d, 'serial') and u2_d.serial:
        adb_serial = u2_d.serial
        status_callback(f"{device_info}子进程命令使用ADB序列号: {adb_serial}")
    else:
        status_callback(f"{device_info}ADB序列号不可用。子进程使用通用'adb'命令。如果连接了多个设备，这可能会失败。")

    # Ensure target directory exists using subprocess adb shell mkdir
    device_target_dir = os.path.dirname(device_photo_full_path)
    if device_target_dir and device_target_dir != '/':
        mkdir_base_command = ["adb"]
        if adb_serial: mkdir_base_command.extend(["-s", adb_serial])
        mkdir_base_command.extend(["shell", "mkdir", "-p", device_target_dir])
        
        status_callback(f"{device_info}确保设备上目录存在: {' '.join(mkdir_base_command)} (通过子进程)")
        try:
            process_mkdir = subprocess.run(mkdir_base_command, capture_output=True, text=True, check=False, timeout=10, encoding='utf-8', errors='replace')
            status_callback(f"{device_info}  mkdir返回码: {process_mkdir.returncode}")
            status_callback(f"{device_info}  mkdir标准输出: {process_mkdir.stdout.strip() if process_mkdir.stdout else '(空)'}")
            status_callback(f"{device_info}  mkdir标准错误: {process_mkdir.stderr.strip() if process_mkdir.stderr else '(空)'}")
            if process_mkdir.returncode != 0 and process_mkdir.stderr: # Check stderr on non-zero exit
                status_callback(f"{device_info}警告：子进程mkdir可能失败。标准错误: {process_mkdir.stderr.strip()}")
                # Not returning False, as adb push might still succeed if dir exists or it creates it.
        except Exception as e_mkdir_sub:
            status_callback(f"{device_info}子进程mkdir出错: {e_mkdir_sub}。仍会尝试上传。")

    # Attempt upload using subprocess to call adb directly
    status_callback(f"{device_info}尝试使用subprocess.run('adb push ...')将'{local_photo_path_param}'上传到'{device_photo_full_path}'...")
    upload_successful_subprocess = False
    try:
        adb_push_command = ["adb"]
        if adb_serial: adb_push_command.extend(["-s", adb_serial])
        adb_push_command.extend(["push", local_photo_path_param, device_photo_full_path])
        
        status_callback(f"{device_info}执行子进程命令: {' '.join(adb_push_command)}")
        process_push = subprocess.run(adb_push_command, capture_output=True, text=True, check=False, timeout=60, encoding='utf-8', errors='replace')
        
        status_callback(f"{device_info}子进程adb push完成。")
        status_callback(f"{device_info}  返回码: {process_push.returncode}")
        status_callback(f"{device_info}  标准输出:\n{process_push.stdout.strip() if process_push.stdout else '(空)'}")
        status_callback(f"{device_info}  标准错误:\n{process_push.stderr.strip() if process_push.stderr else '(空)'}")

        if process_push.returncode == 0:
            upload_successful_subprocess = True
            status_callback(f"{device_info}子进程adb push报告成功(返回码0)。")
        else:
            status_callback(f"{device_info}子进程adb push失败(返回码{process_push.returncode})。")
            if process_push.stderr:
                 status_callback(f"{device_info}来自adb的错误详情: {process_push.stderr.strip()}")

    except FileNotFoundError:
        status_callback(f"{device_info}错误：未找到'adb'命令。确保已安装ADB并在系统PATH中。")
        return False # Critical error
    except subprocess.TimeoutExpired:
        status_callback(f"{device_info}错误：'adb push'命令在60秒后超时。")
        return False # Critical error
    except Exception as e_subprocess_push:
        status_callback(f"{device_info}子进程adb push出错: {e_subprocess_push}")
        status_callback(f"{device_info}{traceback.format_exc()}")
        return False # Critical error
    
    if not upload_successful_subprocess:
        status_callback(f"{device_info}通过子进程adb push上传文件失败。")
        return False

    status_callback(f"{device_info}通过子进程adb push上传文件报告成功。使用子进程adb shell stat验证...")

    # ---- Verify with subprocess adb shell stat ----
    action_successful = False # Reset for this new verification logic
    try:
        adb_stat_command = ["adb"]
        if adb_serial: adb_stat_command.extend(["-s", adb_serial])
        adb_stat_command.extend(["shell", "stat", device_photo_full_path])

        status_callback(f"{device_info}执行验证命令: {' '.join(adb_stat_command)} (通过子进程)")
        process_stat = subprocess.run(adb_stat_command, capture_output=True, text=True, check=False, timeout=10, encoding='utf-8', errors='replace')
        
        status_callback(f"{device_info}子进程adb stat完成。")
        status_callback(f"{device_info}  返回码: {process_stat.returncode}")
        status_callback(f"{device_info}  标准输出:\n{process_stat.stdout.strip() if process_stat.stdout else '(空)'}")
        status_callback(f"{device_info}  标准错误:\n{process_stat.stderr.strip() if process_stat.stderr else '(空)'}")

        if process_stat.returncode == 0 and process_stat.stdout: # Success and got some output (check stdout not None)
            status_callback(f"{device_info}验证成功(子进程): 文件已确认在'{device_photo_full_path}'。")
            action_successful = True
            # ---- Trigger Media Scan via subprocess ----
            media_scan_uri = f"file://{device_photo_full_path}"
            adb_scan_command = ["adb"]
            if adb_serial: adb_scan_command.extend(["-s", adb_serial])
            adb_scan_command.extend(["shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", media_scan_uri])
            
            status_callback(f"{device_info}触发媒体扫描: {' '.join(adb_scan_command)} (通过子进程)")
            process_scan = subprocess.run(adb_scan_command, capture_output=True, text=True, check=False, timeout=10, encoding='utf-8', errors='replace')
            status_callback(f"{device_info}  扫描返回码: {process_scan.returncode}")
            status_callback(f"{device_info}  扫描标准输出: {process_scan.stdout.strip() if process_scan.stdout else '(空)'}")
            status_callback(f"{device_info}  扫描标准错误: {process_scan.stderr.strip() if process_scan.stderr else '(空)'}")
            if process_scan.returncode == 0:
                 status_callback(f"{device_info}通过子进程成功发送媒体扫描广播。")
            else:
                 status_callback(f"{device_info}通过子进程发送媒体扫描广播可能失败。标准错误: {process_scan.stderr.strip() if process_scan.stderr else '(无标准错误)'}")
            time.sleep(3) # Give media scanner a moment
            # ---- End Media Scan ----
        elif process_stat.returncode != 0 and process_stat.stderr and "No such file or directory" in process_stat.stderr.strip():
             status_callback(f"{device_info}验证失败(子进程): 在'{device_photo_full_path}'未找到文件。错误: {process_stat.stderr.strip()}")
        else: # Other errors or unexpected output from stat
            status_callback(f"{device_info}验证不明确(子进程): 'stat'命令已执行。RC={process_stat.returncode}。检查标准错误/标准输出获取详情。")

    except FileNotFoundError:
        status_callback(f"{device_info}错误：stat/scan未找到'adb'命令。确保ADB在PATH中。")
    except subprocess.TimeoutExpired:
        status_callback(f"{device_info}错误：'adb shell stat/scan'命令超时。")
    except Exception as e_subprocess_stat:
        status_callback(f"{device_info}子进程adb shell stat/scan出错: {e_subprocess_stat}")
        status_callback(f"{device_info}{traceback.format_exc()}")
    # ---- End Verification ----

    if not action_successful:
        status_callback(f"{device_info}上传或验证过程失败。跳过后续UI操作。")
        return False

    status_callback(f"{device_info}开始修改头像操作...")

    action_successful = True # This flag will track if steps fail

    # Click 'channels' button
    status_callback(f"{device_info}尝试查找并点击元素XPath: {CHANNELS_BUTTON_XPATH}")
    channels_element_xpath_obj = u2_d.xpath(CHANNELS_BUTTON_XPATH)
    if channels_element_xpath_obj.exists:
        if click_element_center_mytapi_refactored(mytapi, channels_element_xpath_obj, status_callback):
            status_callback("Successfully clicked channels element."); time.sleep(3.5)
        else: status_callback(f"{device_info}无法点击channels (XPath: {CHANNELS_BUTTON_XPATH})."); action_successful = False
    else: status_callback(f"{device_info}元素 (XPath: {CHANNELS_BUTTON_XPATH}) 未找到。"); action_successful = False

    # Click 'Show navigation drawer'
    if action_successful:
        status_callback(f"{device_info}尝试查找并点击元素content-desc: '{NAVIGATION_DRAWER_DESCRIPTION}'")
        nav_drawer_ui_obj = u2_d(description=NAVIGATION_DRAWER_DESCRIPTION)
        if nav_drawer_ui_obj.exists:
            if click_element_center_mytapi_refactored(mytapi, nav_drawer_ui_obj, status_callback):
                status_callback("Successfully clicked navigation drawer element."); time.sleep(3.5)
            else: status_callback(f"{device_info}无法点击导航抽屉 ({NAVIGATION_DRAWER_DESCRIPTION})."); action_successful = False
        else: status_callback(f"{device_info}元素 ({NAVIGATION_DRAWER_DESCRIPTION}) 未找到。"); action_successful = False
    
    # Profile Edit Flow
    if action_successful:
        status_callback(f"{device_info}尝试点击个人资料滚动视图区域 (XPath: {PROFILE_SCROLL_VIEW_XPATH})")
        profile_scroll_obj = u2_d.xpath(PROFILE_SCROLL_VIEW_XPATH)
        if profile_scroll_obj.exists:
            if click_element_center_mytapi_refactored(mytapi, profile_scroll_obj, status_callback):
                status_callback("Clicked profile scroll view area."); time.sleep(3.5)
            else: status_callback("Failed to click profile scroll view area."); action_successful = False
        else: status_callback("Profile scroll view area not found."); action_successful = False
    
    if action_successful:
        status_callback(f"{device_info}尝试点击编辑个人资料按钮 (XPath: {EDIT_PROFILE_BUTTON_XPATH})")
        edit_profile_obj = u2_d.xpath(EDIT_PROFILE_BUTTON_XPATH)
        if edit_profile_obj.exists:
            if click_element_center_mytapi_refactored(mytapi, edit_profile_obj, status_callback):
                status_callback("Clicked edit profile button."); time.sleep(3.5)
            else: status_callback("Failed to click edit profile button."); action_successful = False
        else: status_callback("Edit profile button not found."); action_successful = False

    if action_successful:
        status_callback(f"{device_info}尝试点击头像图像 (XPath: {AVATAR_IMAGE_XPATH})")
        avatar_obj = u2_d.xpath(AVATAR_IMAGE_XPATH)
        if avatar_obj.exists:
            if click_element_center_mytapi_refactored(mytapi, avatar_obj, status_callback):
                status_callback("Clicked avatar image."); time.sleep(3.5)
            else: status_callback("Failed to click avatar image."); action_successful = False
        else: status_callback("Avatar image not found."); action_successful = False

    if action_successful:
        status_callback(f"{device_info}尝试点击'Choose existing photo' (XPath: {CHOOSE_PHOTO_TEXT_XPATH})")
        choose_photo_obj = u2_d.xpath(CHOOSE_PHOTO_TEXT_XPATH)
        if choose_photo_obj.exists:
            if click_element_center_mytapi_refactored(mytapi, choose_photo_obj, status_callback):
                status_callback("Clicked 'Choose existing photo'."); time.sleep(3.5)
            else: status_callback("Failed to click 'Choose existing photo'."); action_successful = False
        else: status_callback("'Choose existing photo' not found."); action_successful = False

    if action_successful:
        status_callback(f"{device_info}尝试点击权限允许按钮 (XPath: {PERMISSION_ALLOW_BUTTON_XPATH}) 使用 u2_d.click_exists()")
        permission_button = u2_d.xpath(PERMISSION_ALLOW_BUTTON_XPATH)
        if permission_button.click_exists(timeout=5.0):
            status_callback("Permission allow button clicked.")
        else:
            status_callback("Permission allow button not found or click failed.") # Not setting action_successful to False, as it might not always appear

    if action_successful:
        # Using UPLOADED_PHOTO_CONTENT_DESC_STARTS_WITH which should match the filename part of the content-desc
        # Assuming the filename part is consistent with local_photo_path_param filename
        # This might need adjustment if the content-desc is more complex or localized.
        
        # Construct XPath dynamically based on the uploaded photo's filename
        # Assuming content-desc starts with the filename (without extension for some gallery apps)
        # For robustness, one might need to check content-desc with and without extension or other variations
        uploaded_photo_filename_for_search = os.path.splitext(local_photo_filename)[0] # Try filename without extension first
        
        # Try finding with filename (often content-desc is just the filename)
        # Or, if the content description includes the extension, use: local_photo_filename
        uploaded_photo_xpath = f'//*[starts-with(@content-desc, "{local_photo_filename}")]/android.widget.RelativeLayout[1]'
        status_callback(f"{device_info}尝试点击上传的照片 (XPath: {uploaded_photo_xpath})")
        uploaded_photo_obj = u2_d.xpath(uploaded_photo_xpath)
        
        if not uploaded_photo_obj.exists:
            # Fallback: try with filename without extension if the above failed
            status_callback(f"{device_info}Photo not found with full filename in content-desc. Trying with filename without extension: '{uploaded_photo_filename_for_search}'")
            uploaded_photo_xpath = f'//*[starts-with(@content-desc, "{uploaded_photo_filename_for_search}")]/android.widget.RelativeLayout[1]'
            status_callback(f"{device_info}尝试点击上传的照片 (Fallback XPath: {uploaded_photo_xpath})")
            uploaded_photo_obj = u2_d.xpath(uploaded_photo_xpath)

        if uploaded_photo_obj.exists:
            if click_element_center_mytapi_refactored(mytapi, uploaded_photo_obj, status_callback):
                status_callback("Clicked uploaded photo.")
            else: status_callback("Failed to click uploaded photo."); action_successful = False
        else: status_callback(f"{device_info}Uploaded photo not found using filename '{local_photo_filename}' or '{uploaded_photo_filename_for_search}' in content-desc start."); action_successful = False

    if action_successful:
        status_callback("Waiting for 3.5 seconds before clicking 'Done' button..."); time.sleep(3.5)
        done_button_obj = u2_d.xpath(DONE_BUTTON_XPATH)
        if done_button_obj.exists:
            if click_element_center_mytapi_refactored(mytapi, done_button_obj, status_callback):
                status_callback("Successfully clicked 'Done' button.")
            else: status_callback(f"{device_info}无法点击'Done'按钮 (XPath: {DONE_BUTTON_XPATH})."); action_successful = False
        else: status_callback(f"{device_info}'Done' button (XPath: {DONE_BUTTON_XPATH}) not found."); action_successful = False

    if action_successful:
        status_callback("Waiting for 3.5 seconds before clicking 'Save' button..."); time.sleep(3.5)
        save_button_obj = u2_d.xpath(SAVE_BUTTON_XPATH)
        if save_button_obj.exists:
            if click_element_center_mytapi_refactored(mytapi, save_button_obj, status_callback):
                status_callback("Successfully clicked 'Save' button.")
            else: status_callback(f"{device_info}无法点击'Save'按钮 (XPath: {SAVE_BUTTON_XPATH})."); action_successful = False
        else: status_callback(f"{device_info}'Save' button (XPath: {SAVE_BUTTON_XPATH}) not found."); action_successful = False

    if action_successful:
        status_callback("Waiting for 3.5 seconds before clicking 'Not now' button..."); time.sleep(3.5)
        not_now_button_obj = u2_d.xpath(NOT_NOW_BUTTON_XPATH)
        if not_now_button_obj.click_exists(timeout=5.0):
            status_callback("Successfully clicked 'Not now' button or it was not present within timeout.")
        else:
            status_callback(f"{device_info}'Not now' button (XPath: {NOT_NOW_BUTTON_XPATH}) not found or failed to click within timeout.") # Not critical, don't set action_successful = False

    if action_successful: 
        status_callback("Waiting for 3.5 seconds before clicking 'Navigate up' button..."); time.sleep(3.5)
        navigate_up_button_obj = u2_d(description=NAVIGATE_UP_BTN_DESC_FINAL)
        if navigate_up_button_obj.click_exists(timeout=5.0):
            status_callback("Successfully clicked 'Navigate up' button.")
        else:
            status_callback(f"{device_info}'Navigate up' button (description: '{NAVIGATE_UP_BTN_DESC_FINAL}') not found or failed to click within timeout.")

    status_callback(f"{device_info}--- Change Profile Photo Script Finished ({'SUCCESS' if action_successful else 'FAILURES ENCOUNTERED'}) ---")
    return action_successful

if __name__ == '__main__':
    def console_status_callback(message):
        __builtins__.print(message)

    console_status_callback("Running changeProfileTest.py as a standalone script.")

    if len(sys.argv) < 5: # ip, u2_port, myt_port, photo_path
        console_status_callback("Usage: python changeProfileTest.py <device_ip> <u2_port> <myt_rpc_port> <local_photo_path>")
        sys.exit(1)
   

        
    test_device_ip = sys.argv[1]
    try:
        test_u2_port = int(sys.argv[2])
        test_myt_rpc_port = int(sys.argv[3])
    except ValueError:
        console_status_callback("Error: u2_port and myt_rpc_port must be integers.")
        sys.exit(1)
    test_local_photo_path = sys.argv[4]

    if not test_local_photo_path or test_local_photo_path == "/path/to/your/local/profile_photo.jpg":
        console_status_callback("Error: Please provide a valid local_photo_path argument.")
        # Try to find a default photo for testing if not provided or placeholder
        script_dir = os.path.dirname(os.path.abspath(__file__))
        potential_photo = os.path.join(script_dir, "profile_photo.jpg") # Assuming it might be in the same dir
        if os.path.exists(potential_photo):
            console_status_callback(f"Using default test photo: {potential_photo}")
            test_local_photo_path = potential_photo
        else:
            console_status_callback(f"Default photo 'profile_photo.jpg' not found in script directory: {script_dir}. Exiting.")
            sys.exit(1)
            
    console_status_callback(f"Attempting to change profile photo on {test_device_ip} with {test_local_photo_path}")
    success = run_change_profile_photo(console_status_callback, test_device_ip, test_u2_port, test_myt_rpc_port, test_local_photo_path)
    
    if success:
        console_status_callback("Standalone profile change script completed successfully.")
    else:
        console_status_callback("Standalone profile change script encountered issues or failed.")
    sys.exit(0 if success else 1) 