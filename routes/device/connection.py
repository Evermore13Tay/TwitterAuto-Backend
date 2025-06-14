"""
设备连接测试路由
包含测试设备连接和uiautomator2连接功能
"""
import logging
import asyncio
import requests
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from db.database import get_db
from db import models
from common.u2_connection import connect_to_device

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/device", tags=["device-connection"])

class DeviceConnectionRequest(BaseModel):
    device_ip: str
    u2_port: int
    device_name: str
    device_id: str

class ContainerConnectionRequest(BaseModel):
    device_ip: str
    device_index: int
    container_name: str

class SmartConnectionRequest(BaseModel):
    slot_number: int
    running_containers: list  # 前端传递的运行中容器列表

class LoginRequest(BaseModel):
    device_ip: str
    u2_port: int
    myt_rpc_port: int
    username: str
    password: str
    secret_key: str

class DeviceConnectionResponse(BaseModel):
    success: bool
    message: str
    device_info: Optional[dict] = None

@router.post("/test-connection", response_model=DeviceConnectionResponse)
async def test_device_connection(
    request: DeviceConnectionRequest,
    db: Session = Depends(get_db)
):
    """
    测试设备连接，特别是uiautomator2连接
    
    Args:
        request: 包含设备连接信息的请求体
        db: 数据库会话
    
    Returns:
        DeviceConnectionResponse: 连接测试结果
    """
    device_info = f"[{request.device_name}({request.device_ip}:{request.u2_port})]"
    
    # 状态日志收集
    status_logs = []
    
    def status_callback(message: str):
        """收集状态消息的回调函数"""
        status_logs.append(message)
        logger.info(f"{device_info} {message}")
    
    try:
        # 从数据库验证设备存在
        device_record = db.query(models.DeviceUser).filter(
            models.DeviceUser.id == request.device_id
        ).first()
        
        if not device_record:
            logger.error(f"设备ID {request.device_id} 在数据库中不存在")
            return DeviceConnectionResponse(
                success=False,
                message=f"设备ID {request.device_id} 不存在"
            )
        
        # 验证设备信息匹配
        if (device_record.device_ip != request.device_ip or 
            device_record.u2_port != request.u2_port or
            device_record.device_name != request.device_name):
            logger.warning(f"设备信息不匹配 - 数据库: {device_record.device_name}({device_record.device_ip}:{device_record.u2_port}), 请求: {request.device_name}({request.device_ip}:{request.u2_port})")
        
        status_callback("开始连接测试...")
        
        # 使用异步执行器运行同步的连接函数
        loop = asyncio.get_event_loop()
        u2_device, connect_success = await loop.run_in_executor(
            None,
            connect_to_device,
            request.device_ip,
            request.u2_port,
            status_callback
        )
        
        if connect_success and u2_device:
            # 获取设备基本信息
            try:
                device_info_dict = {
                    "serial": u2_device.device_info.get('serial', 'N/A') if u2_device.device_info else 'N/A',
                    "screen_size": u2_device.window_size() if u2_device else None,
                    "device_ip": request.device_ip,
                    "u2_port": request.u2_port,
                    "device_name": request.device_name,
                    "device_index": device_record.device_index,
                    "status_logs": status_logs[-5:]  # 只返回最后5条日志
                }
                
                status_callback("连接测试完成，所有功能正常")
                
                return DeviceConnectionResponse(
                    success=True,
                    message="设备连接测试成功，uiautomator2服务正常工作",
                    device_info=device_info_dict
                )
                
            except Exception as info_error:
                logger.warning(f"获取设备详细信息时出错: {info_error}")
                return DeviceConnectionResponse(
                    success=True,
                    message="设备连接成功，但获取详细信息时遇到问题",
                    device_info={
                        "device_ip": request.device_ip,
                        "u2_port": request.u2_port,
                        "device_name": request.device_name,
                        "device_index": device_record.device_index,
                        "status_logs": status_logs[-5:],
                        "warning": str(info_error)
                    }
                )
        else:
            error_message = "设备连接失败，请检查：\n1. 设备是否在线\n2. uiautomator2服务是否正常\n3. 网络连接是否正常\n4. 端口是否正确"
            logger.error(f"{device_info} 连接失败")
            
            return DeviceConnectionResponse(
                success=False,
                message=error_message,
                device_info={
                    "device_ip": request.device_ip,
                    "u2_port": request.u2_port,
                    "device_name": request.device_name,
                    "device_index": device_record.device_index,
                    "status_logs": status_logs[-10:],  # 失败时返回更多日志
                    "connection_status": "failed"
                }
            )
            
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"连接测试过程中发生异常: {str(e)}", exc_info=True)
        return DeviceConnectionResponse(
            success=False,
            message=f"连接测试异常: {str(e)}",
            device_info={
                "device_ip": request.device_ip,
                "u2_port": request.u2_port,
                "device_name": request.device_name,
                "status_logs": status_logs,
                "error": str(e)
            }
        )

