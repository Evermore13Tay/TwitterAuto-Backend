import uiautomator2 as u2
import time
import subprocess
import socket
import traceback
from common.u2_reconnector import try_reconnect_u2, fix_accessibility_service

def check_port_availability(ip, port, timeout=1):
    """检查指定IP和端口是否可连接"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    result = sock.connect_ex((ip, port))
    sock.close()
    return result == 0

def restart_atx_agent(u2_device, status_callback):
    """尝试重启atx-agent服务"""
    try:
        status_callback("尝试重启atx-agent服务...")
        # 获取设备序列号
        serial = u2_device.serial or u2_device.device_info.get('serial', '')
        if not serial:
            status_callback("无法获取设备序列号，无法重启atx-agent")
            return False
            
        # 使用adb重启atx-agent
        restart_cmd = f"adb -s {serial} shell 'am force-stop com.github.uiautomator && am start -n com.github.uiautomator/.MainActivity'"
        status_callback(f"执行命令: {restart_cmd}")
        subprocess.run(restart_cmd, shell=True, timeout=10)
        
        time.sleep(5)  # 等待服务重启
        status_callback("atx-agent服务重启命令已发送")
        return True
    except Exception as e:
        status_callback(f"重启atx-agent服务时出错: {e}")
        return False

def check_uiautomator_status(u2_device, status_callback):
    """
    检查UIAutomator服务状态并尝试修复
    
    Args:
        u2_device: uiautomator2设备对象
        status_callback: 状态回调函数
        
    Returns:
        bool: 服务是否正常运行
    """
    try:
        status_callback("检查UIAutomator服务状态...")
        
        # 首先检查本地端口7912是否可用
        if check_port_availability('127.0.0.1', 7912):
            status_callback("本地uiautomator2服务端口(7912)可连接")
        else:
            status_callback("警告: 本地uiautomator2服务端口(7912)不可连接")
        
        # 使用更直接的方法检查UIAutomator服务
        try:
            # 尝试获取设备信息，如果成功则说明UIAutomator可能正常工作
            info = u2_device.info
            if info:
                status_callback("UIAutomator服务可能正常工作，设备信息可获取")
                
                # 测试是否可以进行窗口层次结构转储
                try:
                    status_callback("测试窗口层次结构转储功能...")
                    hierarchy = u2_device.dump_hierarchy()
                    status_callback("窗口层次结构转储功能正常")
                except Exception as dump_error:
                    status_callback(f"窗口层次结构转储失败: {dump_error}")
                    # 尝试修复Accessibility服务
                    status_callback("检测到Accessibility服务问题，尝试修复...")
                    fix_accessibility_service(u2_device.serial, status_callback)
                    time.sleep(5)
                    # 再次测试
                    try:
                        hierarchy = u2_device.dump_hierarchy()
                        status_callback("修复后窗口层次结构转储成功")
                    except Exception as retry_error:
                        status_callback(f"修复后窗口层次结构转储仍失败: {retry_error}")
                
                return True
        except Exception as e_info:
            status_callback(f"获取设备信息时出错，UIAutomator服务可能不正常: {e_info}")
        
        status_callback("尝试启动UIAutomator服务...")
        
        # 尝试直接使用adb命令启动UIAutomator服务
        try:
            serial = u2_device.serial or (u2_device.device_info.get('serial') if hasattr(u2_device, 'device_info') else None)
            if serial:
                # 停止现有的服务
                stop_cmd = f"adb -s {serial} shell am force-stop com.github.uiautomator"
                status_callback(f"执行: {stop_cmd}")
                subprocess.run(stop_cmd, shell=True, timeout=10)
                time.sleep(1)
                
                # 启动新的服务
                start_cmd = f"adb -s {serial} shell am start -n com.github.uiautomator/.MainActivity"
                status_callback(f"执行: {start_cmd}")
                subprocess.run(start_cmd, shell=True, timeout=10)
                time.sleep(5)
                
                # 检查是否可以获取设备信息
                try:
                    info = u2_device.info
                    if info:
                        status_callback("UIAutomator服务启动成功，设备信息可获取")
                        
                        # 测试是否可以进行窗口层次结构转储
                        try:
                            status_callback("测试u2 init后的窗口层次结构转储功能...")
                            hierarchy = u2_device.dump_hierarchy()
                            status_callback("u2 init后窗口层次结构转储功能正常")
                        except Exception as dump_error:
                            status_callback(f"u2 init后窗口层次结构转储失败: {dump_error}")
                            # 尝试修复Accessibility服务
                            status_callback("u2 init后检测到Accessibility服务问题，尝试修复...")
                            fix_accessibility_service(u2_device.serial, status_callback)
                            time.sleep(5)
                        
                        return True
                except Exception as e:
                    status_callback(f"u2 init后仍然无法获取设备信息: {e}")
            else:
                status_callback("无法获取设备序列号，无法启动UIAutomator服务")
        except Exception as e:
            status_callback(f"启动UIAutomator服务时出错: {e}")
        
        # 尝试使用am instrument命令
        try:
            status_callback("尝试使用am instrument命令启动UIAutomator...")
            cmd = "am instrument -w -r -e debug false -e class com.github.uiautomator.stub.Stub com.github.uiautomator.test/androidx.test.runner.AndroidJUnitRunner"
            status_callback(f"执行命令: {cmd}")
            u2_device.shell(cmd)
            time.sleep(5)  # 给服务更多启动时间
            
            # 检查是否可以获取设备信息
            try:
                info = u2_device.info
                if info:
                    status_callback("UIAutomator服务通过am instrument命令启动成功")
                    return True
            except Exception as e:
                status_callback(f"启动UIAutomator服务后仍然无法获取设备信息: {e}")
            
            # 最后尝试使用u2 init命令初始化
            try:
                # 获取设备序列号并执行init
                serial = u2_device.serial or (u2_device.device_info.get('serial') if hasattr(u2_device, 'device_info') else None)
                if serial:
                    init_cmd = f"python -m uiautomator2 init {serial}"
                    status_callback(f"执行命令: {init_cmd}")
                    subprocess.run(init_cmd, shell=True, timeout=30)
                    time.sleep(8)  # 给更多时间完成初始化
                    
                    # 检查是否可以获取设备信息
                    try:
                        info = u2_device.info
                        if info:
                            status_callback("UIAutomator服务通过u2 init启动成功")
                            
                            # 测试是否可以进行窗口层次结构转储
                            try:
                                status_callback("测试u2 init后的窗口层次结构转储功能...")
                                hierarchy = u2_device.dump_hierarchy()
                                status_callback("u2 init后窗口层次结构转储功能正常")
                            except Exception as dump_error:
                                status_callback(f"u2 init后窗口层次结构转储失败: {dump_error}")
                                # 尝试修复Accessibility服务
                                status_callback("u2 init后检测到Accessibility服务问题，尝试修复...")
                                fix_accessibility_service(u2_device.serial, status_callback)
                                time.sleep(5)
                            
                            return True
                    except Exception as e:
                        status_callback(f"u2 init后仍然无法获取设备信息: {e}")
                else:
                    status_callback("无法获取设备序列号，无法执行u2 init命令")
            except Exception as e_init:
                status_callback(f"执行u2 init命令时出错: {e_init}")
        except Exception as e:
            status_callback(f"尝试通过am instrument启动UIAutomator时出错: {e}")
            
        status_callback("所有UIAutomator服务启动尝试均失败")
        return False
    except Exception as e:
        status_callback(f"检查UIAutomator服务状态时出错: {e}")
        return False

def connect_to_device(device_ip, u2_port, status_callback):
    """
    连接到uiautomator2设备并验证连接状态
    
    Args:
        device_ip: 设备IP地址
        u2_port: uiautomator2端口
        status_callback: 状态回调函数
        
    Returns:
        tuple: (u2_device, success_flag)
    """
    device_info = f"[{device_ip}:{u2_port}] "
    u2_target = f"{device_ip}:{u2_port}"
    
    try:
        status_callback(f"{device_info}连接到uiautomator2设备 {u2_target}...")
        
        # 添加超时机制防止u2.connect卡住（Windows兼容）
        import threading
        import queue
        
        connection_result = queue.Queue()
        connection_error = queue.Queue()
        
        def connect_with_timeout():
            try:
                u2_device = u2.connect(u2_target)
                connection_result.put(u2_device)
            except Exception as e:
                connection_error.put(e)
        
        # 启动连接线程
        connect_thread = threading.Thread(target=connect_with_timeout)
        connect_thread.daemon = True
        connect_thread.start()
        
        # 等待30秒
        connect_thread.join(timeout=30)
        
        if connect_thread.is_alive():
            # 连接超时
            status_callback(f"{device_info}u2.connect超时（30秒），取消连接")
            raise TimeoutError("u2.connect超时30秒")
        
        # 检查连接结果
        if not connection_error.empty():
            error = connection_error.get()
            raise error
        elif not connection_result.empty():
            u2_d = connection_result.get()
        else:
            raise Exception("连接失败，未知原因")
        
        if not u2_d or not u2_d.device_info:
            status_callback(f"{device_info}初始连接失败。尝试重连...")
            # 使用重连机制
            u2_d, reconnect_success = try_reconnect_u2(u2_target, max_retries=3, status_callback=status_callback)
            if not reconnect_success:
                status_callback(f"{device_info}所有重连尝试均失败。请检查设备连接状态。")
                return None, False
        
        # 检查UIAutomator服务状态
        status_callback(f"{device_info}检查并确保UIAutomator服务正常运行...")
        if not check_uiautomator_status(u2_d, lambda msg: status_callback(f"{device_info}{msg}")):
            status_callback(f"{device_info}UIAutomator服务异常且无法恢复，操作可能受限。")
            # 我们仍然继续，但提醒操作可能会失败
        
        # 验证连接有效性
        try:
            status_callback(f"{device_info}测试uiautomator2连接状态（获取屏幕尺寸）...")
            screen_width, screen_height = u2_d.window_size()
            if screen_width and screen_height:
                status_callback(f"{device_info}uiautomator2连接验证成功。屏幕尺寸: {screen_width}x{screen_height}")
                
                # 测试是否可以进行窗口层次结构转储
                try:
                    status_callback(f"{device_info}测试窗口层次结构转储功能...")
                    hierarchy = u2_d.dump_hierarchy()
                    status_callback(f"{device_info}窗口层次结构转储功能正常")
                except Exception as dump_error:
                    status_callback(f"{device_info}窗口层次结构转储失败: {dump_error}")
                    # 尝试修复Accessibility服务
                    status_callback(f"{device_info}检测到Accessibility服务问题，尝试修复...")
                    fix_accessibility_service(u2_d.serial, lambda msg: status_callback(f"{device_info}{msg}"))
                    time.sleep(5)
                    # 再次测试
                    try:
                        hierarchy = u2_d.dump_hierarchy()
                        status_callback(f"{device_info}修复后窗口层次结构转储成功")
                    except Exception as retry_error:
                        status_callback(f"{device_info}修复后窗口层次结构转储仍失败: {retry_error}，但继续操作")
            else:
                status_callback(f"{device_info}uiautomator2连接测试失败 - 无法获取屏幕尺寸。尝试重连...")
                # 尝试重连
                u2_d, reconnect_success = try_reconnect_u2(u2_target, max_retries=3, status_callback=status_callback)
                if not reconnect_success:
                    status_callback(f"{device_info}屏幕尺寸测试后所有重连尝试均失败。请检查设备连接。")
                    return None, False
        except Exception as e_u2_test:
            status_callback(f"{device_info}uiautomator2连接测试出现异常: {e_u2_test}。尝试重连...")
            # 尝试重连
            u2_d, reconnect_success = try_reconnect_u2(u2_target, max_retries=3, status_callback=status_callback)
            if not reconnect_success:
                status_callback(f"{device_info}异常后所有重连尝试均失败。请检查设备连接。")
                return None, False
        
        status_callback(f"{device_info}uiautomator2设备已连接: {u2_d.device_info.get('serial', 'N/A')} via {u2_target}")
        return u2_d, True
        
    except Exception as e:
        status_callback(f"{device_info}连接uiautomator2设备时出错: {e}")
        return None, False 