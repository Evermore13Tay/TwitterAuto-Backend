import logging
import time
import sys
import uiautomator2 as u2
from common.mytRpc import MytRpc
from common.u2_connection import connect_to_device
import os
from datetime import datetime
import traceback

_LOG_DIR_SCRIPT_CHECK = "."
try:
    _LOG_DIR_SCRIPT_CHECK = os.path.dirname(sys.executable) # For bundled app
except Exception:
    _LOG_DIR_SCRIPT_CHECK = os.path.abspath(os.path.dirname(__file__))

_SCRIPT_LOG_PATH_CHECK = os.path.join(_LOG_DIR_SCRIPT_CHECK, "CHECKLOGINTest_execution.log")

def script_log_check(message):
    try:
        with open(_SCRIPT_LOG_PATH_CHECK, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] [CHECKLOGINTest] {message}\n")
            f.flush()
    except Exception as e:
        print(f"Error writing to CHECKLOGINTest log: {e}")

script_log_check(f"--- check_twitter_login_status.py script top-level loaded ---")
script_log_check(f"sys.executable: {sys.executable}")
script_log_check(f"os.getcwd(): {os.getcwd()}")
if hasattr(sys, '_MEIPASS'):
    script_log_check(f"sys._MEIPASS (from check_twitter_login_status.py): {sys._MEIPASS}")
else:
    script_log_check("check_twitter_login_status.py: Not running from _MEIPASS bundle (no sys._MEIPASS attribute).")

