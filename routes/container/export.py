"""
容器导出操作路由
包含容器导出相关的所有功能
"""
import logging
import os
import concurrent.futures
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.orm import Session
from db.database import SessionLocal
from db.models import DeviceUser
from automation.BoxManipulate import call_export_api, call_reboot_api

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)

router = APIRouter(tags=["container-export"])

# 备份文件存放目录
BACKUP_DIR = "D:/mytBackUp"

# 确保备份目录存在
os.makedirs(BACKUP_DIR, exist_ok=True)

# 创建线程池
executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

def export_single_container(device_id: str, save_path: str = None):
    """
    导出单个容器并返回结果，为每个操作创建独立的数据库会话
    导出成功后自动重启容器
    
    参数:
    device_id: 设备ID
    save_path: 用户指定的保存路径，如果为None则使用默认路径
    """
    # 为每个线程创建新的数据库会话
    db = SessionLocal()
    try:
        # 从数据库查询设备信息
        device = db.query(DeviceUser).filter(DeviceUser.id == device_id).first()
        
        if not device:
            return {"device_id": device_id, "success": False, "message": "设备不存在"}
            
        # 检查必要的字段
        if not device.device_ip or not device.device_name:
            return {"device_id": device_id, "success": False, 
                    "message": "设备缺少IP或名称信息"}
            
        # 构建导出文件路径
        username = device.username or "unknown_user"
        export_filename = f"{username}.tar.gz"
        
        # 使用用户指定的路径或默认路径
        backup_dir = save_path if save_path else BACKUP_DIR
        
        # 确保保存目录存在
        os.makedirs(backup_dir, exist_ok=True)
        
        export_path = os.path.join(backup_dir, export_filename)
        
        logger.info(f"导出设备: {device.device_name}, IP: {device.device_ip}, 路径: {export_path}")
        
        # 调用导出API
        export_success = call_export_api(
            ip_address=device.device_ip,
            name=device.device_name,
            local_path=export_path
        )
        
        if export_success:
            logger.info(f"导出成功: {device.device_name}")
            # 验证文件是否存在和大小
            if os.path.exists(export_path):
                file_size = os.path.getsize(export_path)
                logger.info(f"设备 {device.device_name} 最终导出文件大小: {file_size} 字节")
                
                if file_size < 10000:
                    logger.warning(f"警告: 设备 {device.device_name} 导出文件过小 ({file_size} 字节)")
            else:
                logger.error(f"错误: 设备 {device.device_name} 导出文件不存在")
                return {
                    "device_id": device_id,
                    "device_name": device.device_name,
                    "device_ip": device.device_ip,
                    "success": False,
                    "message": "导出失败：文件不存在"
                }
            
            # 导出成功后自动重启容器
            logger.info(f"开始重启容器: {device.device_name}")
            reboot_success = call_reboot_api(
                ip_address=device.device_ip,
                name=device.device_name
            )
            
            if reboot_success:
                logger.info(f"容器 {device.device_name} 重启成功")
                reboot_message = "导出并重启成功"
            else:
                logger.warning(f"容器 {device.device_name} 重启失败")
                reboot_message = "导出成功但重启失败"
            
            return {
                "device_id": device_id,
                "device_name": device.device_name,
                "device_ip": device.device_ip,
                "username": username,
                "export_path": export_path,
                "success": True,
                "reboot_success": reboot_success,
                "message": reboot_message
            }
        else:
            logger.error(f"导出失败: {device.device_name}")
            return {
                "device_id": device_id,
                "device_name": device.device_name,
                "device_ip": device.device_ip,
                "success": False,
                "message": "导出失败"
            }
            
    except Exception as e:
        logger.error(f"导出错误: {str(e)}")
        return {
            "device_id": device_id,
            "success": False,
            "message": f"导出错误: {str(e)}"
        }
    finally:
        # 确保关闭数据库会话
        db.close()