async def get_real_time_container_status(device_ip: str, slot_number: int):
    """
    获取实时的容器状态
    
    Args:
        device_ip: 设备IP
        slot_number: 实例位编号
    
    Returns:
        list: 运行中的容器列表
    """
    try:
        url = f"http://localhost:5000/get/{device_ip}?index={slot_number}"
        response = requests.get(url, timeout=30)
        data = response.json()
        
        if data.get("code") == 200 and "msg" in data:
            # 过滤出状态为 "running" 的容器
            running_containers = [
                container for container in data["msg"] 
                if container.get("State") == "running"
            ]
            logger.info(f"📡 实时容器状态: 找到 {len(running_containers)} 个运行中的容器 (总共 {len(data['msg'])} 个)")
            
            # 调试日志：打印所有容器状态
            for container in data["msg"]:
                logger.info(f"📄 容器详情: {container['Names']} - {container['State']}")
            
            # 调试日志：打印运行中的容器
            for container in running_containers:
                logger.info(f"🟢 运行中容器: {container['Names']} - {container['State']}")
                
            return running_containers
        else:
            logger.warning(f"获取容器状态失败: {data}")
            return []
    except Exception as e:
        logger.error(f"获取实时容器状态异常: {e}")
        return []

@router.get("/connect-instance-slot/{slot_number}")
async def connect_to_instance_slot(
    slot_number: int,
    db: Session = Depends(get_db)
):
    """
    连接到指定实例位的设备（基于实时容器状态的智能选择）
    
    Args:
        slot_number: 实例位编号
        db: 数据库会话
    
    Returns:
        dict: 连接结果
    """
    try:
        # 获取实时容器状态
        device_ip = "10.18.96.3"  # 暂时硬编码，可以后续改为配置
        running_containers = await get_real_time_container_status(device_ip, slot_number)
        
        if not running_containers:
            # 如果没有运行中的容器，回退到数据库选择
            logger.warning("⚠️ 没有发现运行中的容器，回退到数据库选择策略")
            devices = db.query(models.DeviceUser).filter(
                models.DeviceUser.device_index == slot_number
            ).all()
            
            if not devices:
                raise HTTPException(
                    status_code=404,
                    detail=f"未找到实例位 {slot_number} 的设备"
                )
            
            # 优先选择test_user_001设备
            test_user_devices = [d for d in devices if 'test_user_001' in d.device_name]
            device = test_user_devices[0] if test_user_devices else devices[0]
            logger.info(f"📂 数据库选择策略: 选择设备 {device.device_name}")
        else:
            # 基于运行中的容器进行智能选择
            logger.info(f"🎯 发现 {len(running_containers)} 个运行中的容器，开始智能选择...")
            
            # 优先选择test_user_001容器
            target_container = None
            for container in running_containers:
                if 'test_user_001' in container.get('Names', ''):
                    target_container = container
                    logger.info(f"✅ 智能选择策略: 优先选择test_user_001容器: {container['Names']}")
                    break
            
            # 如果没有test_user_001，选择第一个运行中的容器
            if not target_container:
                target_container = running_containers[0]
                logger.info(f"✅ 智能选择策略: 选择第一个运行中的容器: {target_container['Names']}")
            
            # 尝试在数据库中查找对应的设备记录
            # 注意：可能根据容器名称查找更准确
            device = None
            
            # 方法1：根据容器名称模糊匹配
            container_name = target_container['Names']
            db_device_by_name = db.query(models.DeviceUser).filter(
                models.DeviceUser.device_name.contains(container_name.split('_')[1] if '_' in container_name else container_name)
            ).first()
            
            # 方法2：根据IP和索引匹配
            db_device_by_ip = db.query(models.DeviceUser).filter(
                models.DeviceUser.device_ip == target_container['ip'],
                models.DeviceUser.device_index == target_container['index']
            ).first()
            
            device = db_device_by_name or db_device_by_ip
            
            if device:
                logger.info(f"📂 找到数据库设备记录: {device.device_name} (匹配方式: {'名称' if db_device_by_name else 'IP+索引'})")
            else:
                logger.warning(f"⚠️ 数据库中未找到容器 {container_name} 的设备记录，使用默认配置")
                # 创建临时设备记录，直接使用容器信息
                device = type('TempDevice', (), {
                    'device_name': container_name,
                    'device_ip': target_container['ip'],
                    'device_index': target_container['index'],
                    'u2_port': 5555,  # 默认端口
                    'id': f"temp_{container_name}"
                })()
        
        if not device:
            raise HTTPException(
                status_code=404,
                detail=f"未找到实例位 {slot_number} 的可用设备"
            )
        
        # 检查设备信息完整性
        if not device.device_ip or not device.u2_port:
            raise HTTPException(
                status_code=400,
                detail=f"设备 {device.device_name} 的IP或端口信息不完整"
            )
        
        # 构建连接请求
        connection_request = DeviceConnectionRequest(
            device_ip=device.device_ip,
            u2_port=device.u2_port,
            device_name=device.device_name,
            device_id=str(device.id)  # 确保ID是字符串类型
        )
        
        # 记录最终选择的设备
        logger.info(f"🎯 最终选择设备: {device.device_name} ({device.device_ip}:{device.u2_port})")
        
        # 执行连接测试
        result = await test_device_connection(connection_request, db)
        
        return {
            "slot_number": slot_number,
            "device_info": {
                "id": device.id,
                "name": device.device_name,
                "ip": device.device_ip,
                "port": device.u2_port,
                "index": device.device_index
            },
            "connection_result": result.dict()
        }
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"连接实例位 {slot_number} 时发生异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"连接实例位 {slot_number} 时发生异常: {str(e)}"
        )

