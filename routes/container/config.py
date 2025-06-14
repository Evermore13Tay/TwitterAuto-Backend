"""
容器配置模块
包含容器的配置和设置功能
"""
import logging
import os
import json
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import DeviceUser
import aiohttp

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)

router = APIRouter(tags=["container-config"])

@router.get("/container-config/{device_id}")
async def get_container_config(
    device_id: str,
    db: Session = Depends(get_db)
):
    """
    获取容器配置信息
    
    参数:
    device_id: 设备ID
    """
    try:
        # 获取设备信息
        device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
            
        if not device.device_ip:
            raise HTTPException(status_code=400, detail="设备IP地址不可用")
            
        # 构建配置API URL
        config_url = f"http://{device.device_ip}:5000/container_config/{device.device_name}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(config_url, timeout=10) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"获取配置失败: {response_text}"
                        )
                        
                    config_data = await response.json()
                    
                    return {
                        "success": True,
                        "device_name": device.device_name,
                        "config": config_data
                    }
                    
            except aiohttp.ClientError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"连接配置API失败: {str(e)}"
                )
                
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"获取容器配置时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取容器配置时出错: {str(e)}")

@router.post("/container-config/{device_id}")
async def update_container_config(
    device_id: str,
    config: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """
    更新容器配置信息
    
    参数:
    device_id: 设备ID
    config: 要更新的配置信息
    """
    try:
        # 获取设备信息
        device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
            
        if not device.device_ip:
            raise HTTPException(status_code=400, detail="设备IP地址不可用")
            
        # 构建配置API URL
        config_url = f"http://{device.device_ip}:5000/update_config/{device.device_name}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    config_url, 
                    json=config,
                    timeout=30
                ) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"更新配置失败: {response_text}"
                        )
                        
                    result = await response.json()
                    
                    return {
                        "success": True,
                        "device_name": device.device_name,
                        "message": "容器配置已更新",
                        "result": result
                    }
                    
            except aiohttp.ClientError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"连接配置API失败: {str(e)}"
                )
                
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"更新容器配置时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新容器配置时出错: {str(e)}")

@router.get("/container-settings/{device_id}")
async def get_container_settings(
    device_id: str,
    db: Session = Depends(get_db)
):
    """
    获取容器设置信息
    
    参数:
    device_id: 设备ID
    """
    try:
        # 获取设备信息
        device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
            
        # 获取设置文件路径
        settings_dir = os.path.join(os.getcwd(), "container_settings")
        os.makedirs(settings_dir, exist_ok=True)
        
        settings_file = os.path.join(settings_dir, f"{device.id}.json")
        
        # 检查设置文件是否存在
        if not os.path.exists(settings_file):
            # 如果不存在，返回默认设置
            return {
                "success": True,
                "device_name": device.device_name,
                "settings": {
                    "auto_start": False,
                    "auto_export": False,
                    "export_interval": 86400,  # 默认每天导出一次
                    "max_exports": 5,  # 默认保留最近5次导出
                    "notification_enabled": False,
                    "custom_settings": {}
                }
            }
            
        # 读取设置文件
        try:
            with open(settings_file, "r") as f:
                settings = json.load(f)
                
            return {
                "success": True,
                "device_name": device.device_name,
                "settings": settings
            }
            
        except Exception as e:
            logger.error(f"读取设置文件时出错: {str(e)}")
            raise HTTPException(status_code=500, detail=f"读取设置文件时出错: {str(e)}")
            
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"获取容器设置时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取容器设置时出错: {str(e)}")

@router.post("/container-settings/{device_id}")
async def update_container_settings(
    device_id: str,
    settings: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """
    更新容器设置信息
    
    参数:
    device_id: 设备ID
    settings: 要更新的设置信息
    """
    try:
        # 获取设备信息
        device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
            
        # 获取设置文件路径
        settings_dir = os.path.join(os.getcwd(), "container_settings")
        os.makedirs(settings_dir, exist_ok=True)
        
        settings_file = os.path.join(settings_dir, f"{device.id}.json")
        
        # 保存设置文件
        try:
            with open(settings_file, "w") as f:
                json.dump(settings, f, indent=2)
                
            return {
                "success": True,
                "device_name": device.device_name,
                "message": "容器设置已更新"
            }
            
        except Exception as e:
            logger.error(f"保存设置文件时出错: {str(e)}")
            raise HTTPException(status_code=500, detail=f"保存设置文件时出错: {str(e)}")
            
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"更新容器设置时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新容器设置时出错: {str(e)}")

@router.post("/apply-settings/{device_id}")
async def apply_container_settings(
    device_id: str,
    db: Session = Depends(get_db)
):
    """
    应用容器设置
    将本地保存的设置应用到容器
    
    参数:
    device_id: 设备ID
    """
    try:
        # 获取设备信息
        device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
            
        if not device.device_ip:
            raise HTTPException(status_code=400, detail="设备IP地址不可用")
            
        # 获取设置文件路径
        settings_dir = os.path.join(os.getcwd(), "container_settings")
        settings_file = os.path.join(settings_dir, f"{device.id}.json")
        
        # 检查设置文件是否存在
        if not os.path.exists(settings_file):
            raise HTTPException(status_code=404, detail="容器设置不存在")
            
        # 读取设置文件
        try:
            with open(settings_file, "r") as f:
                settings = json.load(f)
        except Exception as e:
            logger.error(f"读取设置文件时出错: {str(e)}")
            raise HTTPException(status_code=500, detail=f"读取设置文件时出错: {str(e)}")
            
        # 构建应用设置API URL
        apply_url = f"http://{device.device_ip}:5000/apply_settings/{device.device_name}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    apply_url, 
                    json=settings,
                    timeout=30
                ) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"应用设置失败: {response_text}"
                        )
                        
                    result = await response.json()
                    
                    return {
                        "success": True,
                        "device_name": device.device_name,
                        "message": "容器设置已应用",
                        "result": result
                    }
                    
            except aiohttp.ClientError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"连接应用设置API失败: {str(e)}"
                )
                
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"应用容器设置时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"应用容器设置时出错: {str(e)}") 