@router.post("/export-containers")
async def export_containers(
    export_data: Dict[str, Any] = Body(..., description="导出数据，包含设备ID列表和保存路径")
):
    """
    并发导出选中的容器，最多同时导出10个，导出成功后自动重启
    
    参数:
    export_data: 包含device_ids(设备ID列表)和save_path(可选的保存路径)
    """
    logger.info(f"导出容器请求: {export_data}")
    
    device_ids = export_data.get("device_ids", [])
    save_path = export_data.get("save_path", None)
    
    if not device_ids:
        raise HTTPException(status_code=400, detail="未提供设备ID")
    
    # 如果用户提供了保存路径，记录并验证
    if save_path:
        logger.info(f"用户指定保存路径: {save_path}")
        try:
            # 尝试创建目录以验证路径有效
            os.makedirs(save_path, exist_ok=True)
        except Exception as e:
            logger.error(f"创建保存路径失败: {str(e)}")
            raise HTTPException(status_code=400, detail=f"无效的保存路径: {str(e)}")
    
    # 将任务提交到线程池
    futures = []
    for device_id in device_ids:
        future = executor.submit(export_single_container, device_id, save_path)
        futures.append(future)
    
    # 收集结果
    results = []
    for future in concurrent.futures.as_completed(futures):
        try:
            result = future.result()
            results.append(result)
            
            # 检查导出的文件大小
            if result.get("success") and "export_path" in result:
                export_path = result["export_path"]
                if os.path.exists(export_path):
                    file_size = os.path.getsize(export_path)
                    logger.info(f"设备 {result.get('device_name', 'unknown')} 导出文件大小: {file_size} 字节")
                    
                    # 检查文件内容类型
                    try:
                        with open(export_path, "rb") as f:
                            file_start = f.read(100)
                        
                        # 尝试判断文件类型
                        if file_start.startswith(b'{') or file_start.startswith(b'['):
                            logger.warning(f"导出文件可能是JSON而不是容器数据: {file_start}")
                        elif file_size < 10000:
                            logger.warning(f"导出文件大小不符合预期: {file_size} 字节，可能不是完整容器")
                    except Exception as e:
                        logger.error(f"检查文件内容失败: {str(e)}")
        except Exception as e:
            logger.error(f"任务执行异常: {str(e)}")
            results.append({
                "device_id": "unknown",
                "success": False,
                "message": f"导出任务异常: {str(e)}"
            })
    
    # 汇总结果
    success_count = sum(1 for r in results if r.get("success", False))
    reboot_success_count = sum(1 for r in results if r.get("reboot_success", False))
    
    return {
        "success": success_count > 0,
        "message": f"已导出 {success_count}/{len(device_ids)} 个容器，成功重启 {reboot_success_count}/{success_count} 个容器",
        "results": results
    }

@router.post("/batch_export")
async def batch_export(
    export_data: Dict[str, Any] = Body(..., description="导出数据，包含设备ID列表和保存路径")
):
    """
    批量导出容器API - 新接口，功能与export-containers相同
    并发导出选中的容器，最多同时导出10个，导出成功后自动重启
    
    参数:
    export_data: 包含device_ids(设备ID列表)和save_path(可选的保存路径)
    """
    logger.info(f"批量导出容器请求(batch_export): {export_data}")
    
    device_ids = export_data.get("device_ids", [])
    save_path = export_data.get("save_path", None)
    
    if not device_ids:
        raise HTTPException(status_code=400, detail="未提供设备ID")
    
    # 如果用户提供了保存路径，记录并验证
    if save_path:
        logger.info(f"用户指定保存路径: {save_path}")
        try:
            os.makedirs(save_path, exist_ok=True)
        except Exception as e:
            logger.error(f"创建保存路径失败: {str(e)}")
            raise HTTPException(status_code=400, detail=f"无效的保存路径: {str(e)}")
    
    # 将任务提交到线程池
    futures = []
    for device_id in device_ids:
        future = executor.submit(export_single_container, device_id, save_path)
        futures.append(future)
    
    # 收集结果
    results = []
    for future in concurrent.futures.as_completed(futures):
        try:
            result = future.result()
            results.append(result)
            
            # 检查导出的文件大小
            if result.get("success") and "export_path" in result:
                export_path = result["export_path"]
                if os.path.exists(export_path):
                    file_size = os.path.getsize(export_path)
                    logger.info(f"设备 {result.get('device_name', 'unknown')} 导出文件大小: {file_size} 字节")
                    
                    # 检查文件内容类型
                    try:
                        with open(export_path, "rb") as f:
                            file_start = f.read(100)
                        
                        if file_start.startswith(b'{') or file_start.startswith(b'['):
                            logger.warning(f"导出文件可能是JSON而不是容器数据: {file_start}")
                        elif file_size < 10000:
                            logger.warning(f"导出文件大小不符合预期: {file_size} 字节")
                    except Exception as e:
                        logger.error(f"检查文件内容失败: {str(e)}")
        except Exception as e:
            logger.error(f"任务执行异常: {str(e)}")
            results.append({
                "device_id": "unknown",
                "success": False,
                "message": f"导出任务异常: {str(e)}"
            })
    
    # 汇总结果
    success_count = sum(1 for r in results if r.get("success", False))
    reboot_success_count = sum(1 for r in results if r.get("reboot_success", False))
    
    return {
        "success": success_count > 0,
        "message": f"已导出 {success_count}/{len(device_ids)} 个容器，成功重启 {reboot_success_count}/{success_count} 个容器",
        "results": results
    }

