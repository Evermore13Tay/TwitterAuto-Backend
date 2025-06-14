"""
容器重启模块
包含容器重启相关的功能
"""
import logging
import concurrent.futures
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from db.database import get_db, SessionLocal
from db import models
from automation.BoxManipulate import call_reboot_api

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)

router = APIRouter(tags=["container-reboot"])

# 创建线程池
executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

def reboot_single_container(device_id: str):
    """
    重启单个容器并返回结果，为每个操作创建独立的数据库会话
    
    参数:
    device_id: 设备ID
    """
    # 为每个线程创建新的数据库会话
    db = SessionLocal()
    try:
        # 从数据库查询设备信息
        device = db.query(models.DeviceUser).filter(models.DeviceUser.id == device_id).first()
        
        if not device:
            return {"device_id": device_id, "success": False, "message": "设备不存在"}
            
        # 检查必要的字段
        if not device.device_ip or not device.device_name:
            return {"device_id": device_id, "success": False, 
                    "message": "设备缺少IP或名称信息"}
        
        logger.info(f"开始重启容器: {device.device_name}, IP: {device.device_ip}")
        
        # 调用重启API
        reboot_success = call_reboot_api(
            ip_address=device.device_ip,
            name=device.device_name
        )
        
        if reboot_success:
            logger.info(f"容器 {device.device_name} 重启成功")
            
            # 更新设备状态为在线
            device.status = 'online'
            db.commit()
            
            return {
                "device_id": device_id,
                "device_name": device.device_name,
                "device_ip": device.device_ip,
                "success": True,
                "message": "容器重启成功"
            }
        else:
            logger.error(f"容器 {device.device_name} 重启失败")
            return {
                "device_id": device_id,
                "device_name": device.device_name,
                "device_ip": device.device_ip,
                "success": False,
                "message": "容器重启失败"
            }
            
    except Exception as e:
        logger.error(f"重启容器时出错: {str(e)}")
        return {
            "device_id": device_id,
            "success": False,
            "message": f"重启容器时出错: {str(e)}"
        }
    finally:
        # 确保关闭数据库会话
        db.close()

@router.post("/reboot-containers")
async def reboot_containers(
    device_ids: List[str] = Body(..., description="要重启的设备ID列表")
):
    """
    批量重启容器
    
    参数:
    device_ids: 要重启的设备ID列表
    """
    logger.info(f"批量重启容器请求: {device_ids}")
    
    if not device_ids:
        raise HTTPException(status_code=400, detail="未提供设备ID")
    
    # 将任务提交到线程池
    futures = []
    for device_id in device_ids:
        future = executor.submit(reboot_single_container, device_id)
        futures.append(future)
    
    # 收集结果
    results = []
    for future in concurrent.futures.as_completed(futures):
        try:
            result = future.result()
            results.append(result)
        except Exception as e:
            logger.error(f"任务执行异常: {str(e)}")
            results.append({
                "device_id": "unknown",
                "success": False,
                "message": f"重启任务异常: {str(e)}"
            })
    
    # 汇总结果
    success_count = sum(1 for r in results if r.get("success", False))
    
    return {
        "success": success_count > 0,
        "message": f"已重启 {success_count}/{len(device_ids)} 个容器",
        "results": results
    }

@router.post("/reboot-container/{device_id}")
async def reboot_single_container_endpoint(
    device_id: str,
    db: Session = Depends(get_db)
):
    """
    重启单个容器
    
    参数:
    device_id: 设备ID
    """
    try:
        # 从数据库查询设备信息
        device = db.query(models.DeviceUser).filter(models.DeviceUser.id == device_id).first()
        
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
            
        # 检查必要的字段
        if not device.device_ip or not device.device_name:
            raise HTTPException(status_code=400, detail="设备缺少IP或名称信息")
        
        logger.info(f"重启单个容器: {device.device_name}, IP: {device.device_ip}")
        
        # 调用重启API
        reboot_success = call_reboot_api(
            ip_address=device.device_ip,
            name=device.device_name
        )
        
        if reboot_success:
            logger.info(f"容器 {device.device_name} 重启成功")
            
            # 更新设备状态为在线
            device.status = 'online'
            db.commit()
            
            return {
                "device_id": device_id,
                "device_name": device.device_name,
                "device_ip": device.device_ip,
                "success": True,
                "message": "容器重启成功"
            }
        else:
            logger.error(f"容器 {device.device_name} 重启失败")
            return {
                "device_id": device_id,
                "device_name": device.device_name,
                "device_ip": device.device_ip,
                "success": False,
                "message": "容器重启失败"
            }
            
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"重启容器时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重启容器时出错: {str(e)}") 