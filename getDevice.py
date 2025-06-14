import requests # 用于发送 HTTP 请求
import json     # 用于处理 JSON 数据
import logging  # 用于日志记录
import os       # 用于文件路径操作
import time     # 导入 time 模块
import urllib.parse
from sqlalchemy.orm import Session
from db.database import SessionLocal, get_db # 导入数据库会话
from db.models import DeviceUser # 导入设备模型

# --- 配置日志记录，只输出到控制台，不再保存到文件 ---
logger = logging.getLogger(__name__)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.setLevel(logging.INFO)
# 清除之前的handlers，防止重复输出
logger.handlers = []
logger.addHandler(console_handler)

# 减少不必要的日志输出
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

def fetch_initial_list(base_url, ip_address):
    """
    通过 GET /dc_api/v1/list/{ip} 获取初始的容器列表。
    """
    try:
        api_url = f"{base_url}/dc_api/v1/list/{ip_address}"
        logger.info(f"获取容器列表: {api_url}")
        
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        logger.info("容器列表获取成功")
        return response.json() # 直接返回解析后的 JSON
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"容器列表API请求失败: {http_err}")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"容器列表API连接错误: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"容器列表API请求超时: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"容器列表API请求异常: {req_err}")
    except json.JSONDecodeError as json_err:
        logger.error(f"容器列表JSON解析错误: {json_err}")
    
    return None # 错误情况下返回 None

def fetch_detailed_api_info(base_url, ip_address, name):
    """
    通过 GET /get_api_info/{ip}/{name} 端点获取详细信息。
    """
    try:
        encoded_name = urllib.parse.quote(name)
        api_url = f"{base_url}/get_api_info/{ip_address}/{encoded_name}"
        
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        logger.debug(f"端口信息获取成功: {name}")
        return response.json() # 直接返回解析后的 JSON
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"详细信息API请求失败: {name}")
    except requests.exceptions.ConnectionError as conn_err:
        logger.error(f"详细信息API连接错误: {name}")
    except requests.exceptions.Timeout as timeout_err:
        logger.error(f"详细信息API请求超时: {name}")
    except requests.exceptions.RequestException as req_err:
        logger.error(f"详细信息API请求异常: {name}")
    except json.JSONDecodeError as json_err:
        logger.error(f"详细信息JSON解析错误: {name}")
    
    return None # 错误情况下返回 None