def check_twitter_login_status(status_callback, device_ip_address, u2_port, myt_rpc_port, username_val):
    script_log_check(f"Function check_twitter_login_status entered.")
    script_log_check(f"  Parameters: device_ip={device_ip_address}, u2_port={u2_port}, myt_rpc_port={myt_rpc_port}, username={username_val}")
    script_log_check(f"  Callback type: {type(status_callback)}")

    u2_device = None # Use a consistent name for U2 device
    myt_rpc = None   # Use a consistent name for MytRpc instance
    is_logged_in = False
    # error_message = None # This was for a different function structure

    original_log_level = logging.getLogger().getEffectiveLevel()
    logging.getLogger().setLevel(logging.ERROR) # Reduce verbosity from libraries during this check
    script_log_check(f"Temporarily set root logger level to ERROR.")

    try:
        status_callback("--- Twitter Login Status Check Started --- (Bundled App)")
        script_log_check("Attempting to connect to device via U2...")
        # connect_to_device now returns a tuple (device, success_boolean)
        u2_device, connect_success = connect_to_device(device_ip_address, u2_port, status_callback)
        if not connect_success or u2_device is None:
            script_log_check("U2 device connection failed.")
            status_callback(f"Error: U2连接失败 {device_ip_address}:{u2_port}")
            return False
        script_log_check(f"U2 device connected successfully: {u2_device}")

        script_log_check("Attempting to initialize MytRpc...")
        myt_rpc = MytRpc() 
        if not myt_rpc.init(device_ip_address, myt_rpc_port, 10, max_retries=3): # Added timeout argument back
            script_log_check("MytRpc initialization failed.")
            status_callback(f"Error: MytRpc初始化失败 {device_ip_address}:{myt_rpc_port}")
            return False 
        script_log_check("MytRpc initialized successfully.")

        # Original logic for stopping/starting app and checking UI elements
        script_log_check("Executing app stop/start sequence and UI checks...")
        status_callback(f"检查设备 {device_ip_address} 上的 Twitter 账号 {username_val} 登录状态...")
        
        script_log_check("Stopping Twitter app (1st time)...")
        status_callback("关闭 Twitter 应用 (第一次)...")
        myt_rpc.stopApp("com.twitter.android")
        time.sleep(5)
        script_log_check("Twitter app stopped (1st time).")

        script_log_check("Opening Twitter app (1st time)...")
        status_callback("打开 Twitter 应用 (第一次)...")
        myt_rpc.openApp("com.twitter.android")
        time.sleep(5)  # Wait for app to load
        script_log_check("Twitter app opened (1st time).")

        script_log_check("Stopping Twitter app (2nd time)...")
        status_callback("关闭 Twitter 应用 (第二次)...")
        myt_rpc.stopApp("com.twitter.android")
        time.sleep(2)
        script_log_check("Twitter app stopped (2nd time).")

        script_log_check("Opening Twitter app (2nd time)...")
        status_callback("打开 Twitter 应用 (第二次)...")
        myt_rpc.openApp("com.twitter.android")
        time.sleep(5)  # Wait for app to load
        script_log_check("Twitter app opened (2nd time).")
        
        login_indicators = [
            {'desc': '导航抽屉按钮', 'xpath': '//*[@content-desc="Show navigation drawer"]'},
            {'desc': '首页标签', 'xpath': '//*[@content-desc="Home Tab"]'},
            {'desc': '时间线', 'xpath': '//*[@resource-id="com.twitter.android:id/timeline"]'},
            {'desc': '底部导航栏', 'xpath': '//*[@resource-id="com.twitter.android:id/channels"]'},
            {'desc': '搜索按钮', 'xpath': '//*[@content-desc="Search and Explore"]'},
            {'desc': '发推按钮', 'xpath': '//*[@resource-id="com.twitter.android:id/composer_write"]'}
        ]
        
        script_log_check("Checking for login indicators...")
        status_callback("检查登录状态指标...")
        for indicator in login_indicators:
            script_log_check(f"  Checking for: {indicator['desc']} ({indicator['xpath']})")
            try:
                element = u2_device.xpath(indicator['xpath'])
                if element.exists:
                    script_log_check(f"  [+] Found login indicator: {indicator['desc']}")
                    status_callback(f"[+] 已检测到登录状态: {indicator['desc']}")
                    is_logged_in = True
                    break 
            except Exception as e_xpath_login:
                script_log_check(f"  [!] Exception checking login indicator {indicator['desc']}: {str(e_xpath_login)}")
                status_callback(f"检查 {indicator['desc']} 时出错: {str(e_xpath_login)}")
        
        if is_logged_in:
            script_log_check("Login confirmed by UI indicators.")
        else:
            script_log_check("No definitive login indicators found. Checking for logout/login page indicators...")
            login_page_indicators = [
                {'desc': '登录按钮', 'xpath': '//*[@text="Log in"]'},
                {'desc': '用户名输入框', 'xpath': '//*[contains(@text, "Phone, email, or username")]'},
                {'desc': '注册按钮', 'xpath': '//*[@text="Sign up"]'}
            ]
            for indicator in login_page_indicators:
                script_log_check(f"  Checking for logout/login page: {indicator['desc']} ({indicator['xpath']})")
                try:
                    element = u2_device.xpath(indicator['xpath'])
                    if element.exists:
                        script_log_check(f"  [-] Found logout/login page indicator: {indicator['desc']}. User is not logged in.")
                        status_callback(f"[-] 检测到未登录状态: 发现{indicator['desc']}")
                        is_logged_in = False # Explicitly false
                        break
                except Exception as e_xpath_logout:
                    script_log_check(f"  [!] Exception checking logout/login page indicator {indicator['desc']}: {str(e_xpath_logout)}")
                    status_callback(f"检查 {indicator['desc']} 时出错: {str(e_xpath_logout)}")
            
            if not is_logged_in and not any(u2_device.xpath(ind['xpath']).exists for ind in login_page_indicators if u2_device): # Recheck if still not confirmed as logged out
                 script_log_check("[!] Final check: Unable to determine login status. No clear login or logout indicators found.")
                 status_callback("[!] 无法确定登录状态，未检测到明确的登录或未登录指标")
                 # is_logged_in remains False by default

    except Exception as e:
        script_log_check(f"!!! EXCEPTION in check_twitter_login_status: {type(e).__name__} - {str(e)} !!!")
        script_log_check(traceback.format_exc())
        status_callback(f"检查登录状态时发生意外错误: {str(e)}")
        is_logged_in = False
    finally:
        script_log_check("Executing finally block...")
        if myt_rpc:
            script_log_check("Attempting to close MytRpc connection and set RPA mode to 0...")
            try:
                myt_rpc.setRpaWorkMode(0) # From original user logic
                myt_rpc.close()
                script_log_check("MytRpc closed and RPA mode set.")
            except Exception as e_close_myt:
                script_log_check(f"Exception while closing MytRpc/setting RPA mode: {type(e_close_myt).__name__} - {str(e_close_myt)}")
        
        logging.getLogger().setLevel(original_log_level) # Restore original log level
        script_log_check(f"Restored root logger level to {logging.getLevelName(original_log_level)}.")
        status_callback("--- Twitter Login Status Check Completed --- (Bundled App)")
        script_log_check(f"Function check_twitter_login_status finished. Returning: {is_logged_in}")

    return is_logged_in

if __name__ == "__main__":
    def console_status_callback(message):
        print(message)
        
    if len(sys.argv) < 5:
        console_status_callback("用法: python check_twitter_login_status.py <设备IP> <u2端口> <myt_rpc端口> <用户名>")
        sys.exit(1)
        
    device_ip = sys.argv[1]
    u2_port = int(sys.argv[2])
    myt_rpc_port = int(sys.argv[3])
    username = sys.argv[4]
    
    result = check_twitter_login_status(console_status_callback, device_ip, u2_port, myt_rpc_port, username)
    
    if result:
        console_status_callback("[+] Twitter 账号已登录")
    else:
        console_status_callback("[-] Twitter 账号未登录")
        
    sys.exit(0 if result else 1) 