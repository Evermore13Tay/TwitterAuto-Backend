"""
设备代理设置路由
包含设置设备代理的功能
"""
import logging
import aiohttp
import time
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from db.database import get_db
from db import models

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

router = APIRouter(prefix="/api/devices", tags=["device-proxy"])

from pydantic import BaseModel

class ProxySettingsRequest(BaseModel):
    proxy_ip: str
    proxy_port: int
    language: str = "en"

@router.post("/{device_id}/save-proxy-settings")
async def save_proxy_settings(
    device_id: str,
    request: ProxySettingsRequest,
    db: Session = Depends(get_db)
):
    """保存代理和语言设置到数据库而不重启设备"""
    try:
        # 查找设备
        device = db.query(models.DeviceUser).filter(models.DeviceUser.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
            
        # 更新数据库中的代理和语言信息
        device.proxy_ip = request.proxy_ip
        device.proxy_port = request.proxy_port
        device.language = request.language
        db.commit()
        
        logger.info(f"Successfully saved proxy and language settings for device {device.device_name}")
        
        return {
            "success": True,
            "message": f"Successfully saved proxy and language settings for device {device.device_name}",
            "device_name": device.device_name,
            "proxy_ip": request.proxy_ip,
            "proxy_port": request.proxy_port,
            "language": request.language
        }
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error saving proxy settings: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save proxy settings: {str(e)}"
        )

@router.post("/{device_id}/set-proxy")
async def set_device_proxy(
    device_id: str,
    proxy: str = Query(..., description="代理地址"),
    db: Session = Depends(get_db)
):
    """设置设备代理并设置地区为英语"""
    try:
        # 查找设备
        device = db.query(models.DeviceUser).filter(models.DeviceUser.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        # 构建API URL
        base_url = f"http://{device.device_ip}:5000"
        proxy_url = f"{base_url}/set_proxy/{device.device_name}/{proxy}"
        location_url = f"{base_url}/set_ipLocation/{device.device_ip}/{device.device_name}/en"

        async with aiohttp.ClientSession() as session:
            # 设置代理
            try:
                async with session.get(proxy_url) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"Failed to set proxy: {response_text}"
                        )
                    logger.info(f"Successfully set proxy for device {device.device_name}")
            except aiohttp.ClientError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to connect to proxy setting endpoint: {str(e)}"
                )
            
            # 等待一段时间确保代理设置生效
            time.sleep(5)
            
            # 设置地区
            try:
                async with session.get(location_url) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"Failed to set location: {response_text}"
                        )
                    logger.info(f"Successfully set location for device {device.device_name}")
            except aiohttp.ClientError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to connect to location setting endpoint: {str(e)}"
                )

            # 重启设备
            restart_url = f"{base_url}/restart_container/{device.device_name}"
            try:
                async with session.get(restart_url) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"Failed to restart device: {response_text}"
                        )
                    logger.info(f"Successfully restarted device {device.device_name}")
            except aiohttp.ClientError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to connect to restart endpoint: {str(e)}"
                )

        # 更新数据库中的代理信息
        device.proxy = proxy
        db.commit()

        return {
            "success": True,
            "message": f"Successfully set proxy, location and restarted device {device.device_name}",
            "device_name": device.device_name,
            "proxy": proxy
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error setting proxy: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to set proxy: {str(e)}"
        ) 