def get_and_combine_data(base_url="http://127.0.0.1:5000", ip_address="192.168.8.74"):
    """
    获取容器列表，然后获取每个实例的详细信息，最后合并到一起。
    """
    try:
        logger.info("应用启动中，正在执行设备信息获取...")
        logger.info(f"使用API基础URL: {base_url}")
        logger.info(f"使用初始列表IP: {ip_address}")
        
        # 获取初始容器列表
        initial_list = fetch_initial_list(base_url, ip_address)
        
        if not initial_list:
            logger.error("无法获取初始容器列表，请检查API可用性。")
            return

        # 打印原始响应数据，帮助调试
        logger.info(f"API响应数据结构: {list(initial_list.keys())}")
        
        # 获取实例列表 - 从正确的键获取数据
        instances = initial_list.get("msg", [])
        
        if not instances:
            logger.warning("容器列表为空，没有实例可用。API返回数据可能不包含'msg'键。")
            # 尝试查找其他可能包含容器数据的键
            if "data" in initial_list and isinstance(initial_list["data"], list):
                logger.info(f"使用'data'键作为容器列表源。")
                instances = initial_list["data"]
            else:
                for key in initial_list.keys():
                    if isinstance(initial_list[key], list) and len(initial_list[key]) > 0:
                        logger.info(f"尝试使用'{key}'键作为容器列表源。")
                        instances = initial_list[key]
                        break
            
            # 如果仍然没有找到数据，返回
            if not instances:
                logger.error(f"无法在API响应中找到有效的容器列表数据。原始响应: {initial_list}")
                return

        # 检查实例是否为预期格式
        if not isinstance(instances, list):
            logger.error(f"意外的实例数据格式，预期列表但获得了: {type(instances)}")
            return

        logger.info(f"从初始列表中获取到 {len(instances)} 个实例。")
        
        # 创建数据库会话
        db = SessionLocal()
        
        try:
            combined_results = []

            # 定义一个延迟时间（秒）
            delay_seconds = 0.5  # 可以根据需要调整这个值
            
            for instance in instances:
                # 检查实例是否为字典类型
                if not isinstance(instance, dict):
                    logger.error(f"意外的实例数据类型: {type(instance)}")
                    continue
                
                # 适配 API 返回的字段名
                device_name = instance.get("Names") or instance.get("names", "unknown")
                status = instance.get("State") or instance.get("status", "unknown")
                ip = instance.get("ip", "unknown")
                device_index = instance.get("index")
                
                # 记录每个实例的基本信息
                logger.info(f"处理实例: Name='{device_name}', Status='{status}', IP='{ip}'")
                
                # 跳过非running状态的实例
                if status.lower() != "running":
                    logger.debug(f"跳过非运行状态的实例: {device_name}, 状态: {status}")
                    continue
                
                # 尝试从实例的基本信息中直接获取端口信息
                adb_port = None
                rpc_port = None
                
                # 按照参考代码中的方式直接从instance获取端口信息
                if "ADB" in instance:
                    adb_str = instance["ADB"].split(":")[-1]
                    if adb_str.isdigit():
                        adb_port = int(adb_str)
                
                if "RPC" in instance:
                    rpc_str = instance["RPC"].split(":")[-1]
                    if rpc_str.isdigit():
                        rpc_port = int(rpc_str)
                
                # 如果无法从基本信息中获取，尝试获取详细API信息
                if not all([adb_port, rpc_port]):
                    logger.info(f"从基本信息中获取端口不完整，尝试获取详细API信息: '{device_name}'")
                    detailed_info = fetch_detailed_api_info(base_url, ip, device_name)
                    
                    if detailed_info:
                        # 在详细信息中查找服务列表
                        services = detailed_info.get("services", [])
                        # 处理可能是字典的情况
                        if isinstance(detailed_info.get("msg"), dict):
                            # 优先使用参考代码中使用的格式直接获取端口信息
                            msg_data = detailed_info.get("msg", {})
                            
                            if not adb_port and "ADB" in msg_data:
                                adb_str = msg_data["ADB"].split(":")[-1]
                                if adb_str.isdigit():
                                    adb_port = int(adb_str)
                            
                            if not rpc_port and "RPC" in msg_data:
                                rpc_str = msg_data["RPC"].split(":")[-1]
                                if rpc_str.isdigit():
                                    rpc_port = int(rpc_str)
                        
                        # 如果仍然无法获取，尝试通过服务列表
                        if services and (not all([adb_port, rpc_port])):
                            for service in services:
                                service_type = service.get("type", "")
                                url = service.get("url", "")
                                
                                if service_type and url:
                                    port_str = url.split(":")[-1]
                                    
                                    if port_str.isdigit():
                                        port = int(port_str)
                                        if service_type == "adb" and not adb_port:
                                            adb_port = port
                                        elif service_type == "rpc" and not rpc_port:
                                            rpc_port = port
                    else:
                        logger.warning(f"无法获取 '{device_name}' 的详细信息，将使用基本信息。")
                
                # 记录获取到的端口信息
                logger.info(f"设备 '{device_name}' 端口信息: ADB={adb_port}, RPC={rpc_port}")
                
                # 更新数据库
                device_name_from_api = device_name
                device_ip_from_api = ip
                
                db_device = db.query(DeviceUser).filter(DeviceUser.device_name == device_name_from_api).first()

                # 检查端口唯一性并更新或创建设备记录
                if db_device:
                    # 更新现有记录
                    logger.debug(f"在数据库中找到设备 '{device_name_from_api}'。正在检查端口唯一性...")

                    # 检查并更新U2端口(ADB)
                    if adb_port:
                        same_port_device = db.query(DeviceUser).filter(
                            DeviceUser.device_ip == device_ip_from_api,
                            DeviceUser.u2_port == adb_port,
                            DeviceUser.id != db_device.id
                        ).first()
                        
                        if same_port_device:
                            logger.warning(f"同一IP {device_ip_from_api} 下已有设备 '{same_port_device.device_name}' 使用U2端口 {adb_port}，为 '{device_name_from_api}' 保持原端口值 {db_device.u2_port}。")
                        else:
                            db_device.u2_port = adb_port

                    # 检查并更新MYT RPC端口
                    if rpc_port:
                        same_port_device = db.query(DeviceUser).filter(
                            DeviceUser.device_ip == device_ip_from_api,
                            DeviceUser.myt_rpc_port == rpc_port,
                            DeviceUser.id != db_device.id
                        ).first()
                        
                        if same_port_device:
                            logger.warning(f"同一IP {device_ip_from_api} 下已有设备 '{same_port_device.device_name}' 使用MYT RPC端口 {rpc_port}，为 '{device_name_from_api}' 保持原端口值 {db_device.myt_rpc_port}。")
                        else:
                            db_device.myt_rpc_port = rpc_port

                    # 更新设备IP和索引
                    db_device.device_ip = device_ip_from_api
                    if device_index is not None:
                        db_device.device_index = device_index

                    logger.info(f"设备 '{device_name_from_api}' 信息已更新。IP:{device_ip_from_api}, ADB:{adb_port}, RPC:{rpc_port}, index:{device_index}")
                else:
                    # 创建新记录，先检查所有端口的唯一性
                    if adb_port:
                        same_port_device = db.query(DeviceUser).filter(
                            DeviceUser.device_ip == device_ip_from_api,
                            DeviceUser.u2_port == adb_port
                        ).first()
                        if same_port_device:
                            logger.warning(f"同一IP {device_ip_from_api} 下已有设备 '{same_port_device.device_name}' 使用U2端口 {adb_port}，需要生成新端口。")
                            adb_port = find_unused_port(db, 'u2_port', 5001, device_ip_from_api)

                    if rpc_port:
                        same_port_device = db.query(DeviceUser).filter(
                            DeviceUser.device_ip == device_ip_from_api,
                            DeviceUser.myt_rpc_port == rpc_port
                        ).first()
                        if same_port_device:
                            logger.warning(f"同一IP {device_ip_from_api} 下已有设备 '{same_port_device.device_name}' 使用MYT RPC端口 {rpc_port}，需要生成新端口。")
                            rpc_port = find_unused_port(db, 'myt_rpc_port', 11001, device_ip_from_api)

                    # 创建新记录
                    new_device = DeviceUser(
                        device_name=device_name_from_api,
                        device_ip=device_ip_from_api,
                        u2_port=adb_port,
                        myt_rpc_port=rpc_port,
                        device_index=device_index
                    )
                    db.add(new_device)
                    logger.info(f"创建新设备记录 '{device_name_from_api}'。IP:{device_ip_from_api}, ADB:{adb_port}, RPC:{rpc_port}, index:{device_index}")

                # 添加到合并结果中
                combined_instance_info = {
                    **instance,
                    "ADB_PORT": adb_port,
                    "RPC_PORT": rpc_port
                }
                combined_results.append(combined_instance_info)
                
                # 延迟一点时间，避免请求过于频繁
                time.sleep(delay_seconds)

            # 提交数据库更改
            db.commit()
            logger.info("设备信息获取完成")
            
            return combined_results
        except Exception as e:
            logger.exception(f"更新数据库时出错: {e}")
            db.rollback()
        finally:
            db.close()

    except Exception as e:
        logger.exception(f"获取和合并数据时出错: {e}")

def find_unused_port(db, port_type, start_port, device_ip):
    """查找指定IP下未使用的端口"""
    current_port = start_port
    while True:
        if port_type == 'u2_port':
            existing = db.query(DeviceUser).filter(
                DeviceUser.device_ip == device_ip,
                DeviceUser.u2_port == current_port
            ).first()
        elif port_type == 'myt_rpc_port':
            existing = db.query(DeviceUser).filter(
                DeviceUser.device_ip == device_ip,
                DeviceUser.myt_rpc_port == current_port
            ).first()
            
        if not existing:
            return current_port
            
        current_port += 1

if __name__ == "__main__":
    results = get_and_combine_data()
    logger.info("设备信息更新完成")