@router.post("/connect", response_model=DeviceConnectionResponse)
async def connect_to_device_by_container(
    request: ContainerConnectionRequest,
    db: Session = Depends(get_db)
):
    """
    基于容器信息连接到设备
    
    Args:
        request: 包含容器连接信息的请求体
        db: 数据库会话
    
    Returns:
        DeviceConnectionResponse: 连接结果
    """
    try:
        # 查找数据库中匹配的设备
        device = db.query(models.DeviceUser).filter(
            models.DeviceUser.device_ip == request.device_ip,
            models.DeviceUser.device_index == request.device_index
        ).first()
        
        if not device:
            # 如果数据库中没有找到，创建一个临时的设备记录进行连接
            logger.info(f"数据库中未找到设备 {request.container_name}，使用默认端口连接")
            u2_port = 5555  # 默认的UIAutomator2端口
            myt_rpc_port = 9999  # 默认的MytRpc端口
        else:
            u2_port = device.u2_port
            myt_rpc_port = device.myt_rpc_port
            logger.info(f"找到数据库设备记录: {device.device_name}")
        
        # 状态日志收集
        status_logs = []
        
        def status_callback(message: str):
            """收集状态消息的回调函数"""
            status_logs.append(message)
            logger.info(f"[{request.container_name}] {message}")
        
        status_callback(f"开始连接设备容器: {request.container_name}")
        status_callback(f"设备IP: {request.device_ip}, 实例索引: {request.device_index}")
        status_callback(f"U2端口: {u2_port}, MytRpc端口: {myt_rpc_port}")
        
        # 使用异步执行器运行同步的连接函数
        loop = asyncio.get_event_loop()
        u2_device, connect_success = await loop.run_in_executor(
            None,
            connect_to_device,
            request.device_ip,
            u2_port,
            status_callback
        )
        
        if connect_success and u2_device:
            # 获取设备基本信息
            try:
                device_info_dict = {
                    "container_name": request.container_name,
                    "device_ip": request.device_ip,
                    "device_index": request.device_index,
                    "u2_port": u2_port,
                    "myt_rpc_port": myt_rpc_port,
                    "serial": u2_device.device_info.get('serial', 'N/A') if u2_device.device_info else 'N/A',
                    "screen_size": u2_device.window_size() if u2_device else None,
                    "status_logs": status_logs[-5:]  # 只返回最后5条日志
                }
                
                status_callback("设备连接成功，UIAutomator2服务正常")
                
                return DeviceConnectionResponse(
                    success=True,
                    message=f"成功连接到设备容器 {request.container_name}",
                    device_info=device_info_dict
                )
                
            except Exception as info_error:
                logger.warning(f"获取设备详细信息时出错: {info_error}")
                return DeviceConnectionResponse(
                    success=True,
                    message="设备连接成功，但获取详细信息时遇到问题",
                    device_info={
                        "container_name": request.container_name,
                        "device_ip": request.device_ip,
                        "device_index": request.device_index,
                        "u2_port": u2_port,
                        "myt_rpc_port": myt_rpc_port,
                        "status_logs": status_logs[-5:],
                        "warning": str(info_error)
                    }
                )
        else:
            error_message = f"连接到设备容器 {request.container_name} 失败，请检查：\n1. 容器是否正在运行\n2. UIAutomator2服务是否正常\n3. 网络连接是否正常"
            logger.error(f"连接失败: {request.container_name}")
            
            return DeviceConnectionResponse(
                success=False,
                message=error_message,
                device_info={
                    "container_name": request.container_name,
                    "device_ip": request.device_ip,
                    "device_index": request.device_index,
                    "u2_port": u2_port,
                    "myt_rpc_port": myt_rpc_port,
                    "status_logs": status_logs[-10:],  # 失败时返回更多日志
                    "connection_status": "failed"
                }
            )
            
    except Exception as e:
        logger.error(f"连接设备容器时发生异常: {str(e)}", exc_info=True)
        return DeviceConnectionResponse(
            success=False,
            message=f"连接异常: {str(e)}",
            device_info={
                "container_name": request.container_name,
                "device_ip": request.device_ip,
                "device_index": request.device_index,
                "error": str(e)
            }
        )

