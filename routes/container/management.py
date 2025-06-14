"""
容器管理路由
包含容器导入和其他常规管理功能
"""
import logging
import os
import shutil
import concurrent.futures
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Body, BackgroundTasks
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import DeviceUser
from automation.BoxManipulate import call_import_api

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)

router = APIRouter(tags=["container-management"])

# 线程池执行器
executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)

@router.post("/import-container")
async def import_container(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    device_id: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    导入容器
    将上传的容器文件导入到指定设备
    """
    try:
        # 获取设备信息
        device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")
            
        if not device.device_ip:
            raise HTTPException(status_code=400, detail="设备IP地址不可用")
            
        # 创建临时目录存储上传的文件
        temp_dir = os.path.join(os.getcwd(), "temp_import")
        os.makedirs(temp_dir, exist_ok=True)
        
        file_path = os.path.join(temp_dir, file.filename)
        
        # 保存上传的文件
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"文件已上传到 {file_path}，准备导入到设备 {device.device_name}")
        
        # 在后台任务中执行导入操作
        background_tasks.add_task(
            _import_container_background,
            device_ip=device.device_ip,
            device_name=device.device_name,
            file_path=file_path
        )
        
        return {
            "success": True,
            "message": f"已开始导入容器到设备 {device.device_name}，请稍后检查导入状态",
            "device_name": device.device_name,
            "file_name": file.filename
        }
        
    except Exception as e:
        logger.error(f"导入容器时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导入容器时出错: {str(e)}")

@router.post("/batch-import")
async def batch_import_containers(
    background_tasks: BackgroundTasks,
    import_data: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """
    批量导入容器
    将多个容器文件导入到多个设备
    
    参数:
    import_data: 包含imports列表的字典，每个元素包含device_id和file_path
    """
    try:
        imports = import_data.get("imports", [])
        if not imports:
            raise HTTPException(status_code=400, detail="未提供导入任务")
            
        results = []
        for import_task in imports:
            device_id = import_task.get("device_id")
            file_path = import_task.get("file_path")
            
            if not device_id or not file_path:
                results.append({
                    "success": False,
                    "message": "设备ID或文件路径缺失",
                    "device_id": device_id
                })
                continue
                
            # 检查文件是否存在
            if not os.path.exists(file_path):
                results.append({
                    "success": False,
                    "message": f"文件不存在: {file_path}",
                    "device_id": device_id
                })
                continue
                
            # 获取设备信息
            device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
            if not device:
                results.append({
                    "success": False,
                    "message": "设备不存在",
                    "device_id": device_id
                })
                continue
                
            if not device.device_ip:
                results.append({
                    "success": False,
                    "message": "设备IP地址不可用",
                    "device_id": device_id
                })
                continue
                
            # 在后台任务中执行导入操作
            background_tasks.add_task(
                _import_container_background,
                device_ip=device.device_ip,
                device_name=device.device_name,
                file_path=file_path
            )
            
            results.append({
                "success": True,
                "message": f"已开始导入容器到设备 {device.device_name}",
                "device_id": device_id,
                "device_name": device.device_name,
                "file_path": file_path
            })
            
        return {
            "success": True,
            "message": f"已提交 {len(results)} 个导入任务",
            "results": results
        }
        
    except Exception as e:
        logger.error(f"批量导入容器时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"批量导入容器时出错: {str(e)}")

# 后台任务函数
def _import_container_background(device_ip: str, device_name: str, file_path: str):
    """
    在后台执行容器导入
    
    参数:
    device_ip: 设备IP
    device_name: 设备名称
    file_path: 导入文件路径
    """
    try:
        logger.info(f"开始导入容器到设备 {device_name}，IP: {device_ip}，文件: {file_path}")
        
        # 调用导入API
        success = call_import_api(
            ip_address=device_ip,
            name=device_name,
            local_path=file_path
        )
        
        if success:
            logger.info(f"成功导入容器到设备 {device_name}")
        else:
            logger.error(f"导入容器到设备 {device_name} 失败")
            
        # 清理临时文件
        if "temp_import" in file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"已删除临时文件: {file_path}")
            except Exception as e:
                logger.error(f"删除临时文件失败: {str(e)}")
                
    except Exception as e:
        logger.error(f"导入容器到设备 {device_name} 时出错: {str(e)}")

@router.get("/check-import-status")
async def check_import_status(
    device_name: str
):
    """
    检查容器导入状态
    这是一个示例接口，实际实现可能需要与具体的导入流程集成
    
    参数:
    device_name: 设备名称
    """
    # 注意：此函数为占位符，实际实现可能需要根据具体的容器API进行调整
    try:
        logger.info(f"请求检查设备 {device_name} 的导入状态")
        
        # 这里应该实现实际的状态检查逻辑
        # 例如查询数据库或调用外部API
        
        # 当前返回模拟的状态信息
        return {
            "success": True,
            "device_name": device_name,
            "status": "completed",  # 可能的值: pending, importing, completed, failed
            "message": "容器导入已完成"
        }
        
    except Exception as e:
        logger.error(f"检查导入状态时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"检查导入状态时出错: {str(e)}") 