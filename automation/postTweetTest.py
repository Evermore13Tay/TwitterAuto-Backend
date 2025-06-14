import time
import sys
import os
import traceback
import subprocess
import uiautomator2 as u2
from common.mytRpc import MytRpc # 假设 common.mytRpc 存在且 MytRpc 可导入
import random
from common.u2_connection import connect_to_device # 假设 common.u2_connection 存在
from common.twitter_ui_handlers import handle_update_now_dialog, handle_keep_less_relevant_ads, ensure_twitter_app_running_and_logged_in # 假设 common.twitter_ui_handlers 存在

# --- Constants for Selectors ---
COMPOSER_WRITE_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/composer_write"]'
GALLERY_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/gallery"]'
GALLERY_TOOLBAR_SPINNER_XPATH = '//*[@resource-id="com.twitter.android:id/gallery_toolbar_spinner"]'
MORE_BUTTON_TEXT_XPATH = '//*[@text="More..."]'
TWEET_TEXT_INPUT_XPATH = '//*[@resource-id="com.twitter.android:id/tweet_text"]'
POST_TWEET_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/composer_toolbar"]/android.widget.LinearLayout[1]'
DEVICE_TARGET_PHOTO_DIR = "/storage/emulated/0/Pictures/" # Standard directory for pictures
CHANNELS_BUTTON_XPATH = '//*[@resource-id="com.twitter.android:id/channels"]' # 添加channels按钮常量
PERMISSION_ALLOW_BUTTON_XPATH = '//*[@resource-id="com.android.permissioncontroller:id/permission_allow_button"]' # 添加权限允许按钮常量

MAX_IMAGES_ALLOWED = 4 # Twitter typically allows up to 4 images

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

