#!/usr/bin/env python3
"""
一体化操作任务API路由
包括获取在线设备、推文模板选择、执行一体化操作等功能
"""

import os
import logging
import time
import json
import uuid
import asyncio
import traceback
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Import backend modules
from db import models
from db.database import get_db, SessionLocal
from utils.connection import manager, active_tasks
from utils.callbacks import WebSocketStatusCallback
from automation.postTweetTest import run_post_tweet

logger = logging.getLogger("TwitterAutomationAPI")

router = APIRouter(
    prefix="/api/integrated-operation",
    tags=["integrated-operation"],
)

class IntegratedOperationRequest(BaseModel):
    operations: List[str]  # 选中的操作类型
    tweet_template_id: Optional[int] = None  # 选中的推文模板ID
    target_devices: Optional[List[str]] = None  # 目标设备列表

@router.get("/online-devices")
async def get_online_devices():
    """获取所有在线设备"""
    try:
        logger.info("获取在线设备列表...")
        
        # 从数据库获取设备信息
        db = SessionLocal()
        try:
            devices = db.query(models.DeviceUser).all()
            devices_data = []
            for device in devices:
                devices_data.append({
                    "id": device.id,
                    "device_name": device.device_name,
                    "device_ip": device.device_ip,
                    "u2_port": device.u2_port,
                    "myt_rpc_port": device.myt_rpc_port,
                    "username": device.username,
                    "status": "online"
                })
        finally:
            db.close()
        
        logger.info(f"获取到 {len(devices_data)} 个设备")
        return {"success": True, "devices": devices_data}
    except Exception as e:
        logger.error(f"获取在线设备失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取在线设备失败: {str(e)}")

