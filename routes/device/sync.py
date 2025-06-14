"""
设备同步和刷新操作路由
包含从IP获取设备、同步设备名称、端口统一化等功能
"""
import logging
import os
import requests
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException, Query, status as fastapi_status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Dict, Optional, List
from datetime import datetime
from db.database import get_db
from db import models
from schemas.models import DeviceUser
from automation.get_device_by_ip import fetch_devices_by_ip
from .utils import clear_device_cache, find_unused_port, apply_exclusivity_rule

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

# 创建带前缀的路由
router = APIRouter(prefix="/api", tags=["device-sync"])

# 创建不带前缀的路由，用于直接访问
router_no_prefix = APIRouter(tags=["device-sync-direct"])

# 线程池执行器
executor = ThreadPoolExecutor(max_workers=5)

@router.get("/fetch_devices_by_ip", response_model=dict)
async def fetch_devices_by_ip_route(
    ip: str = Query(..., description="设备所在主机的IP地址 (此IP将被视为box_ip)"),
    update_existing_only: bool = Query(False, description="如果为true，则只更新现有设备，不添加新设备"),
    db: Session = Depends(get_db)
):
    """从指定IP获取设备信息并更新数据库"""
    return await _fetch_devices_by_ip_route(ip, update_existing_only, db)

@router.get("/sync-device-names", response_model=dict)
async def sync_device_names_with_prefix(
    ip: str = Query(..., description="设备所在主机的IP地址"),
    db: Session = Depends(get_db)
):
    """同步数据库中的设备名称与实际设备名称"""
    return await _sync_device_names(ip, db)

@router.post("/complete-ports")
async def complete_ports_with_prefix(db: Session = Depends(get_db)):
    """为同一(device_ip, device_index)组内的所有设备设置统一的端口号"""
    return await _complete_ports(db)

@router.get("/complete-ports")
async def complete_ports_get_with_prefix(db: Session = Depends(get_db)):
    """GET方法版本：为同一(device_ip, device_index)组内的所有设备设置统一的端口号"""
    return await _complete_ports(db)

# 不带前缀的路由 - 仅包含需要直接访问的端点

@router_no_prefix.post("/complete-ports")
async def complete_ports_direct(db: Session = Depends(get_db)):
    """直接访问版本：为同一(device_ip, device_index)组内的所有设备设置统一的端口号"""
    return await _complete_ports(db)

@router_no_prefix.get("/complete-ports")
async def complete_ports_get_direct(db: Session = Depends(get_db)):
    """直接访问GET方法版本：为同一(device_ip, device_index)组内的所有设备设置统一的端口号"""
    return await _complete_ports(db)