def run_post_tweet(status_callback, device_ip_address, u2_port, myt_rpc_port, tweet_text, attach_image=False, image_paths=None):
    device_info = f"[{device_ip_address}:{u2_port}] "
    status_callback(f"{device_info}--- 发送推文开始 ---")
    mytapi = MytRpc()
    status_callback(f"{device_info}MytRpc SDK 版本: {mytapi.get_sdk_version()}")

    u2_d = None
    mytapi_initialized = False
    action_successful = False  # Default to False, set to True only on full success

    try:
        # 使用通用连接函数连接uiautomator2设备
        u2_d, connect_success = connect_to_device(device_ip_address, u2_port, status_callback)
        if not connect_success:
            status_callback(f"{device_info}无法连接到uiautomator2设备，退出发送推文流程")
            return False # Early exit, finally will handle u2_d if it was partially set

        if not mytapi.init(device_ip_address, myt_rpc_port, 10, max_retries=3):
            status_callback(f"MytRpc failed to connect to device {device_ip_address} on port {myt_rpc_port}. Exiting.")
            return False # Early exit, finally will handle mytapi (though init failed)
        mytapi_initialized = True
        
        if not mytapi.check_connect_state():
            status_callback("MytRpc connection is disconnected. Exiting.")
            return False # Early exit
        status_callback("MytRpc connected and connection state is normal.")

        # 检查Twitter应用是否运行并已登录
        if not ensure_twitter_app_running_and_logged_in(u2_d, mytapi, status_callback, device_info):
            status_callback(f"{device_info}Twitter应用未运行或用户未登录，退出发送推文流程")
            return False # Early exit

        # 检查是否存在升级APP对话框
        handle_update_now_dialog(u2_d, mytapi, status_callback, device_info)
        handle_keep_less_relevant_ads(u2_d, mytapi, status_callback, device_info)

        post_image_choice_bool = attach_image 
        current_step_successful = True # Tracks success of individual steps within the try block
        
        # Ensure image_paths_param is a list if images are to be attached
        if post_image_choice_bool and not isinstance(image_paths, list):
            status_callback(f"Warning: image_paths_param was not a list, but attach_image is true. Treating as no images. Type: {type(image_paths)}")
            image_paths_to_process = []
        elif post_image_choice_bool:
            image_paths_to_process = image_paths[:MAX_IMAGES_ALLOWED]
            if len(image_paths) > MAX_IMAGES_ALLOWED:
                status_callback(f"Warning: More than {MAX_IMAGES_ALLOWED} images provided. Only the first {MAX_IMAGES_ALLOWED} will be processed.")
        else:
            image_paths_to_process = []

        # Step 0: 首先点击 channels 按钮
        if current_step_successful:
            status_callback(f"点击 channels 按钮: {CHANNELS_BUTTON_XPATH}")
            time.sleep(1.0)
            channels_button_obj = u2_d.xpath(CHANNELS_BUTTON_XPATH)
            if channels_button_obj.wait(timeout=5.0):
                if click_element_center_mytapi_refactored(mytapi, channels_button_obj, status_callback):
                    status_callback("成功点击 channels 按钮"); time.sleep(2.5)
                else:
                    status_callback(f"点击 channels 按钮失败，但继续执行...")
            else:
                status_callback(f"channels 按钮未找到，但继续执行...")
            time.sleep(1.5)

        # Step 1: 第一次点击 - 打开推文编辑器
        if current_step_successful:
            status_callback(f"第一次点击: 尝试打开推文编辑器: {COMPOSER_WRITE_BUTTON_XPATH}")
            time.sleep(1.0)
            composer_button_obj = u2_d.xpath(COMPOSER_WRITE_BUTTON_XPATH)
            if composer_button_obj.wait(timeout=10.0):
                if click_element_center_mytapi_refactored(mytapi, composer_button_obj, status_callback):
                    status_callback("成功第一次点击推文编辑器按钮"); time.sleep(3.0)
                else:
                    status_callback(f"第一次点击推文编辑器按钮失败 (XPath: {COMPOSER_WRITE_BUTTON_XPATH})"); current_step_successful = False
            else:
                status_callback(f"推文编辑器按钮未找到 (XPath: {COMPOSER_WRITE_BUTTON_XPATH})"); current_step_successful = False
            time.sleep(1.5)

        # Step 2: 第二次点击 - 确认推文编辑器
        if current_step_successful:
            status_callback(f"第二次点击: 再次点击推文编辑器按钮")
            time.sleep(1.0)
            composer_button_obj = u2_d.xpath(COMPOSER_WRITE_BUTTON_XPATH)
            if composer_button_obj.wait(timeout=5.0):
                if click_element_center_mytapi_refactored(mytapi, composer_button_obj, status_callback):
                    status_callback("成功第二次点击推文编辑器按钮"); time.sleep(2.5)
                else:
                    status_callback("第二次点击推文编辑器按钮失败"); current_step_successful = False
            else:
                status_callback("第二次点击推文编辑器按钮未找到"); current_step_successful = False
            time.sleep(1.5)
        
        # Step 3: 检查并点击 "Got it" 按钮
        if current_step_successful:
            status_callback(f"检查是否存在 'Got it' 按钮")
            time.sleep(1.5)
            got_it_button_xpath = '//*[@text="Got it"]'
            status_callback(f"检查是否存在 'Got it' 按钮: {got_it_button_xpath}")
            got_it_button_obj = u2_d.xpath(got_it_button_xpath)
            if got_it_button_obj.exists:
                status_callback("找到 'Got it' 按钮，尝试点击...")
                time.sleep(0.5)
                if click_element_center_mytapi_refactored(mytapi, got_it_button_obj, status_callback):
                    status_callback("成功点击 'Got it' 按钮"); time.sleep(2.0)
                else:
                    status_callback("点击 'Got it' 按钮失败，但继续执行...")
            else:
                status_callback("未找到 'Got it' 按钮 (如果之前已关闭提示，这是正常的)")
            time.sleep(1.0)

        # Step 4: 根据是否有图片选择不同的处理路径
        if current_step_successful and post_image_choice_bool and image_paths_to_process:
            status_callback(f"选择发送图片，共 {len(image_paths_to_process)} 张")
            time.sleep(1.0)
            for idx, current_image_path in enumerate(image_paths_to_process):
                if not current_step_successful: break
                status_callback(f"处理第 {idx + 1}/{len(image_paths_to_process)} 张图片: {current_image_path}")
                time.sleep(1.5)
                if not current_image_path or not os.path.exists(current_image_path):
                    status_callback(f"错误: 图片路径无效或文件不存在: '{current_image_path}'。跳过此图片。")
                    continue
                local_photo_filename = os.path.basename(current_image_path)
                device_photo_full_path = os.path.join(DEVICE_TARGET_PHOTO_DIR, local_photo_filename).replace("\\", "/")
                status_callback(f"      设备上的目标路径: {device_photo_full_path}")
                adb_serial = u2_d.serial if u2_d and hasattr(u2_d, 'serial') and u2_d.serial else None
                upload_current_image_successful = True
                device_target_dir_for_image = os.path.dirname(device_photo_full_path)
                if device_target_dir_for_image and device_target_dir_for_image != '/':
                    mkdir_cmd = ["adb"] + (["-s", adb_serial] if adb_serial else []) + ["shell", "mkdir", "-p", device_target_dir_for_image]
                    try:
                        proc_mkdir = subprocess.run(mkdir_cmd, capture_output=True, text=True, check=False, timeout=10, encoding='utf-8', errors='replace')
                        if proc_mkdir.returncode != 0 and proc_mkdir.stderr: status_callback(f"      警告: 创建目录过程出错: {proc_mkdir.stderr.strip()}")
                    except Exception as e_mkdir: status_callback(f"      创建目录过程异常: {e_mkdir}")
                adb_push_cmd = ["adb"] + (["-s", adb_serial] if adb_serial else []) + ["push", current_image_path, device_photo_full_path]
                try:
                    proc_push = subprocess.run(adb_push_cmd, capture_output=True, text=True, check=False, timeout=60, encoding='utf-8', errors='replace')
                    if proc_push.returncode == 0: status_callback(f"      文件 {local_photo_filename} 上传成功。")
                    else: 
                        status_callback(f"      文件 {local_photo_filename} 上传失败。返回码: {proc_push.returncode}. 错误: {proc_push.stderr.strip() if proc_push.stderr else '(无错误信息)'}"); upload_current_image_successful = False
                except Exception as e_push: status_callback(f"      上传 {local_photo_filename} 过程异常: {e_push}"); upload_current_image_successful = False
                if upload_current_image_successful:
                    adb_stat_cmd = ["adb"] + (["-s", adb_serial] if adb_serial else []) + ["shell", "stat", device_photo_full_path]
                    try:
                        proc_stat = subprocess.run(adb_stat_cmd, capture_output=True, text=True, check=False, timeout=10, encoding='utf-8', errors='replace')
                        if proc_stat.returncode == 0 and proc_stat.stdout:
                            status_callback(f"      验证成功: {local_photo_filename} 已确认。")
                            media_scan_uri = f"file://{device_photo_full_path}"
                            adb_scan_cmd = ["adb"] + (["-s", adb_serial] if adb_serial else []) + ["shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", media_scan_uri]
                            proc_scan = subprocess.run(adb_scan_cmd, capture_output=True, text=True, check=False, timeout=10, encoding='utf-8', errors='replace')
                            if proc_scan.returncode == 0: status_callback(f"      文件 {local_photo_filename} 的媒体扫描已发送。")
                            else: status_callback(f"      文件 {local_photo_filename} 的媒体扫描可能失败。错误: {proc_scan.stderr.strip() if proc_scan.stderr else '(无错误信息)'}")
                            time.sleep(2)
                        else: status_callback(f"      验证 {local_photo_filename} 失败。" ); upload_current_image_successful = False
                    except Exception as e_stat: status_callback(f"      验证/扫描 {local_photo_filename} 过程异常: {e_stat}"); upload_current_image_successful = False
                else:
                    current_step_successful = False; break
                if not upload_current_image_successful:
                    current_step_successful = False; break
                status_callback(f"为图片 {idx + 1}/{len(image_paths_to_process)} 点击相册按钮...")
                time.sleep(1.5)
                gallery_button_obj = u2_d.xpath(GALLERY_BUTTON_XPATH)
                if gallery_button_obj.wait(timeout=8.0):
                    if click_element_center_mytapi_refactored(mytapi, gallery_button_obj, status_callback):
                        status_callback(f"成功点击相册按钮（第 {idx + 1} 张图片）"); time.sleep(3.0)
                    else:
                        status_callback(f"点击相册按钮失败（第 {idx + 1} 张图片）"); current_step_successful = False; break
                else:
                    status_callback(f"相册按钮未找到（第 {idx + 1} 张图片）"); current_step_successful = False; break
                if idx == 0:
                    status_callback(f"检查是否需要授予媒体访问权限: {PERMISSION_ALLOW_BUTTON_XPATH}")
                    time.sleep(2.0)
                    permission_allow_button_obj = u2_d.xpath(PERMISSION_ALLOW_BUTTON_XPATH)
                    if permission_allow_button_obj.exists:
                        status_callback("找到权限允许按钮，尝试点击...")
                        if click_element_center_mytapi_refactored(mytapi, permission_allow_button_obj, status_callback):
                            status_callback("成功点击权限允许按钮"); time.sleep(3.0)
                        else:
                            status_callback("点击权限允许按钮失败，但继续执行...")
                    else:
                        status_callback("未找到权限允许按钮 (如果已授权，这是正常的)")
                    time.sleep(1.5)
                status_callback(f"尝试点击相册文件夹 'Pictures' (第 {idx + 1} 张图片)")
                time.sleep(2.0)
                pictures_folder_obj = u2_d.xpath('//*[@resource-id="com.twitter.android:id/text_view" and @text="Pictures"]')
                if pictures_folder_obj.wait(timeout=8.0):
                    if click_element_center_mytapi_refactored(mytapi, pictures_folder_obj, status_callback):
                        status_callback(f"成功点击 'Pictures' 文件夹（第 {idx + 1} 张图片）"); time.sleep(2.5)
                    else:
                        status_callback(f"点击 'Pictures' 文件夹失败（第 {idx + 1} 张图片）"); current_step_successful = False; break
                else:
                    status_callback(f"未找到 'Pictures' 文件夹（第 {idx + 1} 张图片）"); current_step_successful = False; break
                status_callback(f"尝试选择图片: {local_photo_filename} (第 {idx + 1} 张图片)")
                time.sleep(2.0)
                image_selector_xpath = f'//*[@resource-id="com.twitter.android:id/image" and contains(@content-desc, "{os.path.splitext(local_photo_filename)[0]}")]'
                status_callback(f"      图片选择器XPath: {image_selector_xpath}")
                image_obj = u2_d.xpath(image_selector_xpath)

                # 如果通过完整文件名未找到，尝试不带扩展名查找
                if not image_obj.wait(timeout=10.0): # 增加超时时间
                    status_callback(f"      通过完整文件名在content-desc中未找到图片。尝试不带扩展名: '{os.path.splitext(local_photo_filename)[0]}'.")
                    image_selector_xpath = f'//*[@resource-id="com.twitter.android:id/image" and contains(@content-desc, "{os.path.splitext(local_photo_filename)[0]}")]'
                    image_obj = u2_d.xpath(image_selector_xpath)
                    time.sleep(1.0)  # 重新查找后等待

                if image_obj.wait(timeout=7.0):  # 增加超时时间
                    if click_element_center_mytapi_refactored(mytapi, image_obj, status_callback):
                        status_callback(f"      成功从相册选择图片 {local_photo_filename}（第 {idx + 1} 张图片）"); time.sleep(3.0)
                    else: 
                        status_callback(f"      点击选择的图片 {local_photo_filename} 失败（第 {idx + 1} 张图片）"); 
                        current_step_successful = False; 
                        break
                else: 
                    status_callback(f"      在相册中未找到图片 {local_photo_filename}（第 {idx + 1} 张图片）"); 
                    current_step_successful = False; 
                    break
                
                # 选择完成后等待并确认进入下一张图片选择
                time.sleep(3.0)
                
            status_callback("所有图片选择完成。")
            time.sleep(2.0)

        # Step 5: 输入文本并发布推文
        if current_step_successful:
            status_callback("准备输入推文文本并发布。")
            time.sleep(2.0)
            tweet_text_field = u2_d.xpath(TWEET_TEXT_INPUT_XPATH)
            if tweet_text_field.wait(timeout=10.0):
                status_callback("找到推文文本输入框。")
                time.sleep(1.0)
                if click_element_center_mytapi_refactored(mytapi, tweet_text_field, status_callback): 
                    time.sleep(1.5)  # 增加点击后等待时间
                    status_callback(f"输入推文内容: '{tweet_text}'")
                    if send_text_char_by_char(mytapi, tweet_text, status_callback, char_delay=0.15):  # 增加字符输入延迟
                        status_callback("成功输入推文内容。"); time.sleep(2.0)  # 增加输入后等待时间
                        
                        # 尝试发布
                        status_callback("查找发布推文按钮...")
                        time.sleep(1.5)  # 查找发布按钮前等待
                        post_button_obj = u2_d.xpath(POST_TWEET_BUTTON_XPATH)
                        if post_button_obj.wait(timeout=7.0):  # 增加超时时间
                            status_callback("找到发布推文按钮。尝试点击...")
                            time.sleep(1.0)  # 点击前等待
                            # 使用click_exists，对简单按钮点击通常更可靠
                            if post_button_obj.click_exists(timeout=3.0):
                                status_callback("成功点击发布推文按钮。"); time.sleep(4.0) # 增加发布后等待时间
                                action_successful = True # All steps completed successfully
                            else:
                                status_callback("点击发布推文按钮失败。"); current_step_successful = False
                        else:
                            status_callback("未找到发布推文按钮。"); current_step_successful = False
                    else:
                        status_callback("输入推文内容失败。"); current_step_successful = False
                else:
                    status_callback("点击/聚焦推文文本输入框失败。"); current_step_successful = False
            else:
                status_callback("打开编辑器后未找到推文文本输入框。"); current_step_successful = False
        else:
            status_callback("由于之前的错误或选择，跳过最终推文输入和发布。")
        
        if not current_step_successful and action_successful:
             # This case implies a step failed but action_successful was somehow true before final check.
             # Ensure action_successful is false if any current_step_successful became false.
             action_successful = False

    except Exception as e_main_try:
        status_callback(f"{device_info}发送推文过程中发生意外错误: {e_main_try}")
        status_callback(traceback.format_exc())
        action_successful = False # Ensure overall failure
    finally:
        status_callback(f"{device_info}--- run_post_tweet: 进入清理阶段 ---")
        if mytapi_initialized:
            try:
                status_callback(f"{device_info}尝试在清理阶段设置MytRpc工作模式为0...")
                if mytapi.setRpaWorkMode(0):
                    status_callback(f"{device_info}MytRpc在清理阶段成功设置工作模式为0。")
                else:
                    status_callback(f"{device_info}MytRpc在清理阶段设置工作模式为0失败。")
            except Exception as e_rpa_cleanup:
                status_callback(f"{device_info}MytRpc在清理阶段设置工作模式为0时出错: {e_rpa_cleanup}")
        
        if u2_d:
            try:
                status_callback(f"{device_info}尝试在清理阶段停止uiautomator服务...")
                u2_d.service("uiautomator").stop()
                status_callback(f"{device_info}uiautomator服务停止命令已发送。")
            except Exception as e_u2_stop_cleanup:
                status_callback(f"{device_info}在清理阶段停止uiautomator服务时出错: {e_u2_stop_cleanup}")
            
            # Optionally, stop the app if the overall action was not successful
            if not action_successful: # Only stop app if tweet posting failed or was incomplete
                try:
                    status_callback(f"{device_info}由于操作未成功，尝试在清理阶段停止Twitter应用 (com.twitter.android)...")
                    u2_d.app_stop("com.twitter.android")
                    status_callback(f"{device_info}Twitter应用停止命令已发送。")
                except Exception as e_app_stop_cleanup:
                    status_callback(f"{device_info}在清理阶段停止Twitter应用时出错: {e_app_stop_cleanup}")
            else:
                status_callback(f"{device_info}操作成功，Twitter应用将保持打开状态。")

        status_callback(f"{device_info}--- run_post_tweet: 清理阶段完成 ('{'成功' if action_successful else '遇到故障'}') ---")
    
    return action_successful

