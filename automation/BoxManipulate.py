import requests
import logging
import os
import urllib.parse
import random # 导入 random 模块用于生成随机数
import time
import threading

# 配置日志 - 只使用控制台输出（防重复配置）
logger = logging.getLogger(__name__)
logger.handlers.clear()  # 清除所有已存在的处理器
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.setLevel(logging.INFO)
logger.addHandler(console_handler)
logger.propagate = False  # 防止向父logger传播

# 减少不必要的日志输出
logging.getLogger('urllib3').setLevel(logging.WARNING)

# API 服务器的基础 URL，如果所有 API 都在同一个服务器和端口，可以定义一个全局变量
# 例如: API_BASE_URL = "http://127.0.0.1:5000"
# 然后在每个函数中使用它，例如 f"{API_BASE_URL}/export/{ip_address}/{encoded_name}"
# 为保持与您提供代码段的一致性，暂时仍在每个函数中单独指定。

def call_export_api(ip_address, name, local_path):
    """调用容器导出API
    
    参数:
    ip_address: 目标主机IP地址
    name: 容器名称
    local_path: 导出到本地的路径
    
    返回值:
    成功返回True，失败返回False
    """
    try:
        # 确保导出目录存在
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # URL编码容器名称，避免特殊字符问题
        encoded_name = urllib.parse.quote(name)
        
        # 使用新的API路径格式
        api_url = f"http://127.0.0.1:5000/dc_api/v1/export/{ip_address}/{encoded_name}"
        
        # 添加local参数表示导出到主机本地，并指定导出路径
        params = {
            'local': 'true',
            'path': local_path
        }
        
        logger.info(f"导出容器: {name}, 导出路径: {local_path}")
        
        # 发送GET请求到导出API，设置超时为5分钟
        response = requests.get(api_url, params=params, timeout=300)
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                # 检查响应是否成功
                if response_data.get('code') == 200 or response_data.get('message') == 'success':
                    logger.info(f"容器 {name} 已成功导出到 {local_path}")
                    return True
                else:
                    logger.error(f"容器 {name} 导出API返回错误响应: {response_data}")
                    return False
            except Exception as e:
                logger.warning(f"解析导出响应时出错，但可能导出已成功: {e}")
                # 即使解析JSON失败，尝试检查文件是否存在
                if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                    logger.info(f"虽然解析响应失败，但文件已创建: {local_path}")
                    return True
                return False
        else:
            try:
                error_text = response.text
            except:
                error_text = "无法获取错误详情"
                
            logger.error(f"容器 {name} 导出API返回错误: {response.status_code}, 原因: {error_text}")
            return False
            
    except Exception as e:
        logger.error(f"容器 {name} 导出异常: {str(e)}")
        return False

def generate_random_four_digits():
    """生成一个五位的随机数字字符串，例如 '0042' 或 '1234'."""
    return str(random.randint(0, 9999)).zfill(5)

# 全局调用计数器（用于调试重复日志问题）
import threading
_call_count_lock = threading.Lock()
_call_import_count = 0