async def _fetch_devices_by_ip_route(
    ip: str,
    update_existing_only: bool,
    db: Session
):
    """从指定IP获取设备信息并更新数据库的实现"""
    http_status = fastapi_status
    if not ip or not ip.strip():
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="IP地址不能为空"
        )
    
    try:
        logger.info(f"开始从IP {ip} 获取设备信息...")
        logger.info("在刷新操作中禁用所有排他性规则，以确保API中的实际状态准确反映在数据库中")
        
        # 特别检查：解决特定设备问题
        special_device_name = "TwitterAutomation_073c_66545"
        special_device = db.query(models.DeviceUser).filter(
            models.DeviceUser.device_name == special_device_name
        ).first()
        
        if special_device:
            logger.info(f"【特别处理】发现特殊设备 {special_device_name}，当前状态: {special_device.status}")
            special_device.status = "offline"
            db.commit()
            logger.info(f"【特别处理】已将特殊设备 {special_device_name} 的状态临时设置为offline")
        
        base_url = os.environ.get("DEVICE_API_BASE_URL", "http://127.0.0.1:5000")
        logger.info(f"使用API基础URL: {base_url}, 设备IP: {ip}")
        
        # 测试API连接
        try:
            response = requests.get(f"{base_url}/", timeout=3)
            if response.status_code >= 400:
                logger.warning(f"API基础URL {base_url} 似乎无法访问，状态码: {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"API基础URL {base_url} 检查失败: {str(e)}")
        
        # 获取设备信息
        loop = asyncio.get_event_loop()
        try:
            results = await loop.run_in_executor(
                executor,
                fetch_devices_by_ip,
                base_url,
                ip
            )
        except Exception as e:
            logger.error(f"执行fetch_devices_by_ip函数失败: {str(e)}")
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"获取设备信息失败: {str(e)}"
            )
        
        device_count = len(results) if results else 0
        logger.info(f"从IP {ip} 获取到 {device_count} 个设备")
        
        updated_count = 0
        created_count = 0
        assigned_u2_ports_for_this_ip_in_session = set()
        assigned_myt_ports_for_this_ip_in_session = set()

        if device_count > 0:
            try:
                running_devices = [d for d in results if d.get("status", "").lower() == "running"]
                logger.info(f"运行中的设备数量: {len(running_devices)}/{device_count}")
                
                for device in results:
                    device_name = device.get("name")
                    device_ip = device.get("ip")
                    u2_port = device.get("adb_port")
                    myt_rpc_port = device.get("rpc_port")
                    device_index = device.get("index")
                    device_status = device.get("status", "unknown")
                    
                    # 如果设备名称为空或太短，生成一个唯一名称
                    if not device_name or len(device_name) < 3:
                        device_name = f"device-{uuid.uuid4().hex[:8]}"
                    
                    # 设置设备状态
                    is_online = device_status.lower() in ["running"]
                    is_starting = device_status.lower() in ["created", "restarting"]
                    
                    if is_online:
                        status_value = "online"
                    elif is_starting and device.get("should_treat_created_as_online", False):
                        status_value = "online"
                        logger.info(f"Device '{device_name}' is in '{device_status}' state but treated as online per API hint")
                    else:
                        status_value = "offline"
                    
                    logger.info(f"Device '{device_name}' API status: '{device_status}', mapped status: '{status_value}', device_index: {device_index}")
                    
                    # 检查是否有同名设备
                    existing_device = db.query(models.DeviceUser).filter(
                        models.DeviceUser.device_name == device_name
                    ).first()
                    
                    u2_port_from_api = device.get("adb_port")
                    myt_rpc_port_from_api = device.get("rpc_port")
                    logger.info(f"Device {device_name}: Retrieved u2_port_from_api: {u2_port_from_api}, myt_rpc_port_from_api: {myt_rpc_port_from_api}")

                    if existing_device:
                        logger.info(f"【诊断】找到现有设备记录: {device_name}, 当前DB状态={existing_device.status}, API状态={status_value}")
                        
                        # 更新现有设备
                        _update_existing_device(
                            existing_device, device, ip, status_value,
                            u2_port_from_api, myt_rpc_port_from_api,
                            device_index, db,
                            assigned_u2_ports_for_this_ip_in_session,
                            assigned_myt_ports_for_this_ip_in_session
                        )
                        
                        updated_count += 1
                    else:
                        # 如果只更新现有设备，跳过创建新设备
                        if update_existing_only:
                            logger.info(f"Skipping creation of new device {device_name} because update_existing_only is true.")
                            continue
                        
                        # 创建新设备
                        if _create_new_device(
                            device_name, device_ip or ip, ip, status_value,
                            u2_port_from_api, myt_rpc_port_from_api,
                            device_index, db,
                            assigned_u2_ports_for_this_ip_in_session,
                            assigned_myt_ports_for_this_ip_in_session
                        ):
                            created_count += 1
                
                # 提交更改
                try:
                    db.commit()
                    logger.info(f"数据库更新完成，更新: {updated_count}，创建: {created_count}")
                    
                    # 清理缓存
                    clear_device_cache()
                    
                    # 验证更新结果
                    _verify_sync_results(ip, results, db)
                    
                except Exception as commit_err:
                    db.rollback()
                    logger.error(f"数据库提交时发生错误: {str(commit_err)}", exc_info=True)
                    raise
                    
            except SQLAlchemyError as sql_err:
                db.rollback()
                logger.error(f"更新数据库时出错: {str(sql_err)}", exc_info=True)
                raise
            except Exception as gen_err:
                db.rollback()
                logger.error(f"更新数据库时出现错误: {str(gen_err)}", exc_info=True)
                raise
        
        # 准备返回结果
        messages = []
        if results:
            running_count = 0
            for device in results:
                device_name = device.get("name", "未知设备")
                status = device.get("status", "未知状态")
                if status.lower() == "running":
                    messages.append(f"设备: {device_name}, 状态: {status} (在线)")
                    running_count += 1
                else:
                    messages.append(f"设备: {device_name}, 状态: {status} (离线)")
            
            result_message = f"成功从IP {ip} 获取到 {device_count} 个设备，其中 {running_count} 个运行中"
            if created_count > 0 or updated_count > 0:
                result_message += f"，已添加/更新 {created_count + updated_count} 个设备到数据库"
        else:
            result_message = f"未从IP {ip} 获取到任何设备"
        
        return {
            "success": True,
            "count": device_count,
            "running_count": len([d for d in results if d.get("status", "").lower() == "running"]),
            "messages": messages,
            "message": result_message,
            "db_updated": updated_count,
            "db_created": created_count
        }
        
    except Exception as e:
        logger.error(f"从IP {ip} 获取设备信息失败: {str(e)}")
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取设备信息失败: {str(e)}"
        )