@router.get("/tweet-templates")
async def get_tweet_templates(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取推文模板列表"""
    try:
        # 构建查询
        query = db.query(models.TweetTemplate).filter(models.TweetTemplate.status == "active")
        
        # 分类筛选
        if category_id:
            query = query.filter(models.TweetTemplate.category_id == category_id)
        
        # 搜索
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                models.TweetTemplate.title.like(search_term) |
                models.TweetTemplate.content.like(search_term)
            )
        
        # 获取结果
        templates = query.order_by(models.TweetTemplate.created_time.desc()).limit(50).all()
        
        # 转换为字典格式
        templates_data = []
        for template in templates:
            # 获取关联的图片
            images = db.query(models.TweetImage).filter(
                models.TweetImage.tweet_id == template.id
            ).order_by(models.TweetImage.sort_order).all()
            
            templates_data.append({
                "id": template.id,
                "title": template.title,
                "content": template.content,
                "category_id": template.category_id,
                "tags": template.tags,
                "use_count": template.use_count,
                "is_favorite": template.is_favorite,
                "created_time": template.created_time,
                "images": [
                    {
                        "id": img.id,
                        "filename": img.file_name,
                        "file_path": img.file_path,
                        "sort_order": img.sort_order
                    } for img in images
                ]
            })
        
        return {"success": True, "templates": templates_data}
    except Exception as e:
        logger.error(f"获取推文模板失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取推文模板失败: {str(e)}")

@router.post("/execute")
async def execute_integrated_operation(
    request: IntegratedOperationRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """执行一体化操作任务"""
    try:
        logger.info(f"开始执行一体化操作: {request.operations}")
        
        # 创建任务ID
        task_id = f"integrated_operation_{uuid.uuid4().hex[:8]}"
        
        # 获取目标设备
        devices = db.query(models.DeviceUser).all()
        target_devices = [
            {
                "device_name": device.device_name,
                "device_ip": device.device_ip,
                "u2_port": device.u2_port,
                "myt_rpc_port": device.myt_rpc_port,
                "username": device.username
            } for device in devices
        ]
        
        if not target_devices:
            raise HTTPException(status_code=400, detail="没有找到可用的目标设备")
        
        # 获取推文模板
        tweet_data = None
        if "post_tweet" in request.operations and request.tweet_template_id:
            template = db.query(models.TweetTemplate).filter(
                models.TweetTemplate.id == request.tweet_template_id
            ).first()
            
            if not template:
                raise HTTPException(status_code=404, detail="推文模板不存在")
            
            # 获取关联的图片
            images = db.query(models.TweetImage).filter(
                models.TweetImage.tweet_id == template.id
            ).order_by(models.TweetImage.sort_order).all()
            
            tweet_data = {
                "title": template.title,
                "content": template.content,
                "images": [
                    {
                        "filename": img.file_name,
                        "file_path": img.file_path
                    } for img in images
                ]
            }
        
        # 存储当前事件循环
        current_loop = asyncio.get_running_loop()
        
        # 创建回调函数
        callback = WebSocketStatusCallback(
            task_id,
            loop=current_loop,
            extra_data={
                "operations": request.operations,
                "device_count": len(target_devices),
                "tweet_template_id": request.tweet_template_id
            }
        )
        
        # 在后台执行任务
        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            execute_integrated_operation_task,
            request.operations,
            target_devices,
            tweet_data,
            callback,
            task_id,
            current_loop
        )
        
        # 处理任务完成
        def handle_task_completion(future):
            try:
                result = future.result()
                asyncio.run_coroutine_threadsafe(
                    manager.send_task_completed(task_id, "integrated_operation"),
                    current_loop
                )
            except Exception as e:
                error_message = f"Integrated operation task failed: {str(e)}"
                logger.error(f"Task {task_id} failed: {error_message}")
                
                asyncio.run_coroutine_threadsafe(
                    manager.send_task_error(task_id, error_message, "integrated_operation"),
                    current_loop
                )
                
                if task_id in active_tasks:
                    active_tasks[task_id]["status"] = "failed"
                    active_tasks[task_id]["error"] = error_message
        
        future.add_done_callback(handle_task_completion)
        
        return {
            "success": True,
            "task_id": task_id,
            "message": f"一体化操作任务已启动，目标设备数量: {len(target_devices)}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行一体化操作失败: {e}")
        raise HTTPException(status_code=500, detail=f"执行一体化操作失败: {str(e)}")

def execute_integrated_operation_task(operations, target_devices, tweet_data, callback, task_id, main_loop):
    """执行一体化操作任务的具体逻辑"""
    try:
        callback(f"开始执行一体化操作，目标设备: {len(target_devices)} 个")
        
        success_count = 0
        failed_count = 0
        
        for i, device in enumerate(target_devices):
            try:
                callback(f"处理设备 {i+1}/{len(target_devices)}: {device['device_name']}")
                
                device_success = True
                
                if "post_tweet" in operations and tweet_data:
                    callback(f"设备 {device['device_name']} - 执行发推文操作")
                    
                    # 准备图片路径
                    image_paths = []
                    if tweet_data.get("images"):
                        for img in tweet_data["images"]:
                            if os.path.exists(img["file_path"]):
                                image_paths.append(img["file_path"])
                    
                    # 调用发推文功能
                    def device_callback(message):
                        callback(f"设备 {device['device_name']} - {message}")
                    
                    success = run_post_tweet(
                        device_callback,
                        device["device_ip"],
                        device["u2_port"],
                        device["myt_rpc_port"],
                        tweet_data["content"],
                        len(image_paths) > 0,
                        image_paths
                    )
                    
                    if not success:
                        device_success = False
                        callback(f"设备 {device['device_name']} - 发推文失败")
                    else:
                        callback(f"设备 {device['device_name']} - 发推文成功")
                
                if device_success:
                    success_count += 1
                else:
                    failed_count += 1
                
                # 设备间添加延迟
                if i < len(target_devices) - 1:
                    time.sleep(2)
                    
            except Exception as e:
                failed_count += 1
                callback(f"设备 {device['device_name']} - 处理异常: {str(e)}")
                logger.error(f"处理设备 {device['device_name']} 时出错: {e}")
        
        callback(f"一体化操作任务完成！成功: {success_count} 个设备，失败: {failed_count} 个设备")
        
        return {
            "success": True,
            "total": len(target_devices),
            "success_count": success_count,
            "failed_count": failed_count
        }
        
    except Exception as e:
        callback(f"一体化操作任务执行异常: {str(e)}")
        logger.error(f"一体化操作任务执行异常: {e}")
        raise e