def call_import_api(ip_address, name, local_path, index=None):
    """调用容器导入API，将本地文件导入为容器
    
    参数:
    ip_address: 目标主机IP地址
    name: 目标容器名称 (将被作为新容器名称使用)
    local_path: 本地容器文件路径
    index: 容器索引，如果未提供则随机生成
    
    返回值:
    成功返回新容器名称（字符串），失败返回None
    """
    global _call_import_count
    
    try:
        # 调用计数器
        with _call_count_lock:
            _call_import_count += 1
            call_number = _call_import_count
        
        # 确保文件存在
        if not os.path.exists(local_path):
            logger.error(f"[调用#{call_number}] 容器文件不存在: {local_path}")
            return None
            
        # 直接使用提供的name作为目标容器名称
        target_name = name
        
        # URL编码容器名称
        encoded_target_name = urllib.parse.quote(target_name)
        
        # 使用传入的index或生成随机索引
        if index is None:
            index = random.randint(1, 9)
        
        # 使用新的API路径格式
        api_url = f"http://127.0.0.1:5000/dc_api/v1/import/{ip_address}/{encoded_target_name}/{index}"
        
        logger.info(f"[调用#{call_number}] 导入容器: 目标名称={target_name}, 索引={index}, 文件路径={local_path}, API URL={api_url}")
        
        # 使用GET请求并传递local参数，与成功的curl命令保持一致
        params = {'local': local_path}
        response = requests.get(api_url, params=params, timeout=300)
        
        if response.status_code == 200:
            try:
                # 尝试解析响应
                response_data = response.json()
                # 记录完整的响应内容以便调试
                logger.info(f"[调用#{call_number}] 导入API响应: {response_data}")
                
                # 检查API响应中的code字段
                if response_data.get('code') == 200:
                    logger.info(f"[调用#{call_number}] 容器导入成功，名称: {target_name}")
                    return target_name
                else:
                    logger.error(f"[调用#{call_number}] 容器导入API返回错误响应: {response_data}")
                    return None
            except Exception as e:
                logger.warning(f"[调用#{call_number}] 解析导入响应时出错: {e}")
                # 即使解析失败，只要HTTP状态码是200，我们仍然认为导入成功
                logger.info(f"[调用#{call_number}] 容器导入可能成功，使用目标名称: {target_name}")
                return target_name
        else:
            logger.error(f"[调用#{call_number}] 容器导入API返回错误: {response.status_code}, 原因: {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"[调用#{call_number}] 容器导入异常: {str(e)}")
        return None

def call_reboot_api(ip_address, name, wait_after_reboot=False):
    """调用容器重启API
    
    参数:
    ip_address: 容器所在主机的IP地址
    name: 容器名称
    wait_after_reboot: 是否在重启后等待（默认False，由上层控制等待）
    
    返回值:
    成功返回True，失败返回False
    """
    try:
        # URL编码容器名称
        encoded_name = urllib.parse.quote(name)
        
        # 使用新的API路径格式，直接 /reboot/
        api_url = f"http://127.0.0.1:5000/reboot/{ip_address}/{encoded_name}"
        
        logger.info(f"重启容器: {name} using url {api_url}")
        
        # 发送GET请求到重启API
        response = requests.get(api_url, timeout=60) # Increased timeout for reboot
        
        if response.status_code == 200 or response.status_code == 202: # 202 Accepted is also a success
            logger.info(f"容器 {name} 重启指令已发送")
            
            # 只有在明确要求等待时才等待（保持向后兼容）
            if wait_after_reboot:
                logger.info(f"容器 {name} 等待30秒模拟重启...")
                time.sleep(30)
                logger.info(f"容器 {name} 重启假定完成。")
            
            return True
        else:
            logger.error(f"容器 {name} 重启API返回错误: {response.status_code}, 原因: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"容器 {name} 重启异常: {str(e)}")
        return False

def call_stop_api(ip_address, name):
    """调用容器停止API
    
    参数:
    ip_address: 容器所在主机的IP地址
    name: 容器名称
    
    返回值:
    成功返回True，失败返回False
    """
    try:
        # URL编码容器名称
        encoded_name = urllib.parse.quote(name)
        
        # 使用新的API路径格式，直接 /stop/
        api_url = f"http://127.0.0.1:5000/stop/{ip_address}/{encoded_name}"
        
        logger.info(f"停止容器: {name} using url {api_url}")
        
        # 发送GET请求到停止API
        response = requests.get(api_url, timeout=60)
        
        if response.status_code == 200:
            logger.info(f"容器 {name} 已成功停止")
            return True
        else:
            logger.error(f"容器 {name} 停止API返回错误: {response.status_code}, 原因: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"容器 {name} 停止异常: {str(e)}")
        return False

if __name__ == "__main__":
    # 示例用法
    export_ip_val = "192.168.1.100"
    export_name_val = "container_name" 
    export_local_val = "D:/backup_folder/container_name.tar.gz"
    
    # 导出容器示例
    success = call_export_api(export_ip_val, export_name_val, export_local_val)
    print(f"导出结果: {'成功' if success else '失败'}")

    print("\n" + "="*40 + "\n") # 分隔符

    # 2. Import 操作
    import_ip_val = "192.168.8.74"
    # 注意：根据您的要求，reboot 的 name 是 import 的 new_name。
    # 所以 import_base_name_prefix 应该是您期望 reboot 时使用的 name 的前缀部分。
    import_base_name_prefix = "2b8fb511cdcd48970c5171ee7c2c49a7" # 用于生成 new_name 的前缀
    import_index_val = 6
    import_local_file = "D:/mytBackUp/PKertzmann5650.tar.gz" # 要导入的本地文件路径
                                                            # (与 export_local_val 相同，按您提供的信息)
    
    print("--- 开始 Import 操作 ---")
    # 调用 Import API 函数并获取生成的 new_name
    imported_new_name = call_import_api(import_ip_val, import_base_name_prefix, import_local_file)
    if imported_new_name:
        print(f"Import 操作成功，生成的 new_name 用于 Reboot: {imported_new_name}")
    else:
        print("Import 操作失败，将跳过 Reboot 操作。")
    print("--- Import 操作结束 ---")

    print("\n" + "="*40 + "\n") # 分隔符

    # 3. Reboot 操作
    # Reboot 使用 Import 操作中生成的 new_name
    if imported_new_name: # 仅当 import 成功并返回了 new_name 时才执行 reboot
        reboot_ip_val = "192.168.8.74" # 通常与 import 的 IP 相同
        
        print("--- 开始 Reboot 操作 ---")
        call_reboot_api(reboot_ip_val, imported_new_name, wait_after_reboot=True)
        print("--- Reboot 操作结束 ---")
    else:
        print("由于 Import 操作未成功或未返回 new_name，Reboot 操作已跳过。")