async def _sync_device_names(ip: str, db: Session):
    """同步数据库中的设备名称与实际设备名称的实现"""
    if not ip or not ip.strip():
        raise HTTPException(
            status_code=fastapi_status.HTTP_400_BAD_REQUEST,
            detail="IP地址不能为空"
        )
    
    try:
        logger.info(f"开始从IP {ip} 同步设备名称...")
        
        # 获取API基础URL
        base_url = os.environ.get("DEVICE_API_BASE_URL", "http://127.0.0.1:5000")
        
        # 获取设备列表
        api_url = f"{base_url}/dc_api/v1/list/{ip}"
        logger.info(f"获取设备列表: {api_url}")
        
        try:
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            devices_data = response.json()
            
            # 处理不同的API响应格式
            devices = []
            if isinstance(devices_data, dict):
                if "data" in devices_data and isinstance(devices_data["data"], list):
                    devices = devices_data["data"]
                elif "msg" in devices_data and isinstance(devices_data["msg"], list):
                    devices = devices_data["msg"]
            
            if not devices:
                logger.warning(f"从API获取的设备列表为空: {devices_data}")
                return {"success": False, "message": "设备列表为空", "updated": 0}
            
            logger.info(f"找到 {len(devices)} 个设备")
            
            # 获取数据库中的设备记录
            db_devices = db.query(models.DeviceUser).filter(models.DeviceUser.box_ip == ip).all()
            logger.info(f"数据库中找到 {len(db_devices)} 个相关设备记录")
            
            # 创建映射
            devices_by_index = {d.device_index: d for d in db_devices if d.device_index is not None}
            devices_by_name = {d.device_name: d for d in db_devices}
            
            # 更新设备名称
            updated_count = 0
            for device in devices:
                device_name = device.get("name")
                device_index = device.get("index")
                
                if not device_name:
                    logger.warning(f"设备缺少名称: {device}")
                    continue
                
                # 尝试匹配设备
                db_device = None
                if device_index is not None:
                    db_device = devices_by_index.get(device_index)
                
                if not db_device:
                    # 通过名称前缀匹配
                    current_name_parts = device_name.rsplit('_', 1)
                    base_name = current_name_parts[0] if len(current_name_parts) > 1 else device_name
                    
                    for old_name, old_device in devices_by_name.items():
                        if old_name.startswith(base_name) or device_name.startswith(old_name.rsplit('_', 1)[0]):
                            logger.info(f"通过名称前缀匹配到设备: 新名称={device_name}, 旧名称={old_name}")
                            db_device = old_device
                            break
                
                # 更新设备名称
                if db_device:
                    if db_device.device_name != device_name:
                        old_name = db_device.device_name
                        db_device.device_name = device_name
                        logger.info(f"更新设备名称: '{old_name}' -> '{device_name}'")
                        updated_count += 1
                else:
                    logger.warning(f"未找到与 '{device_name}' 匹配的设备记录")
            
            # 提交更改
            db.commit()
            
            return {
                "success": True,
                "message": f"成功同步 {updated_count} 个设备名称",
                "updated": updated_count
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"请求设备列表失败: {str(e)}")
            raise HTTPException(
                status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"请求设备列表失败: {str(e)}"
            )
            
    except Exception as e:
        logger.error(f"同步设备名称时出错: {str(e)}")
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"同步设备名称时出错: {str(e)}"
        )