@router.post("/connect-smart", response_model=DeviceConnectionResponse)
async def smart_connect_with_containers(
    request: SmartConnectionRequest,
    db: Session = Depends(get_db)
):
    """
    基于前端传递的容器信息进行智能连接
    
    Args:
        request: 包含槽位号和运行中容器列表的请求体
        db: 数据库会话
    
    Returns:
        DeviceConnectionResponse: 连接结果
    """
    try:
        running_containers = request.running_containers
        slot_number = request.slot_number
        
        logger.info(f"🎯 前端传递了 {len(running_containers)} 个运行中容器，开始智能选择...")
        
        if not running_containers:
            logger.warning("⚠️ 前端未传递运行中的容器，回退到数据库选择策略")
            devices = db.query(models.DeviceUser).filter(
                models.DeviceUser.device_index == slot_number
            ).all()
            
            if not devices:
                return DeviceConnectionResponse(
                    success=False,
                    message=f"未找到实例位 {slot_number} 的设备"
                )
            
            # 优先选择test_user_001设备
            test_user_devices = [d for d in devices if 'test_user_001' in d.device_name]
            device = test_user_devices[0] if test_user_devices else devices[0]
            logger.info(f"📂 数据库选择策略: 选择设备 {device.device_name}")
        else:
            # 基于运行中的容器进行智能选择
            # 优先选择test_user_001容器
            target_container = None
            for container in running_containers:
                if 'test_user_001' in container.get('Names', ''):
                    target_container = container
                    logger.info(f"✅ 智能选择策略: 优先选择test_user_001容器: {container['Names']}")
                    break
            
            # 如果没有test_user_001，选择第一个运行中的容器
            if not target_container:
                target_container = running_containers[0]
                logger.info(f"✅ 智能选择策略: 选择第一个运行中的容器: {target_container['Names']}")
            
            # 尝试在数据库中查找对应的设备记录
            container_name = target_container['Names']
            device = db.query(models.DeviceUser).filter(
                models.DeviceUser.device_name.contains(container_name.split('_')[1] if '_' in container_name else container_name)
            ).first()
            
            if not device:
                # 根据IP和索引再次查找
                device = db.query(models.DeviceUser).filter(
                    models.DeviceUser.device_ip == target_container['ip'],
                    models.DeviceUser.device_index == target_container['index']
                ).first()
            
            if device:
                logger.info(f"📂 找到数据库设备记录: {device.device_name}")
            else:
                logger.warning(f"⚠️ 数据库中未找到容器 {container_name} 的设备记录，使用默认配置")
                # 创建临时设备记录，直接使用容器信息
                device = type('TempDevice', (), {
                    'device_name': container_name,
                    'device_ip': target_container['ip'],
                    'device_index': target_container['index'],
                    'u2_port': 5555,  # 默认端口
                    'id': f"temp_{container_name}"
                })()
        
        if not device:
            return DeviceConnectionResponse(
                success=False,
                message=f"未找到实例位 {slot_number} 的可用设备"
            )
        
        # 检查设备信息完整性
        if not device.device_ip or not device.u2_port:
            return DeviceConnectionResponse(
                success=False,
                message=f"设备 {device.device_name} 的IP或端口信息不完整"
            )
        
        # 记录最终选择的设备
        logger.info(f"🎯 最终选择设备: {device.device_name} ({device.device_ip}:{device.u2_port})")
        
        # 状态日志收集
        status_logs = []
        
        def status_callback(message: str):
            """收集状态消息的回调函数"""
            status_logs.append(message)
            logger.info(f"[{device.device_name}] {message}")
        
        status_callback(f"开始连接设备: {device.device_name}")
        status_callback(f"设备IP: {device.device_ip}, U2端口: {device.u2_port}")
        
        # 使用异步执行器运行同步的连接函数
        loop = asyncio.get_event_loop()
        u2_device, connect_success = await loop.run_in_executor(
            None,
            connect_to_device,
            device.device_ip,
            device.u2_port,
            status_callback
        )
        
        if connect_success and u2_device:
            # 获取设备基本信息
            try:
                device_info_dict = {
                    "device_name": device.device_name,
                    "device_ip": device.device_ip,
                    "device_index": device.device_index,
                    "u2_port": device.u2_port,
                    "serial": u2_device.device_info.get('serial', 'N/A') if u2_device.device_info else 'N/A',
                    "screen_size": u2_device.window_size() if u2_device else None,
                    "status_logs": status_logs[-5:]
                }
                
                status_callback("设备连接成功，UIAutomator2服务正常")
                
                return DeviceConnectionResponse(
                    success=True,
                    message=f"成功连接到设备 {device.device_name}",
                    device_info=device_info_dict
                )
                
            except Exception as info_error:
                logger.warning(f"获取设备详细信息时出错: {info_error}")
                return DeviceConnectionResponse(
                    success=True,
                    message="设备连接成功，但获取详细信息时遇到问题",
                    device_info={
                        "device_name": device.device_name,
                        "device_ip": device.device_ip,
                        "device_index": device.device_index,
                        "u2_port": device.u2_port,
                        "status_logs": status_logs[-5:],
                        "warning": str(info_error)
                    }
                )
        else:
            error_message = f"连接到设备 {device.device_name} 失败，请检查：\n1. 设备是否在线\n2. UIAutomator2服务是否正常\n3. 网络连接是否正常"
            logger.error(f"连接失败: {device.device_name}")
            
            return DeviceConnectionResponse(
                success=False,
                message=error_message,
                device_info={
                    "device_name": device.device_name,
                    "device_ip": device.device_ip,
                    "device_index": device.device_index,
                    "u2_port": device.u2_port,
                    "status_logs": status_logs[-10:],
                    "connection_status": "failed"
                }
            )
            
    except Exception as e:
        logger.error(f"智能连接时发生异常: {str(e)}", exc_info=True)
        return DeviceConnectionResponse(
            success=False,
            message=f"连接异常: {str(e)}",
            device_info={
                "error": str(e)
            }
        )

