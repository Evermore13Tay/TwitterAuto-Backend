"""
设备容器控制操作路由
包含启动、停止容器的功能
"""
import logging
import asyncio
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException, status as fastapi_status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from db.database import get_db
from db import models
from schemas.models import DeviceUser
from automation.BoxManipulate import call_stop_api, call_reboot_api
from suspended_account import SuspendedAccount

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/devices", tags=["device-container"])

# 线程池执行器
executor = ThreadPoolExecutor(max_workers=5)

@router.post("/{device_id}/close", response_model=DeviceUser)
async def close_device_container(
    device_id: str,
    db: Session = Depends(get_db)
):
    """关闭指定设备的容器并将其状态更新为离线，但保留端口配置"""
    try:
        device_user = db.query(models.DeviceUser).filter(models.DeviceUser.id == device_id).first()
        if not device_user:
            raise HTTPException(status_code=404, detail=f"Device with ID {device_id} not found")
        
        original_status = device_user.status
        
        # 如果设备已经是离线状态，直接返回
        if device_user.status == 'offline':
            logger.info(f"Device {device_user.device_name} (ID: {device_id}) is already offline.")
            
            # 检查用户是否被封号
            is_suspended = _check_user_suspended(device_user.username, db)
            
            return DeviceUser.model_validate({
                "id": device_user.id,
                "device_ip": device_user.device_ip,
                "box_ip": device_user.box_ip,
                "u2_port": device_user.u2_port,
                "myt_rpc_port": device_user.myt_rpc_port,
                "username": device_user.username,
                "password": device_user.password,
                "secret_key": device_user.secret_key,
                "device_name": device_user.device_name,
                "device_index": device_user.device_index,
                "status": device_user.status,
                "proxy": None,
                "is_suspended": is_suspended
            })
        
        # 尝试关闭容器
        try:
            logger.info(f"[DeviceContainer] close_device_container for ID: {device_user.id}, Name: {device_user.device_name}")
            logger.info(f"Attempting to stop container {device_user.device_name} on host {device_user.box_ip}")
            
            loop = asyncio.get_event_loop()
            encoded_device_name = urllib.parse.quote(device_user.device_name)
            logger.info(f"URL-encoded device name for stop API: {encoded_device_name}")
            
            success = await loop.run_in_executor(
                executor,
                call_stop_api, 
                device_user.box_ip,
                encoded_device_name
            )
            
            if success:
                logger.info(f"Successfully stopped container {device_user.device_name} via call_stop_api")
                device_user.status = 'offline'
            else:
                logger.warning(f"call_stop_api failed for container {device_user.device_name}")
                # 即使API调用失败，根据现有逻辑，我们也将状态设置为离线
                device_user.status = 'offline'
                logger.info(f"Setting device {device_user.device_name} status to 'offline' despite call_stop_api failure.")

        except Exception as e:
            logger.error(f"Error calling call_stop_api for device {device_user.device_name}: {str(e)}")
            # 即使发生错误，根据现有逻辑，我们也将状态设置为离线
            device_user.status = 'offline'
            logger.info(f"Setting device {device_user.device_name} status to 'offline' due to error during stop operation.")
            
    except Exception as e:
        logger.error(f"Unexpected error during stop operation for device {device_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )
    
    if device_user.status != original_status:
        try:
            db.commit()
            db.refresh(device_user)
            logger.info(f"Device {device_user.device_name} (ID: {device_id}) status updated to {device_user.status}")
        except SQLAlchemyError as db_err:
            db.rollback()
            logger.error(f"Database error while updating device status after stop: {str(db_err)}")
            device_user.status = original_status 
            raise HTTPException(status_code=500, detail=f"DB error updating status: {str(db_err)}")

    # 检查用户是否被封号
    is_suspended = _check_user_suspended(device_user.username, db)

    return DeviceUser.model_validate({
        "id": device_user.id,
        "device_ip": device_user.device_ip,
        "box_ip": device_user.box_ip,
        "u2_port": device_user.u2_port,
        "myt_rpc_port": device_user.myt_rpc_port,
        "username": device_user.username,
        "password": device_user.password,
        "secret_key": device_user.secret_key,
        "device_name": device_user.device_name,
        "device_index": device_user.device_index,
        "status": device_user.status,
        "proxy": None,
        "is_suspended": is_suspended
    })

@router.post("/{device_id}/start")
async def start_device_container(
    device_id: str,
    db: Session = Depends(get_db)
):
    """启动 (重启) 指定设备的容器并将其状态更新为在线"""
    try:
        device_user = db.query(models.DeviceUser).filter(models.DeviceUser.id == device_id).first()
        if not device_user:
            raise HTTPException(status_code=404, detail=f"Device with ID {device_id} not found")
        
        original_status = device_user.status
        
        if device_user.status == 'online':
            logger.info(f"Device {device_user.device_name} (ID: {device_id}) is already online. Performing reboot.")
        
        try:
            logger.info(f"[DeviceContainer] start_device_container for ID: {device_user.id}, Name: {device_user.device_name}")
            logger.info(f"Attempting to reboot container {device_user.device_name} on host {device_user.box_ip}")
            
            loop = asyncio.get_event_loop()
            encoded_device_name = urllib.parse.quote(device_user.device_name)
            logger.info(f"URL-encoded device name for reboot API: {encoded_device_name}")
            
            success = await loop.run_in_executor(
                executor, 
                call_reboot_api,
                device_user.box_ip,
                encoded_device_name
            )
            
            if success:
                logger.info(f"Successfully sent reboot command for container {device_user.device_name}")
                device_user.status = 'online'
            else:
                logger.warning(f"call_reboot_api failed for container {device_user.device_name}. Setting status to online as fallback.")
                device_user.status = 'online' 

        except Exception as e:
            logger.error(f"Error calling call_reboot_api for device {device_user.device_name}: {str(e)}")
            device_user.status = 'online'
            logger.info(f"Setting device {device_user.device_name} status to 'online' due to error during reboot operation.")
            
    except Exception as e:
        logger.error(f"Unexpected error during start/reboot operation for device {device_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=fastapi_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}"
        )
    
    if device_user.status != original_status or original_status == 'offline':
        try:
            db.commit()
            db.refresh(device_user)
            logger.info(f"Device {device_user.device_name} (ID: {device_id}) status is now {device_user.status}")
        except SQLAlchemyError as db_err:
            db.rollback()
            logger.error(f"Database error while updating device status after reboot: {str(db_err)}")
            raise HTTPException(status_code=500, detail=f"DB error updating status: {str(db_err)}")

    # 检查用户是否被封号
    is_suspended = _check_user_suspended(device_user.username, db)

    return DeviceUser.model_validate({
        "id": device_user.id,
        "device_ip": device_user.device_ip,
        "box_ip": device_user.box_ip,
        "u2_port": device_user.u2_port,
        "myt_rpc_port": device_user.myt_rpc_port,
        "username": device_user.username,
        "password": device_user.password,
        "secret_key": device_user.secret_key,
        "device_name": device_user.device_name,
        "device_index": device_user.device_index,
        "status": device_user.status,
        "proxy": None,
        "is_suspended": is_suspended
    })

def _check_user_suspended(username: str, db: Session) -> bool:
    """检查用户是否被封号"""
    if not username:
        return False
    
    suspended_account = db.query(SuspendedAccount).filter(
        SuspendedAccount.username == username
    ).first()
    
    return suspended_account is not None 