async def _complete_ports(db: Session):
    """为同一(device_ip, device_index)组内的所有设备设置统一的端口号"""
    try:
        logger.info("端口统一化操作：开始执行...")
        updated_group_count = 0

        # 获取所有具有device_ip和device_index的设备
        all_devices_with_index = db.query(models.DeviceUser).filter(
            models.DeviceUser.device_ip.isnot(None),
            models.DeviceUser.device_index.isnot(None)
        ).all()

        # 按 (device_ip, device_index) 分组
        grouped_devices = {}
        for device in all_devices_with_index:
            key = (device.device_ip, device.device_index)
            if key not in grouped_devices:
                grouped_devices[key] = []
            grouped_devices[key].append(device)

        logger.info(f"端口统一化操作：找到 {len(grouped_devices)} 个设备组进行处理。")

        for key, device_group in grouped_devices.items():
            device_ip, device_index = key
            online_device_in_group = None
            
            # 查找在线设备作为参考
            for device_in_current_group_check in device_group:
                if (device_in_current_group_check.status == 'online' and 
                    device_in_current_group_check.u2_port is not None and 
                    device_in_current_group_check.myt_rpc_port is not None):
                    online_device_in_group = device_in_current_group_check
                    break
            
            if online_device_in_group:
                master_u2_port = online_device_in_group.u2_port
                master_myt_rpc_port = online_device_in_group.myt_rpc_port
                group_updated_this_iteration = False

                logger.info(f"端口统一化操作：组 ({device_ip}, 实例位 {device_index}) - 使用在线设备 '{online_device_in_group.device_name}' 的端口")

                for device_to_update in device_group:
                    changed_u2 = False
                    changed_myt = False
                    
                    if device_to_update.u2_port != master_u2_port:
                        logger.info(f"  设备 '{device_to_update.device_name}': U2端口更新为 {master_u2_port}")
                        device_to_update.u2_port = master_u2_port
                        changed_u2 = True
                    
                    if device_to_update.myt_rpc_port != master_myt_rpc_port:
                        logger.info(f"  设备 '{device_to_update.device_name}': MYT RPC端口更新为 {master_myt_rpc_port}")
                        device_to_update.myt_rpc_port = master_myt_rpc_port
                        changed_myt = True
                    
                    if changed_u2 or changed_myt:
                        group_updated_this_iteration = True
                        db.add(device_to_update)
                
                if group_updated_this_iteration:
                    updated_group_count += 1
            else:
                logger.info(f"端口统一化操作：组 ({device_ip}, 实例位 {device_index}) - 未找到具有有效端口的在线设备")

        if updated_group_count > 0:
            logger.info(f"端口统一化操作：准备提交数据库更改。总共 {updated_group_count} 个设备组中有设备被更新。")
            db.commit()
            logger.info(f"端口统一化操作：数据库提交完成。")
        else:
            logger.info("端口统一化操作：未执行任何端口更新")

        return {
            "success": True,
            "message": f"端口统一化操作完成。处理了 {len(grouped_devices)} 个设备组，其中 {updated_group_count} 个组内的设备端口被统一设置。",
            "updated_group_count": updated_group_count
        }

    except Exception as e:
        db.rollback()
        logger.error(f"端口统一化操作过程中发生错误: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"端口统一化失败: {str(e)}")

# 辅助函数：更新现有设备
def _update_existing_device(existing_device, device_data, box_ip, status_value,
                           u2_port_from_api, myt_rpc_port_from_api,
                           device_index, db, 
                           assigned_u2_ports_session, assigned_myt_ports_session):
    """更新现有设备的信息"""
    original_db_device_ip = existing_device.device_ip
    api_provided_device_ip = device_data.get("ip")

    ip_changed = False
    if api_provided_device_ip and api_provided_device_ip != original_db_device_ip:
        logger.info(f"Device {existing_device.device_name}: device_ip changing from '{original_db_device_ip}' to '{api_provided_device_ip}'")
        existing_device.device_ip = api_provided_device_ip
        ip_changed = True
    
    current_target_device_ip = existing_device.device_ip
    
    # 更新设备状态
    existing_device.status = status_value

    if status_value == 'online':
        # 处理在线设备的端口更新
        _handle_online_device_ports(
            existing_device, current_target_device_ip,
            u2_port_from_api, myt_rpc_port_from_api,
            ip_changed, db,
            assigned_u2_ports_session, assigned_myt_ports_session
        )
    else:
        # 处理离线设备的端口更新
        _handle_offline_device_ports(
            existing_device, current_target_device_ip,
            u2_port_from_api, myt_rpc_port_from_api,
            device_index, db,
            assigned_u2_ports_session, assigned_myt_ports_session
        )
    
    # 更新其他字段
    if device_index is not None:
        existing_device.device_index = device_index
    existing_device.box_ip = box_ip

# 辅助函数：创建新设备
def _create_new_device(device_name, device_ip, box_ip, status_value,
                      u2_port_from_api, myt_rpc_port_from_api,
                      device_index, db,
                      assigned_u2_ports_session, assigned_myt_ports_session):
    """创建新设备记录"""
    logger.info(f"Creating new device: {device_name}, API Status: {status_value}")
    
    resolved_u2_port = None
    resolved_myt_rpc_port = None

    if status_value == 'online':
        # 处理在线设备的端口
        if u2_port_from_api is not None:
            resolved_u2_port = u2_port_from_api
        else:
            logger.info(f"New device {device_name} is online, API gave no U2 port. Finding unused U2 port.")
            resolved_u2_port = find_unused_port(db, 'u2_port', 5001, device_ip, assigned_u2_ports_session)
        
        if resolved_u2_port is not None:
            assigned_u2_ports_session.add(resolved_u2_port)

        if myt_rpc_port_from_api is not None:
            resolved_myt_rpc_port = myt_rpc_port_from_api
        else:
            logger.info(f"New device {device_name} is online, API gave no MYT RPC port. Finding unused MYT RPC port.")
            resolved_myt_rpc_port = find_unused_port(db, 'myt_rpc_port', 11001, device_ip, assigned_myt_ports_session)
        
        if resolved_myt_rpc_port is not None:
            assigned_myt_ports_session.add(resolved_myt_rpc_port)
    
    try:
        # 检查端口冲突
        if status_value == 'online':
            if resolved_u2_port is not None:
                u2_conflict = db.query(models.DeviceUser).filter(
                    models.DeviceUser.device_ip == device_ip,
                    models.DeviceUser.u2_port == resolved_u2_port
                ).first()
                
                if u2_conflict:
                    logger.warning(f"Duplicate device_ip + u2_port conflict detected for new device {device_name}")
                    # 更新现有设备而不是创建新设备
                    u2_conflict.device_name = device_name
                    u2_conflict.status = status_value
                    if device_index is not None:
                        u2_conflict.device_index = device_index
                    u2_conflict.box_ip = box_ip
                    return True
            
            if resolved_myt_rpc_port is not None:
                myt_conflict = db.query(models.DeviceUser).filter(
                    models.DeviceUser.device_ip == device_ip,
                    models.DeviceUser.myt_rpc_port == resolved_myt_rpc_port
                ).first()
                
                if myt_conflict:
                    logger.warning(f"Duplicate device_ip + myt_rpc_port conflict detected for new device {device_name}")
                    myt_conflict.device_name = device_name
                    myt_conflict.status = status_value
                    if device_index is not None:
                        myt_conflict.device_index = device_index
                    myt_conflict.box_ip = box_ip
                    return True
        
        # 创建新设备
        new_device = models.DeviceUser(
            device_name=device_name,
            device_ip=device_ip,
            box_ip=box_ip,
            u2_port=resolved_u2_port,
            myt_rpc_port=resolved_myt_rpc_port,
            device_index=device_index,
            status=status_value
        )
        db.add(new_device)
        return True
        
    except Exception as e:
        logger.error(f"创建设备记录时内部出错: {str(e)}", exc_info=True)
        return False

# 辅助函数：处理在线设备端口
def _handle_online_device_ports(device, device_ip, u2_port_api, myt_port_api,
                               ip_changed, db, u2_ports_session, myt_ports_session):
    """处理在线设备的端口分配"""
    # U2端口处理
    if u2_port_api is not None:
        if device.u2_port != u2_port_api or ip_changed:
            conflict_db_u2 = db.query(models.DeviceUser.id).filter(
                models.DeviceUser.device_ip == device_ip,
                models.DeviceUser.u2_port == u2_port_api,
                models.DeviceUser.id != device.id
            ).first()
            conflict_session_u2 = u2_port_api in u2_ports_session
            
            if conflict_db_u2 or conflict_session_u2:
                logger.warning(f"U2 port conflict for {device.device_name}: port {u2_port_api} is already in use")
                if device.u2_port is None:
                    new_u2_port = find_unused_port(db, 'u2_port', 5001, device_ip, u2_ports_session)
                    if new_u2_port:
                        device.u2_port = new_u2_port
            else:
                device.u2_port = u2_port_api
    elif device.u2_port is None:
        new_u2_port = find_unused_port(db, 'u2_port', 5001, device_ip, u2_ports_session)
        if new_u2_port:
            device.u2_port = new_u2_port
    
    if device.u2_port is not None:
        u2_ports_session.add(device.u2_port)

    # MYT RPC端口处理
    if myt_port_api is not None:
        if device.myt_rpc_port != myt_port_api or ip_changed:
            conflict_db_myt = db.query(models.DeviceUser.id).filter(
                models.DeviceUser.device_ip == device_ip,
                models.DeviceUser.myt_rpc_port == myt_port_api,
                models.DeviceUser.id != device.id
            ).first()
            conflict_session_myt = myt_port_api in myt_ports_session
            
            if conflict_db_myt or conflict_session_myt:
                logger.warning(f"MYT RPC port conflict for {device.device_name}: port {myt_port_api} is already in use")
                if device.myt_rpc_port is None:
                    new_myt_port = find_unused_port(db, 'myt_rpc_port', 11001, device_ip, myt_ports_session)
                    if new_myt_port:
                        device.myt_rpc_port = new_myt_port
            else:
                device.myt_rpc_port = myt_port_api
    elif device.myt_rpc_port is None:
        new_myt_port = find_unused_port(db, 'myt_rpc_port', 11001, device_ip, myt_ports_session)
        if new_myt_port:
            device.myt_rpc_port = new_myt_port
    
    if device.myt_rpc_port is not None:
        myt_ports_session.add(device.myt_rpc_port)

# 辅助函数：处理离线设备端口
def _handle_offline_device_ports(device, device_ip, u2_port_api, myt_port_api,
                                device_index, db, u2_ports_session, myt_ports_session):
    """处理离线设备的端口分配"""
    logger.info(f"Device {device.device_name} is offline according to API.")
    
    online_counterpart = None
    if device.device_index is not None and device_ip is not None:
        online_counterpart = db.query(models.DeviceUser).filter(
            models.DeviceUser.device_ip == device_ip,
            models.DeviceUser.device_index == device.device_index,
            models.DeviceUser.status == 'online',
            models.DeviceUser.id != device.id,
            models.DeviceUser.u2_port.isnot(None),
            models.DeviceUser.myt_rpc_port.isnot(None)
        ).first()

    if online_counterpart:
        logger.info(f"  Offline device {device.device_name} has online counterpart {online_counterpart.device_name}")
        
        if online_counterpart.u2_port is not None and device.u2_port != online_counterpart.u2_port:
            logger.info(f"    {device.device_name}: U2 port mirroring from {online_counterpart.device_name}")
            device.u2_port = online_counterpart.u2_port
        
        if online_counterpart.myt_rpc_port is not None and device.myt_rpc_port != online_counterpart.myt_rpc_port:
            logger.info(f"    {device.device_name}: MYT port mirroring from {online_counterpart.device_name}")
            device.myt_rpc_port = online_counterpart.myt_rpc_port

        if device.u2_port is not None:
            u2_ports_session.add(device.u2_port)
        if device.myt_rpc_port is not None:
            myt_ports_session.add(device.myt_rpc_port)
    else:
        # 标准离线端口逻辑
        if u2_port_api is not None and device.u2_port is None:
            conflict_db_u2 = db.query(models.DeviceUser.id).filter(
                models.DeviceUser.device_ip == device_ip,
                models.DeviceUser.u2_port == u2_port_api,
                models.DeviceUser.id != device.id
            ).first()
            conflict_session_u2 = u2_port_api in u2_ports_session
            
            if not (conflict_db_u2 or conflict_session_u2):
                device.u2_port = u2_port_api
                u2_ports_session.add(device.u2_port)
        elif device.u2_port is not None:
            u2_ports_session.add(device.u2_port)

        if myt_port_api is not None and device.myt_rpc_port is None:
            conflict_db_myt = db.query(models.DeviceUser.id).filter(
                models.DeviceUser.device_ip == device_ip,
                models.DeviceUser.myt_rpc_port == myt_port_api,
                models.DeviceUser.id != device.id
            ).first()
            conflict_session_myt = myt_port_api in myt_ports_session
            
            if not (conflict_db_myt or conflict_session_myt):
                device.myt_rpc_port = myt_port_api
                myt_ports_session.add(device.myt_rpc_port)
        elif device.myt_rpc_port is not None:
            myt_ports_session.add(device.myt_rpc_port)

# 辅助函数：验证同步结果
def _verify_sync_results(ip, api_results, db):
    """验证API中的运行设备是否在数据库中正确标记为在线"""
    # 记录API中运行的设备
    running_devices_from_api = [d.get("name") for d in api_results if d.get("status", "").lower() == "running"]
    logger.info(f"【诊断】API中running的设备: {running_devices_from_api}")
    
    # 查询数据库中的设备
    all_devices_after_update = db.query(models.DeviceUser).filter(
        models.DeviceUser.box_ip == ip
    ).all()
    
    online_devices_in_db = []
    for device in all_devices_after_update:
        logger.info(f"设备 {device.device_name} (ID: {device.id}): 状态={device.status}, 索引={device.device_index}")
        if device.status == 'online':
            online_devices_in_db.append(device.device_name)
    
    # 检查差异
    missing_online_devices = set(running_devices_from_api) - set(online_devices_in_db)
    if missing_online_devices:
        logger.error(f"【诊断】存在差异! API中running但DB中不是online的设备: {missing_online_devices}")
        
        # 尝试修复差异
        for missing_device_name in missing_online_devices:
            _try_fix_device_status(missing_device_name, api_results, db)
    else:
        logger.info("【最终验证】所有API中running的设备在DB中都已正确标记为online")

# 辅助函数：尝试修复设备状态
def _try_fix_device_status(device_name, api_results, db):
    """尝试修复设备状态不一致的问题"""
    missing_device = db.query(models.DeviceUser).filter(
        models.DeviceUser.device_name == device_name
    ).first()
    
    if missing_device:
        logger.error(f"【诊断】数据库中存在设备 {device_name} 但状态为 {missing_device.status}")
        
        try:
            logger.info(f"【修复】尝试强制将设备 {device_name} 的状态更新为online")
            
            # 从API结果中获取设备信息
            device_from_api = next((d for d in api_results if d.get("name") == device_name), None)
            if device_from_api:
                # 更新设备状态和端口
                missing_device.status = "online"
                
                # 从API数据中提取端口信息
                if "ADB" in device_from_api and device_from_api["ADB"]:
                    port_str = device_from_api["ADB"].split(":")[-1]
                    if port_str.isdigit():
                        missing_device.u2_port = int(port_str)
                
                if "RPC" in device_from_api and device_from_api["RPC"]:
                    port_str = device_from_api["RPC"].split(":")[-1]
                    if port_str.isdigit():
                        missing_device.myt_rpc_port = int(port_str)
                
                db.add(missing_device)
                db.commit()
                logger.info(f"【修复】成功将设备 {device_name} 更新为online状态")
            else:
                logger.error(f"【修复】无法在API结果中找到设备 {device_name} 的详细信息")
        except Exception as update_err:
            db.rollback()
            logger.error(f"【修复】强制更新设备 {device_name} 状态时出错: {str(update_err)}", exc_info=True)
    else:
        logger.error(f"【诊断】数据库中不存在设备 {device_name}") 