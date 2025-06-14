import time
import subprocess
import logging
import uiautomator2 as u2
import socket
import sys
import traceback

# UIAutomator2 Accessibility Service Component Name
U2_ACCESSIBILITY_SERVICE = "com.github.uiautomator/androidx.test.uiautomator.UiAutomatorAccessibilityService"

def check_port_availability(ip, port, timeout=1):
    """检查指定IP和端口是否可连接"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    result = sock.connect_ex((ip, port))
    sock.close()
    return result == 0

def restart_adb_server(status_callback=None):
    """尝试重启ADB服务器"""
    if status_callback:
        status_callback("尝试重启ADB服务器...")
    
    try:
        # 先杀死ADB服务器进程
        kill_process = subprocess.run(["adb", "kill-server"], 
                                       capture_output=True, text=True, timeout=10)
        if status_callback:
            status_callback(f"ADB kill-server 返回码: {kill_process.returncode}")
        
        time.sleep(2)  # 给进程一些时间来终止
        
        # 启动新的ADB服务器
        start_process = subprocess.run(["adb", "start-server"], 
                                        capture_output=True, text=True, timeout=10)
        if status_callback:
            status_callback(f"ADB start-server 返回码: {start_process.returncode}")
        
        time.sleep(3)  # 给ADB服务器一些启动时间
        return True
    except Exception as e:
        if status_callback:
            status_callback(f"重启ADB服务器失败: {e}")
        return False

def restart_atx_agent(device_id, status_callback=None):
    """尝试重启设备上的ATX-Agent服务"""
    if status_callback:
        status_callback(f"尝试重启设备 {device_id} 上的ATX-Agent服务...")
    
    try:
        # 检查设备是否通过adb连接
        if ":" in device_id:  # IP:端口格式
            ip, port = device_id.split(":")
            connect_cmd = ["adb", "connect", device_id]
            status_callback(f"尝试通过ADB连接设备: {' '.join(connect_cmd)}")
            connect_result = subprocess.run(connect_cmd, capture_output=True, text=True, timeout=10)
            status_callback(f"ADB连接结果: {connect_result.stdout}")
            
            # 不管是否连接成功，我们继续尝试后续操作
        
        # 尝试通过uiautomator app启动atx-agent服务
        if status_callback:
            status_callback("尝试启动uiautomator app...")
            
        # 获取设备的adb ID
        device_adb_id = device_id
        
        # 停止并重新启动uiautomator服务
        stop_cmd = f"adb -s {device_adb_id} shell am force-stop com.github.uiautomator"
        if status_callback:
            status_callback(f"执行: {stop_cmd}")
        subprocess.run(stop_cmd, shell=True, timeout=10)
        time.sleep(1)
        
        start_cmd = f"adb -s {device_adb_id} shell am start -n com.github.uiautomator/.MainActivity"
        if status_callback:
            status_callback(f"执行: {start_cmd}")
        subprocess.run(start_cmd, shell=True, timeout=10)
        
        # 等待ATX-Agent启动
        if status_callback:
            status_callback("等待20秒让ATX-Agent完全启动...")
        time.sleep(20)
        
        # 检查ATX-Agent是否启动成功
        if ":" in device_id:
            ip = device_id.split(":")[0]
            agent_port = 7912  # 默认ATX-Agent端口
            
            # 检查端口是否可连接
            if check_port_availability(ip, agent_port):
                if status_callback:
                    status_callback(f"ATX-Agent成功启动，端口 {ip}:{agent_port} 可连接")
                return True
            else:
                if status_callback:
                    status_callback(f"ATX-Agent启动失败，端口 {ip}:{agent_port} 不可连接")
                return False
        else:
            # 如果不是IP格式，我们只能假设重启成功
            if status_callback:
                status_callback("ATX-Agent服务重启命令已发送，但无法确认是否成功")
            return True
            
    except Exception as e:
        if status_callback:
            status_callback(f"重启ATX-Agent服务失败: {e}")
        return False

def reset_uiautomator_service(device_id, status_callback=None):
    """尝试重置设备上的uiautomator服务"""
    if status_callback:
        status_callback(f"尝试重置设备 {device_id} 上的uiautomator服务...")
    
    try:
        # 停止uiautomator服务
        stop_cmd = ["adb", "-s", device_id, "shell", "am", "force-stop", "com.github.uiautomator"]
        subprocess.run(stop_cmd, capture_output=True, text=True, timeout=10)
        
        # 停止uiautomator测试服务
        stop_test_cmd = ["adb", "-s", device_id, "shell", "am", "force-stop", "com.github.uiautomator.test"]
        subprocess.run(stop_test_cmd, capture_output=True, text=True, timeout=10)
        
        time.sleep(2)
        
        # 重启设备上的Accessibility服务
        try:
            if status_callback:
                status_callback("尝试重启设备上的Accessibility服务...")
            # 重启设置应用
            settings_cmd = ["adb", "-s", device_id, "shell", "am", "start", "-n", "com.android.settings/.Settings"]
            subprocess.run(settings_cmd, capture_output=True, text=True, timeout=10)
            time.sleep(2)
            
            # 停止设置应用
            stop_settings_cmd = ["adb", "-s", device_id, "shell", "am", "force-stop", "com.android.settings"]
            subprocess.run(stop_settings_cmd, capture_output=True, text=True, timeout=10)
            time.sleep(1)
        except Exception as access_error:
            if status_callback:
                status_callback(f"重启Accessibility服务时出错: {access_error}")
        
        # 使用u2的init_device来重新初始化设备服务
        try:
            # 使用u2 init命令来全新初始化设备
            python_exe = sys.executable if hasattr(sys, 'executable') else 'python'
            init_cmd = [python_exe, "-m", "uiautomator2", "init", device_id]
            if status_callback:
                status_callback(f"执行u2 init命令: {' '.join(init_cmd)}")
            
            init_result = subprocess.run(init_cmd, capture_output=True, text=True, timeout=60)
            if status_callback:
                if init_result.stdout:
                    status_callback(f"Init输出: {init_result.stdout[:300]}{'...' if len(init_result.stdout) > 300 else ''}")
                if init_result.stderr:
                    status_callback(f"Init错误: {init_result.stderr[:300]}{'...' if len(init_result.stderr) > 300 else ''}")
            
            time.sleep(10)  # 给足够的时间初始化
            
            # 启动uiautomator app并等待
            start_app_cmd = ["adb", "-s", device_id, "shell", "am", "start", "-n", "com.github.uiautomator/.MainActivity"]
            subprocess.run(start_app_cmd, capture_output=True, text=True, timeout=10)
            time.sleep(5)  # 给app启动时间
            
            if status_callback:
                status_callback(f"uiautomator服务重置成功")
            return True
        except Exception as init_error:
            if status_callback:
                status_callback(f"初始化设备服务失败: {init_error}")
                status_callback(traceback.format_exc())
            return False
    except Exception as e:
        if status_callback:
            status_callback(f"重置uiautomator服务失败: {e}")
            status_callback(traceback.format_exc())
        return False

def fix_accessibility_service(device_id_or_serial, status_callback):
    """
    尝试修复指定设备上的Accessibility服务，确保UIAutomator2服务已启用。
    Args:
        device_id_or_serial: 设备序列号或IP:端口格式的设备ID
        status_callback: 状态回调函数
    Returns:
        bool: 修复尝试是否执行 (不一定表示成功修复)
    """
    status_callback(f"尝试对设备 {device_id_or_serial} 进行彻底的无障碍服务修复...")

    # 确定ADB设备标识符
    adb_target_id = device_id_or_serial
    # if ':' in device_id_or_serial: # Likely IP:Port format - adb commands handle this target directly
    #     pass

    try:
        # 1. Force-stop com.github.uiautomator package
        status_callback(f"强制停止设备 {adb_target_id} 上的 com.github.uiautomator 应用...")
        subprocess.run(["adb", "-s", adb_target_id, "shell", "am", "force-stop", "com.github.uiautomator"], 
                       capture_output=True, text=True, timeout=10)
        time.sleep(2)

        # 2. Disable global accessibility
        status_callback(f"临时禁用设备 {adb_target_id} 上的全局无障碍服务...")
        subprocess.run(["adb", "-s", adb_target_id, "shell", "settings", "put", "secure", "accessibility_enabled", "0"], 
                       check=True, capture_output=True, text=True, timeout=5)
        time.sleep(1)

        # 3. Log and clear all currently enabled accessibility services
        cmd_get_enabled_services = ["adb", "-s", adb_target_id, "shell", "settings", "get", "secure", "enabled_accessibility_services"]
        result_get_before = subprocess.run(cmd_get_enabled_services, capture_output=True, text=True, timeout=10)
        original_enabled_services = result_get_before.stdout.strip()
        status_callback(f"设备 {adb_target_id} 上修复前已启用的服务: '{original_enabled_services}'")

        status_callback(f"清除设备 {adb_target_id} 上所有已启用的无障碍服务...")
        subprocess.run(["adb", "-s", adb_target_id, "shell", "settings", "put", "secure", "enabled_accessibility_services", ""], 
                       check=True, capture_output=True, text=True, timeout=10) # Use empty string to clear
        time.sleep(1)

        # 4. Enable ONLY the UIAutomator2 accessibility service
        status_callback(f"在设备 {adb_target_id} 上专门启用 UIAutomator2 无障碍服务 ({U2_ACCESSIBILITY_SERVICE})...")
        cmd_enable_u2_only = ["adb", "-s", adb_target_id, "shell", "settings", "put", "secure", "enabled_accessibility_services", U2_ACCESSIBILITY_SERVICE]
        status_callback(f"执行命令: {' '.join(cmd_enable_u2_only)}")
        subprocess.run(cmd_enable_u2_only, check=True, capture_output=True, text=True, timeout=10)
        time.sleep(1)

        # 5. Enable global accessibility
        status_callback(f"重新启用设备 {adb_target_id} 上的全局无障碍服务...")
        subprocess.run(["adb", "-s", adb_target_id, "shell", "settings", "put", "secure", "accessibility_enabled", "1"], 
                       check=True, capture_output=True, text=True, timeout=5)
        status_callback(f"全局无障碍服务已在设备 {adb_target_id} 上重新启用。")
        time.sleep(3) 

        # 6. Restart the com.github.uiautomator app (ATX Agent)
        status_callback(f"重启设备 {adb_target_id} 上的 ATX Agent (com.github.uiautomator) 以应用更改...")
        subprocess.run(["adb", "-s", adb_target_id, "shell", "am", "start", "-n", "com.github.uiautomator/.MainActivity"], 
                       capture_output=True, text=True, timeout=10)
        status_callback(f"ATX Agent (com.github.uiautomator) 重启命令已发送至设备 {adb_target_id}。等待服务初始化...")
        time.sleep(10) # Increased delay for ATX agent to fully start and register accessibility

        # 7. Verify service is now enabled
        result_get_after = subprocess.run(cmd_get_enabled_services, capture_output=True, text=True, timeout=10)
        final_enabled_services = result_get_after.stdout.strip()
        status_callback(f"设备 {adb_target_id} 上修复后最终启用的服务: '{final_enabled_services}'")
        
        if U2_ACCESSIBILITY_SERVICE not in final_enabled_services:
            status_callback(f"警告: UIAutomator2服务 ({U2_ACCESSIBILITY_SERVICE}) 在修复流程后仍未出现在启用列表中: '{final_enabled_services}'。可能需要手动检查设备设置。")
        else:
            status_callback(f"成功: UIAutomator2服务 ({U2_ACCESSIBILITY_SERVICE}) 已在设备 {adb_target_id} 的启用列表中。")

        status_callback(f"设备 {adb_target_id} 的Accessibility服务修复流程完成。")
        return True

    except subprocess.CalledProcessError as e:
        status_callback(f"执行ADB命令失败: {e}. 输出: {e.output},错误: {e.stderr}")
        return False
    except subprocess.TimeoutExpired as e:
        status_callback(f"执行ADB命令超时: {e}")
        return False
    except Exception as e:
        status_callback(f"修复Accessibility服务时发生未知错误: {e}\n{traceback.format_exc()}")
        return False

def try_reconnect_u2(u2_target, max_retries=3, status_callback=None, initial_delay=5, backoff_factor=2):
    """
    尝试多种方法重新连接u2设备
    
    Args:
        u2_target: 设备IP:端口，例如 "192.168.1.100:5555"
        max_retries: 最大重试次数
        status_callback: 状态回调函数
        initial_delay: 初始重试延迟（秒）
        backoff_factor: 每次重试延迟倍增因子
    Returns:
        tuple: (u2_device, success_flag)
    """
    if status_callback:
        status_callback(f"开始尝试重新连接设备 {u2_target}...")
    
    # 解析IP和端口
    parts = u2_target.split(':')
    device_ip = parts[0]
    device_port = int(parts[1]) if len(parts) > 1 else 5555
    
    # 构建设备ID
    device_id = f"{device_ip}:{device_port}"
    
    for attempt in range(1, max_retries + 1):
        if status_callback:
            status_callback(f"重连尝试 {attempt}/{max_retries}")
        
        # 检查ATX-Agent端口是否可用
        if status_callback:
            status_callback(f"检查设备 {device_ip} 上的ATX-Agent端口(7912)...")
        
        atx_agent_available = check_port_availability(device_ip, 7912)
        if atx_agent_available:
            if status_callback:
                status_callback(f"设备 {device_ip} 上的ATX-Agent端口(7912)可连接")
        else:
            if status_callback:
                status_callback(f"设备 {device_ip} 上的ATX-Agent端口(7912)不可连接，需要重启服务")
            
            # 如果ATX-Agent端口不可用，尝试重启ATX-Agent
            if restart_atx_agent(device_id, status_callback):
                if status_callback:
                    status_callback(f"已尝试重启设备 {device_ip} 上的ATX-Agent服务")
            else:
                if status_callback:
                    status_callback(f"无法重启设备 {device_ip} 上的ATX-Agent服务")
        
        # 方法1：直接尝试重新连接
        try:
            if status_callback:
                status_callback("方法1: 直接尝试重新连接...")
            u2_device = u2.connect(u2_target)
            
            # 检查是否可以获取设备信息
            try:
                info = u2_device.info
                screen = u2_device.window_size()
                if info and screen[0] > 0:
                    # 检查是否可以进行窗口层次结构转储
                    try:
                        u2_device.dump_hierarchy()
                        if status_callback:
                            status_callback("窗口层次结构转储测试成功")
                    except Exception as dump_error:
                        if status_callback:
                            status_callback(f"窗口层次结构转储测试失败: {dump_error}")
                        # 尝试修复Accessibility服务
                        if status_callback:
                            status_callback("尝试修复Accessibility服务问题...")
                        fix_accessibility_service(device_id, status_callback)
                        time.sleep(5)
                    
                    if status_callback:
                        status_callback(f"重置服务后重连成功! 屏幕尺寸: {screen}")
                    return u2_device, True
            except Exception:
                if status_callback:
                    status_callback("连接对象创建但无法获取设备信息")
        except Exception as e1:
            if status_callback:
                status_callback(f"直接重连失败: {e1}")
        
        # 方法2：重启ADB服务器
        if restart_adb_server(status_callback):
            try:
                if status_callback:
                    status_callback("方法2: 重启ADB服务器后尝试连接...")
                u2_device = u2.connect(u2_target)
                
                # 检查是否可以获取设备信息
                try:
                    info = u2_device.info
                    screen = u2_device.window_size()
                    if info and screen[0] > 0:
                        # 检查是否可以进行窗口层次结构转储
                        try:
                            u2_device.dump_hierarchy()
                            if status_callback:
                                status_callback("窗口层次结构转储测试成功")
                        except Exception as dump_error:
                            if status_callback:
                                status_callback(f"窗口层次结构转储测试失败: {dump_error}")
                            # 尝试修复Accessibility服务
                            if status_callback:
                                status_callback("尝试修复Accessibility服务问题...")
                            fix_accessibility_service(device_id, status_callback)
                            time.sleep(5)
                        
                        if status_callback:
                            status_callback(f"重启ADB后重连成功! 屏幕尺寸: {screen}")
                        return u2_device, True
                except Exception:
                    if status_callback:
                        status_callback("连接对象创建但无法获取设备信息")
            except Exception as e2:
                if status_callback:
                    status_callback(f"重启ADB后重连失败: {e2}")
        
        # 方法3：尝试重新连接ADB设备
        try:
            if status_callback:
                status_callback("方法3: 尝试通过ADB重新连接设备...")
            # 先断开连接
            disconnect_cmd = ["adb", "disconnect", device_id]
            subprocess.run(disconnect_cmd, capture_output=True, text=True, timeout=10)
            
            time.sleep(2)
            
            # 重新连接
            connect_cmd = ["adb", "connect", device_id]
            connect_result = subprocess.run(connect_cmd, capture_output=True, text=True, timeout=10)
            if status_callback:
                status_callback(f"ADB连接结果: {connect_result.stdout.strip()}")
            
            if "connected" in connect_result.stdout.lower():
                # ADB重连成功，现在尝试u2连接
                time.sleep(2)
                try:
                    if status_callback:
                        status_callback("ADB连接成功，尝试u2连接...")
                    u2_device = u2.connect(u2_target)
                    
                    # 检查是否可以获取设备信息
                    try:
                        info = u2_device.info
                        screen = u2_device.window_size()
                        if info and screen[0] > 0:
                            # 检查是否可以进行窗口层次结构转储
                            try:
                                u2_device.dump_hierarchy()
                                if status_callback:
                                    status_callback("窗口层次结构转储测试成功")
                            except Exception as dump_error:
                                if status_callback:
                                    status_callback(f"窗口层次结构转储测试失败: {dump_error}")
                                # 尝试修复Accessibility服务
                                if status_callback:
                                    status_callback("尝试修复Accessibility服务问题...")
                                fix_accessibility_service(device_id, status_callback)
                                time.sleep(5)
                            
                            if status_callback:
                                status_callback(f"ADB重连后连接成功! 屏幕尺寸: {screen}")
                            return u2_device, True
                    except Exception:
                        if status_callback:
                            status_callback("连接对象创建但无法获取设备信息")
                except Exception as e3:
                    if status_callback:
                        status_callback(f"ADB重连成功但u2连接失败: {e3}")
        except Exception as e4:
            if status_callback:
                status_callback(f"ADB重连过程出错: {e4}")
        
        # 方法4：完全重置uiautomator服务
        try:
            if status_callback:
                status_callback("方法4: 完全重置uiautomator服务...")
            
            reset_result = reset_uiautomator_service(device_id, status_callback)
            if reset_result:
                try:
                    if status_callback:
                        status_callback("uiautomator服务重置成功，尝试u2连接...")
                    time.sleep(5)
                    u2_device = u2.connect(u2_target)
                    
                    # 检查是否可以获取设备信息
                    try:
                        info = u2_device.info
                        screen = u2_device.window_size()
                        if info and screen[0] > 0:
                            # 检查是否可以进行窗口层次结构转储
                            try:
                                u2_device.dump_hierarchy()
                                if status_callback:
                                    status_callback("窗口层次结构转储测试成功")
                            except Exception as dump_error:
                                if status_callback:
                                    status_callback(f"窗口层次结构转储测试失败: {dump_error}")
                                # 尝试修复Accessibility服务
                                if status_callback:
                                    status_callback("尝试修复Accessibility服务问题...")
                                fix_accessibility_service(device_id, status_callback)
                                time.sleep(5)
                            
                            if status_callback:
                                status_callback(f"重置服务后重连成功! 屏幕尺寸: {screen}")
                            return u2_device, True
                    except Exception:
                        if status_callback:
                            status_callback("连接对象创建但无法获取设备信息")
                except Exception as e5:
                    if status_callback:
                        status_callback(f"重置服务后重连失败: {e5}")
        except Exception as e6:
            if status_callback:
                status_callback(f"重置uiautomator服务过程出错: {e6}")
        
        # 在下一次尝试前等待递增的时间（指数退避策略）
        wait_time = initial_delay * (backoff_factor ** (attempt - 1))
        if status_callback:
            status_callback(f"重试前等待 {wait_time} 秒...")
        time.sleep(wait_time)
    
    # 所有重试都失败
    if status_callback:
        status_callback(f"所有重连方法尝试 {max_retries} 次后均失败。建议检查设备连接或重启设备。")
    
    return None, False

# 使用示例
if __name__ == "__main__":
    def print_callback(message):
        print(f"[U2重连] {message}")
    
    device, success = try_reconnect_u2("192.168.1.100:5555", status_callback=print_callback)
    if success:
        print("重连成功!")
        # 测试窗口层次结构转储
        try:
            print("测试窗口层次结构转储...")
            hierarchy = device.dump_hierarchy()
            print(f"窗口层次结构转储成功，长度: {len(hierarchy)}")
        except Exception as e:
            print(f"窗口层次结构转储失败: {e}")
            # 尝试修复Accessibility服务
            print("尝试修复Accessibility服务...")
            fix_accessibility_service(device.serial, print_callback)
    else:
        print("重连失败。")