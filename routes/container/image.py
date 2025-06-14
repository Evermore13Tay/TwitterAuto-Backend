"""
容器镜像模块
包含创建容器镜像和镜像管理功能
"""
import logging
import os
import aiohttp
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from db.database import get_db
from db import models

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)

router = APIRouter(tags=["container-image"])


@router.get("/create_pure_image/{box_ip}/{new_name}/{index}", summary="创建纯净镜像")
async def create_pure_image_endpoint(
    box_ip: str,
    new_name: str,
    index: int,
    filepath: str = Query(None, description="纯净镜像文件的完整路径"),
    filename: str = Query(None, description="纯净镜像文件名 (兼容旧版本, 例如 PureTwitter.tar.gz)")
):
    """
    创建一个新的纯净镜像容器
    
    参数:
    box_ip: 主机IP地址
    new_name: 新容器名称
    index: 容器索引
    filename: 纯净镜像文件名
    """
    try:
        # 构建API请求URL
        from urllib.parse import quote
        import os
        
        # 优先使用前端传递的完整路径
        local_path = None
        
        if filepath:
            # 使用前端传递的文件路径
            if os.path.exists(filepath):
                local_path = filepath
                logger.info(f"使用前端提供的文件路径: {local_path}")
            else:
                logger.warning(f"前端提供的文件路径不存在: {filepath}")
                # 路径不存在时，继续尝试其他方法
        
        # 如果没有有效路径但有文件名，尝试定位文件
        if not local_path and filename:
            # 如果文件名是绝对路径且存在，直接使用
            if os.path.isabs(filename) and os.path.exists(filename):
                local_path = filename
                logger.info(f"使用文件名参数中的绝对路径: {local_path}")
            # 否则，检查默认路径
            else:
                default_backup_paths = [
                    "D:/mytBackUp",  # 默认路径
                    "C:/mytBackUp",  # 备用路径
                    os.path.expanduser("~/mytBackUp"),  # 用户主目录下的路径
                ]
                
                # 尝试在不同路径下定位文件
                for base_path in default_backup_paths:
                    potential_path = os.path.join(base_path, filename)
                    if os.path.exists(potential_path):
                        local_path = potential_path
                        logger.info(f"在默认目录中找到文件: {local_path}")
                        break
        
        # 如果仍然没有有效路径，构造一个默认路径(即使文件可能不存在)
        if not local_path:
            # 使用filename或默认文件名
            default_filename = filename or "PureTwitter.tar.gz"
            local_path = os.path.join("D:/mytBackUp", default_filename)
            logger.warning(f"无法定位文件，使用默认路径: {local_path}")
        
        # 构造最终的API URL
        # 注意：正确的格式应该是 /import/{box_ip}/{new_name}/{index}?local={local_path}
        api_url = f"http://127.0.0.1:5000/import/{box_ip}/{new_name}/{index}?local={quote(local_path)}"
        
        logger.info(f"请求创建纯净镜像: {api_url}")
        
        # 调用远程API
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(api_url, timeout=60) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"创建纯净镜像失败: {response_text}"
                        )
                        
                    # 获取响应内容
                    result = await response.json()
                    
                    logger.info(f"创建纯净镜像响应: {result}")
                    
                    # 处理成功和失败情况
                    if result.get("status") == "success" or result.get("success", False):
                        return {
                            "success": True,
                            "message": f"成功创建纯净镜像容器: {new_name}",
                            "container_name": new_name,
                            "container_index": index,
                            "detail": result
                        }
                    else:
                        logger.error(f"创建纯净镜像失败: {result}")
                        return {
                            "success": False,
                            "message": f"创建纯净镜像失败: {result.get('message', '未知错误')}",
                            "detail": result
                        }
                        
            except aiohttp.ClientError as e:
                logger.error(f"连接主机API失败: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"连接主机API失败: {str(e)}"
                )
                
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"创建纯净镜像时出错: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"创建纯净镜像时出错: {str(e)}"
        )

@router.get("/list-images/{box_ip}")
async def list_images(
    box_ip: str
):
    """
    列出主机上的所有容器镜像
    
    参数:
    box_ip: 主机IP地址
    """
    try:
        # 构建API请求URL
        api_url = f"http://127.0.0.1:5000/list_images"
        
        logger.info(f"请求列出镜像: {api_url}")
        
        # 调用远程API
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(api_url, timeout=30) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"列出镜像失败: {response_text}"
                        )
                        
                    # 获取响应内容
                    result = await response.json()
                    
                    logger.info(f"列出镜像响应: {result}")
                    
                    # 返回镜像列表
                    return {
                        "success": True,
                        "images": result.get("images", []),
                        "count": len(result.get("images", []))
                    }
                    
            except aiohttp.ClientError as e:
                logger.error(f"连接主机API失败: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"连接主机API失败: {str(e)}"
                )
                
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"列出镜像时出错: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"列出镜像时出错: {str(e)}"
        )

@router.delete("/delete-image/{box_ip}/{image_name}")
async def delete_image(
    box_ip: str,
    image_name: str
):
    """
    删除主机上的容器镜像
    
    参数:
    box_ip: 主机IP地址
    image_name: 镜像名称
    """
    try:
        # 构建API请求URL
        api_url = f"http://127.0.0.1:5000/delete_image/{image_name}"
        
        logger.info(f"请求删除镜像: {api_url}")
        
        # 调用远程API
        async with aiohttp.ClientSession() as session:
            try:
                async with session.delete(api_url, timeout=30) as response:
                    if response.status != 200:
                        response_text = await response.text()
                        raise HTTPException(
                            status_code=response.status,
                            detail=f"删除镜像失败: {response_text}"
                        )
                        
                    # 获取响应内容
                    result = await response.json()
                    
                    logger.info(f"删除镜像响应: {result}")
                    
                    # 处理成功和失败情况
                    if result.get("status") == "success" or result.get("success", False):
                        return {
                            "success": True,
                            "message": f"成功删除镜像: {image_name}",
                            "detail": result
                        }
                    else:
                        logger.error(f"删除镜像失败: {result}")
                        return {
                            "success": False,
                            "message": f"删除镜像失败: {result.get('message', '未知错误')}",
                            "detail": result
                        }
                        
            except aiohttp.ClientError as e:
                logger.error(f"连接主机API失败: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"连接主机API失败: {str(e)}"
                )
                
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"删除镜像时出错: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"删除镜像时出错: {str(e)}"
        ) 