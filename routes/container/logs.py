"""
容器日志和监控模块
包含获取容器日志和监控容器状态的功能
"""
import logging
import time
import asyncio
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect, Query
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

router = APIRouter(tags=["container-logs"])

@router.get("/logs/{device_id}")
async def get_container_logs(
    device_id: str,
    lines: int = Query(100, description="要获取的日志行数"),
    db: Session = Depends(get_db)
):
    """
    获取指定设备的容器日志
    
    参数:
    device_id: 设备ID
    lines: 要获取的日志行数，默认100行
    """
    try:
        # 获取设备信息
        device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
            
        if not device.device_ip:
            raise HTTPException(status_code=400, detail="设备IP地址不可用")
            
        # 构建日志API URL
        logs_url = f"http://{device.device_ip}:5000/container_logs/{device.device_name}?lines={lines}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(logs_url, timeout=30) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"获取日志失败: {response_text}"
                        )
                        
                    logs_data = await response.json()
                    
                    return {
                        "success": True,
                        "device_name": device.device_name,
                        "logs": logs_data.get("logs", [])
                    }
                    
            except aiohttp.ClientError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"连接日志API失败: {str(e)}"
                )
                
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"获取容器日志时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取容器日志时出错: {str(e)}")

@router.websocket("/ws/logs/{device_id}")
async def websocket_logs(websocket: WebSocket, device_id: str, db: Session = Depends(get_db)):
    """
    通过WebSocket实时获取容器日志
    
    参数:
    websocket: WebSocket连接
    device_id: 设备ID
    """
    await websocket.accept()
    
    try:
        # 获取设备信息
        device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
        if not device:
            await websocket.send_json({"error": "设备不存在"})
            await websocket.close()
            return
            
        if not device.device_ip:
            await websocket.send_json({"error": "设备IP地址不可用"})
            await websocket.close()
            return
            
        logger.info(f"开始WebSocket日志流: 设备 {device.device_name}")
        
        # 发送初始日志数据
        initial_logs = await _fetch_container_logs(device.device_ip, device.device_name, 50)
        await websocket.send_json({
            "type": "initial",
            "device_name": device.device_name,
            "logs": initial_logs
        })
        
        # 持续发送日志更新
        last_line = initial_logs[-1] if initial_logs else ""
        while True:
            try:
                # 检查WebSocket是否仍然连接
                await websocket.receive_text()
                
                # 获取新日志
                new_logs = await _fetch_container_logs_since(device.device_ip, device.device_name, last_line)
                if new_logs:
                    await websocket.send_json({
                        "type": "update",
                        "logs": new_logs
                    })
                    last_line = new_logs[-1]
                
                # 等待一段时间再获取新日志
                await asyncio.sleep(2)
                
            except WebSocketDisconnect:
                logger.info(f"WebSocket连接断开: 设备 {device.device_name}")
                break
                
    except Exception as e:
        logger.error(f"WebSocket日志流出错: {str(e)}")
        try:
            await websocket.send_json({"error": f"获取日志出错: {str(e)}"})
            await websocket.close()
        except:
            pass

@router.get("/container-status/{device_id}")
async def get_container_status(
    device_id: str,
    db: Session = Depends(get_db)
):
    """
    获取容器状态信息
    
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
            
        # 构建状态API URL
        status_url = f"http://{device.device_ip}:5000/container_status/{device.device_name}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(status_url, timeout=10) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"获取状态失败: {response_text}"
                        )
                        
                    status_data = await response.json()
                    
                    return {
                        "success": True,
                        "device_name": device.device_name,
                        "status": status_data
                    }
                    
            except aiohttp.ClientError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"连接状态API失败: {str(e)}"
                )
                
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"获取容器状态时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取容器状态时出错: {str(e)}")

# 辅助函数：获取容器日志
async def _fetch_container_logs(device_ip: str, device_name: str, lines: int = 100) -> list:
    """获取指定设备的容器日志"""
    try:
        logs_url = f"http://{device_ip}:5000/container_logs/{device_name}?lines={lines}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(logs_url, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"获取日志失败，状态码: {response.status}")
                    return []
                    
                logs_data = await response.json()
                return logs_data.get("logs", [])
                
    except Exception as e:
        logger.error(f"获取容器日志出错: {str(e)}")
        return []

# 辅助函数：获取自指定行以来的新日志
async def _fetch_container_logs_since(device_ip: str, device_name: str, last_line: str) -> list:
    """获取自上次请求以来的新日志行"""
    # 注意：此函数是一个示例实现，实际实现可能需要根据API调整
    try:
        # 先获取较多的日志行
        all_logs = await _fetch_container_logs(device_ip, device_name, 200)
        
        if not all_logs or not last_line:
            return all_logs
            
        # 找到上次的最后一行的位置
        try:
            last_index = all_logs.index(last_line)
            # 返回新的日志行
            return all_logs[last_index+1:]
        except ValueError:
            # 如果找不到上次的最后一行，返回所有日志
            return all_logs
            
    except Exception as e:
        logger.error(f"获取新日志出错: {str(e)}")
        return [] 