@router.get("/dc_api/v1/batch_export/{ip_address}")
async def dc_api_batch_export(
    ip_address: str,
    names: List[str] = Query(None, description="容器名称列表"),
    locals: List[str] = Query(None, description="保存路径列表")
):
    """
    批量导出容器的直接API，使用GET请求和查询参数
    
    参数:
    ip_address: 目标设备IP地址，路径参数
    names: 容器名称列表，查询参数，可重复多次
    locals: 本地保存路径列表，查询参数，可重复多次
    
    示例:
    /dc_api/v1/batch_export/192.168.8.74?names=container1&names=container2&locals=path1&locals=path2
    """
    logger.info(f"DC API批量导出请求: IP={ip_address}, names={names}, locals={locals}")
    
    if not names or not locals:
        raise HTTPException(status_code=400, detail="缺少必要的容器名称或保存路径参数")
        
    if len(names) != len(locals):
        raise HTTPException(status_code=400, detail=f"容器名称({len(names)})和保存路径({len(locals)})数量不匹配")
    
    # 使用线程池并发处理所有导出请求
    futures = []
    export_tasks = []
    
    # 保存导出任务信息，用于返回结果
    for i, (name, local_path) in enumerate(zip(names, locals)):
        export_tasks.append({"name": name, "local_path": local_path, "index": i})
        # 提交导出任务到线程池
        future = executor.submit(
            call_export_api,
            ip_address=ip_address,
            name=name,
            local_path=local_path
        )
        futures.append(future)
    
    # 收集导出结果
    results = []
    task_map = {id(future): task for future, task in zip(futures, export_tasks)}
    
    for future in concurrent.futures.as_completed(futures):
        task = task_map[id(future)]
        try:
            success = future.result()
            results.append({
                "name": task["name"],
                "local_path": task["local_path"],
                "success": success,
                "message": "导出成功" if success else "导出失败"
            })
            
            if success:
                # 导出成功后自动重启容器
                logger.info(f"开始重启容器: {task['name']}")
                reboot_success = call_reboot_api(
                    ip_address=ip_address,
                    name=task["name"]
                )
                
                if reboot_success:
                    logger.info(f"容器 {task['name']} 重启成功")
                    results[-1]["reboot_success"] = True
                    results[-1]["message"] = "导出并重启成功"
                else:
                    logger.warning(f"容器 {task['name']} 重启失败")
                    results[-1]["reboot_success"] = False
                    results[-1]["message"] = "导出成功但重启失败"
        except Exception as e:
            logger.error(f"导出错误: {str(e)}")
            results.append({
                "name": task["name"],
                "local_path": task["local_path"],
                "success": False,
                "message": f"导出错误: {str(e)}"
            })
    
    # 汇总结果
    success_count = sum(1 for r in results if r.get("success", False))
    reboot_success_count = sum(1 for r in results if r.get("reboot_success", False))
    
    return {
        "success": success_count > 0,
        "message": f"已导出 {success_count}/{len(names)} 个容器，成功重启 {reboot_success_count}/{success_count} 个容器",
        "results": results
    } 