if __name__ == '__main__':
    def console_status_callback(message):
        print(message)

    console_status_callback("Running postTweetTest.py as a standalone script.")

    test_device_ip = "192.168.8.74"
    test_u2_port = 5006
    test_myt_rpc_port = 11060
    
    default_tweet_text = "Testing multi-image tweet!"
    default_attach_image = False # Set to True to test with images
    # For multiple images, provide a comma-separated string of paths if using CLI for arg 6
    # Example: "path/to/image1.jpg,path/to/image2.png"
    default_image_paths_str = "test_image1.jpg,test_image2.jpg" # Dummy paths for default

    # Args: ip u2_port myt_port tweet_text attach_image_bool [image_paths_comma_separated]
    if len(sys.argv) >= 6: 
        console_status_callback("Using command-line arguments.")
        test_device_ip = sys.argv[1]
        try:
            test_u2_port = int(sys.argv[2])
            test_myt_rpc_port = int(sys.argv[3])
        except ValueError:
            console_status_callback("Error: u2_port and myt_rpc_port must be integers. Exiting."); sys.exit(1)
        
        default_tweet_text = sys.argv[4]
        attach_image_str = sys.argv[5].lower()
        if attach_image_str not in ['true', 'false']:
            console_status_callback("Error: attach_image_bool (arg 5) must be 'true' or 'false'. Exiting."); sys.exit(1)
        default_attach_image = (attach_image_str == 'true')
        
        image_paths_list_for_script = []
        if default_attach_image:
            if len(sys.argv) >= 7:
                default_image_paths_str = sys.argv[6]
                image_paths_list_for_script = [p.strip() for p in default_image_paths_str.split(',') if p.strip()]
                if not image_paths_list_for_script:
                    console_status_callback("Warning: Image attachment is true, but no valid image paths found in comma-separated list.")
                    default_attach_image = False # Effectively disable if paths are bad/empty
                else:
                    for p in image_paths_list_for_script:
                        if not os.path.exists(p):
                            console_status_callback(f"Warning: Provided image path '{p}' does not exist. Image attachment might fail for this image.")
            else:
                console_status_callback("Error: Image attachment is true, but no image paths provided (arg 6 missing). Exiting."); sys.exit(1)
        
    else: # No/few CLI args, use defaults
        console_status_callback(f"No/insufficient command-line arguments. Using default test values: Tweet='{default_tweet_text}', AttachImage={default_attach_image}")
        image_paths_list_for_script = []
        if default_attach_image:
            image_paths_list_for_script = [p.strip() for p in default_image_paths_str.split(',') if p.strip()]
            console_status_callback(f"Default image paths for testing: {image_paths_list_for_script}")
            # Create dummy files if they don't exist for default testing
            for p_path in image_paths_list_for_script:
                if not os.path.exists(p_path):
                    try:
                        # Ensure the directory exists before creating the file
                        os.makedirs(os.path.dirname(p_path) or '.', exist_ok=True)
                        with open(p_path, 'w') as f: f.write(f"dummy content for {p_path}")
                        console_status_callback(f"Created dummy '{p_path}' for testing.")
                    except Exception as e_create_dummy:
                        console_status_callback(f"Could not create dummy '{p_path}': {e_create_dummy}.")
    
    # Actual paths passed to the function
    final_image_paths = image_paths_list_for_script if default_attach_image else []

    success = run_post_tweet(console_status_callback, test_device_ip, test_u2_port, test_myt_rpc_port, 
                             default_tweet_text, default_attach_image, final_image_paths)
    
    if success:
        console_status_callback("Standalone post tweet script completed successfully.")
    else:
        console_status_callback("Standalone post tweet script encountered issues or failed.")
    sys.exit(0 if success else 1)