@router.post("/login", response_model=DeviceConnectionResponse)
async def login_to_twitter(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    登录Twitter账号
    
    Args:
        request: 包含设备信息和登录凭据的请求体
        db: 数据库会话
    
    Returns:
        DeviceConnectionResponse: 登录结果
    """
    try:
        # 导入登录函数
        from automation.logintest import run_login
        
        # 状态日志收集
        status_logs = []
        
        def status_callback(message: str):
            """收集状态消息的回调函数"""
            status_logs.append(message)
            logger.info(f"[LOGIN] {message}")
        
        logger.info(f"开始Twitter登录: {request.username} -> {request.device_ip}:{request.u2_port}")
        status_callback(f"开始登录用户: {request.username}")
        status_callback(f"设备地址: {request.device_ip}:{request.u2_port}")
        status_callback(f"MytRpc端口: {request.myt_rpc_port}")
        
        # 调用登录函数
        login_success = run_login(
            status_callback=status_callback,
            device_ip_address=request.device_ip,
            u2_port=request.u2_port,
            myt_rpc_port=request.myt_rpc_port,
            username_val=request.username,
            password_val=request.password,
            secret_key_2fa_val=request.secret_key
        )
        
        if login_success:
            logger.info(f"Twitter登录成功: {request.username}")
            return DeviceConnectionResponse(
                success=True,
                message=f"用户 {request.username} 登录成功",
                device_info={
                    "username": request.username,
                    "device_ip": request.device_ip,
                    "u2_port": request.u2_port,
                    "myt_rpc_port": request.myt_rpc_port,
                    "status_logs": status_logs[-10:],  # 返回最后10条日志
                    "login_time": asyncio.get_event_loop().time()
                }
            )
        else:
            logger.warning(f"Twitter登录失败: {request.username}")
            return DeviceConnectionResponse(
                success=False,
                message=f"用户 {request.username} 登录失败，请检查账号密码或设备状态",
                device_info={
                    "username": request.username,
                    "device_ip": request.device_ip,
                    "u2_port": request.u2_port,
                    "myt_rpc_port": request.myt_rpc_port,
                    "status_logs": status_logs[-15:],  # 失败时返回更多日志
                    "login_status": "failed"
                }
            )
            
    except Exception as e:
        logger.error(f"登录过程中发生异常: {str(e)}", exc_info=True)
        return DeviceConnectionResponse(
            success=False,
            message=f"登录异常: {str(e)}",
            device_info={
                "username": request.username,
                "device_ip": request.device_ip,
                "error": str(e)
            }
        ) 