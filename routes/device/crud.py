"""
设备CRUD操作路由
包含创建、读取、更新、删除设备的基本操作
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_
from typing import List, Dict, Any, Optional
from db.database import get_db
from db import models
from schemas.models import DeviceUser, DeviceUserCreate, DeviceCredentialsUpdateRequest
from suspended_account import SuspendedAccount
from .utils import clear_device_cache, cache_key, _device_cache, _cache_timestamps
import time
import os

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)

router = APIRouter(prefix="/device-users", tags=["device-crud"])

@router.get("", response_model=List[DeviceUser])
async def get_device_users(db: Session = Depends(get_db)):
    """获取所有设备用户列表"""
    try:
        device_users = db.query(models.DeviceUser).all()
        
        # 获取所有被封号的用户名列表
        suspended_accounts = db.query(SuspendedAccount).all()
        suspended_usernames = set(account.username for account in suspended_accounts)
        
        logger.info(f"Total suspended usernames found: {len(suspended_usernames)}")
        logger.info(f"Suspended usernames: {list(suspended_usernames)[:5]}")  # 打印前5个
        
        result = []
        for user in device_users:
            # 检查用户是否被封号
            is_suspended = user.username in suspended_usernames if user.username else False
            
            if is_suspended:
                logger.info(f"Device {user.device_name} with username {user.username} is suspended")
            
            # 将数据库对象转换为字典，确保正确处理空值
            user_dict = {
                "id": user.id,
                "device_ip": user.device_ip,
                "box_ip": user.box_ip,
                "u2_port": user.u2_port,
                "myt_rpc_port": user.myt_rpc_port,
                "username": user.username,
                "password": user.password,
                "secret_key": user.secret_key,
                "device_name": user.device_name,
                "device_index": user.device_index,
                "status": user.status,
                "proxy_ip": user.proxy_ip,
                "proxy_port": user.proxy_port,
                "language": user.language,
                "proxy": f"{user.proxy_ip}:{user.proxy_port}" if user.proxy_ip and user.proxy_port else None,
                "is_suspended": is_suspended
            }
            result.append(DeviceUser.model_validate(user_dict))
        
        logger.info(f"Retrieved {len(result)} device users")
        return result
    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching device users: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error fetching device users: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.get("/paginated", response_model=Dict[str, Any])
async def get_device_users_paginated(
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(50, ge=1, le=500, description="每页大小，最大500"),
    search: Optional[str] = Query(None, description="搜索关键词（设备名称、IP或用户名）"),
    db: Session = Depends(get_db)
):
    """分页获取设备用户列表，支持搜索功能"""
    try:
        # 检查缓存
        cache_key_str = cache_key(page, page_size, search)
        current_time = time.time()
        
        # 如果缓存存在且未过期（60秒），直接返回
        if cache_key_str in _device_cache and cache_key_str in _cache_timestamps:
            if current_time - _cache_timestamps[cache_key_str] < 60:
                logger.debug(f"返回缓存数据: page={page}, search={search}")
                return _device_cache[cache_key_str]
        
        # 构建基础查询
        query = db.query(models.DeviceUser)
        
        # 如果有搜索关键词，添加过滤条件
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    models.DeviceUser.device_name.ilike(search_filter),
                    models.DeviceUser.device_ip.ilike(search_filter),
                    models.DeviceUser.username.ilike(search_filter)
                )
            )
        
        # 获取总数
        total_count = query.count()
        
        # 计算分页
        skip = (page - 1) * page_size
        
        # 查询数据
        devices = query.order_by(models.DeviceUser.device_name).offset(skip).limit(page_size).all()
        
        # 获取所有被封号的用户名列表
        suspended_accounts = db.query(SuspendedAccount).all()
        suspended_usernames = set(account.username for account in suspended_accounts)
        
        # 转换数据
        result = []
        for user in devices:
            is_suspended = user.username in suspended_usernames if user.username else False
            
            result.append({
                "id": user.id,
                "device_ip": user.device_ip,
                "box_ip": user.box_ip,
                "u2_port": user.u2_port,
                "myt_rpc_port": user.myt_rpc_port,
                "username": user.username,
                "password": user.password,
                "secret_key": user.secret_key,
                "device_name": user.device_name,
                "device_index": user.device_index,
                "status": user.status,
                "proxy": None,
                "is_suspended": is_suspended
            })
        
        # 计算总页数
        total_pages = (total_count + page_size - 1) // page_size
        
        # 构建响应
        response_data = {
            "items": result,
            "total": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        }
        
        # 更新缓存
        _device_cache[cache_key_str] = response_data
        _cache_timestamps[cache_key_str] = current_time
        
        # 清理过期缓存（防止内存泄漏）
        expired_keys = [k for k, t in _cache_timestamps.items() if current_time - t > 300]
        for k in expired_keys:
            _device_cache.pop(k, None)
            _cache_timestamps.pop(k, None)
        
        return response_data
    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching paginated device users: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error fetching paginated device users: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.post("", response_model=DeviceUser)
async def create_device_user(device_user_create: DeviceUserCreate, db: Session = Depends(get_db)):
    """创建新的设备用户"""
    try:
        logger.info(f"Creating device user with data: {device_user_create.model_dump()}")
        
        # 检查设备名称是否已存在
        existing_device = db.query(models.DeviceUser).filter(
            models.DeviceUser.device_name == device_user_create.device_name
        ).first()
        
        if existing_device:
            raise HTTPException(
                status_code=400,
                detail=f"Device with name '{device_user_create.device_name}' already exists"
            )
        
        # 创建新设备用户实例
        device_user = models.DeviceUser(**device_user_create.model_dump())
        
        # 添加到数据库
        try:
            db.add(device_user)
            db.commit()
            db.refresh(device_user)
            logger.info(f"Successfully created device user: {device_user.device_name}")
            
            # 清理缓存
            clear_device_cache()
            
            # 转换为Pydantic模型并返回
            device_user_dict = {
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
                "is_suspended": False
            }
            return DeviceUser.model_validate(device_user_dict)
        except SQLAlchemyError as db_error:
            db.rollback()
            logger.error(f"Database error while creating device user: {str(db_error)}")
            raise HTTPException(
                status_code=400,
                detail=f"Database error: {str(db_error)}"
            )
    except HTTPException as http_error:
        raise http_error
    except Exception as e:
        logger.error(f"Error creating device user: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.put("/{user_id}", response_model=DeviceUser)
async def update_device_user(user_id: str, device_user_update: DeviceUserCreate, db: Session = Depends(get_db)):
    """更新设备用户信息"""
    try:
        # 查找设备用户
        device_user = db.query(models.DeviceUser).filter(models.DeviceUser.id == user_id).first()
        if not device_user:
            raise HTTPException(status_code=404, detail="Device user not found")
        
        # 检查新设备名称是否已存在
        if device_user.device_name != device_user_update.device_name:
            existing_device = db.query(models.DeviceUser).filter(
                models.DeviceUser.device_name == device_user_update.device_name,
                models.DeviceUser.id != user_id
            ).first()
            if existing_device:
                raise HTTPException(
                    status_code=400,
                    detail=f"Device with name '{device_user_update.device_name}' already exists"
                )

        # 更新设备用户属性
        update_data = device_user_update.model_dump(exclude_unset=True)
        
        # 仅更新提供的非空字段
        for key, value in update_data.items():
            if key in ["password", "secret_key"]:
                # 对于password和secret_key，如果未提供（为空字符串或None），不更新
                if value:
                    setattr(device_user, key, value)
            else:
                setattr(device_user, key, value)

        try:
            db.commit()
            db.refresh(device_user)
            logger.info(f"Updated device user: {device_user.device_name} (ID: {user_id})")
            
            # 清理缓存
            clear_device_cache()
            
            # 检查更新后的用户是否被封号
            is_suspended = False
            if device_user.username:
                suspended_account = db.query(SuspendedAccount).filter(
                    SuspendedAccount.username == device_user.username
                ).first()
                is_suspended = suspended_account is not None
            
            # 转换为Pydantic模型并返回
            result = DeviceUser.model_validate({
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
            return result
        except SQLAlchemyError as db_error:
            db.rollback()
            logger.error(f"Database error while updating device user: {str(db_error)}")
            raise HTTPException(
                status_code=400,
                detail=f"Database error: {str(db_error)}"
            )
    except HTTPException as http_error:
        raise http_error
    except Exception as e:
        logger.error(f"Error updating device user: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.delete("/{user_id}", response_model=Dict[str, str])
async def delete_device_user(user_id: str, db: Session = Depends(get_db)):
    """删除设备用户"""
    try:
        # 查找设备用户
        device_user = db.query(models.DeviceUser).filter(models.DeviceUser.id == user_id).first()
        if not device_user:
            raise HTTPException(status_code=404, detail="Device user not found")

        # 存储删除前的名称用于日志
        deleted_user_name = device_user.device_name

        # 删除设备用户
        db.delete(device_user)
        db.commit()

        logger.info(f"Deleted device user: {deleted_user_name} (ID: {user_id})")
        
        # 清理缓存
        clear_device_cache()
        
        return {"status": "deleted", "id": user_id}
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error while deleting device user: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
    except HTTPException as http_error:
        raise http_error
    except Exception as e:
        logger.error(f"Error deleting device user: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

# 保留原有端点但仅使用PUT方法
@router.put("/{device_id}/credentials", response_model=DeviceUser)
async def update_device_credentials(
    device_id: str,
    request: DeviceCredentialsUpdateRequest,
    db: Session = Depends(get_db)
):
    """更新设备凭证信息 (PUT方法)"""
    logger.info(f"Attempting to update credentials for device ID: {device_id} via PUT method")
    return await _update_device_credentials_internal(device_id, request, db)

# 新增一个专门用于批量更新的POST方法端点
@router.post("/{device_id}/update-credentials", response_model=DeviceUser)
async def post_update_device_credentials(
    device_id: str,
    request: DeviceCredentialsUpdateRequest,
    db: Session = Depends(get_db)
):
    """更新设备凭证信息 (POST方法，新端点)"""
    logger.info(f"Attempting to update credentials for device ID: {device_id} via POST method (new endpoint)")
    return await _update_device_credentials_internal(device_id, request, db)

# 新增一个使用GET方法的凭据更新端点
@router.get("/{device_id}/update-credentials", response_model=DeviceUser)
async def get_update_device_credentials(
    device_id: str,
    username: str,
    password: str,
    secret_key: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """使用GET方法更新设备凭证 (查询参数形式)"""
    logger.info(f"Attempting to update credentials for device ID: {device_id} via GET method with query parameters")
    
    # 创建请求对象
    request = DeviceCredentialsUpdateRequest(
        username=username,
        password=password,
        secret_key=secret_key if secret_key else None
    )
    
    return await _update_device_credentials_internal(device_id, request, db)

# 提取共用逻辑到内部函数
async def _update_device_credentials_internal(device_id: str, request: DeviceCredentialsUpdateRequest, db: Session):
    """凭据更新内部实现"""
    logger.info(f"Processing credentials update for device ID: {device_id}")
    db_device = db.query(models.DeviceUser).filter(models.DeviceUser.id == device_id).first()
    if not db_device:
        logger.warning(f"Device not found with ID: {device_id} for credential update.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    
    try:
        update_data = request.model_dump(exclude_unset=True)
        if 'username' in update_data:
            db_device.username = update_data['username']
        if 'password' in update_data:
            db_device.password = update_data['password'] 
        if 'secret_key' in update_data:
            db_device.secret_key = update_data['secret_key']
        else:
            db_device.secret_key = None

        db.commit()
        db.refresh(db_device)
        logger.info(f"Successfully updated credentials for device ID: {device_id}, username: {request.username}")
        
        # 检查用户是否被封号
        is_suspended = False
        if db_device.username:
            suspended_account = db.query(SuspendedAccount).filter(
                SuspendedAccount.username == db_device.username
            ).first()
            is_suspended = suspended_account is not None
        
        return DeviceUser.model_validate({
            "id": db_device.id,
            "device_ip": db_device.device_ip,
            "box_ip": db_device.box_ip,
            "u2_port": db_device.u2_port,
            "myt_rpc_port": db_device.myt_rpc_port,
            "username": db_device.username,
            "password": db_device.password,
            "secret_key": db_device.secret_key,
            "device_name": db_device.device_name,
            "device_index": db_device.device_index,
            "status": db_device.status,
            "proxy": None,
            "is_suspended": is_suspended
        })
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error updating credentials for device ID {device_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: Failed to update credentials.")
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error updating credentials for device ID {device_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected error: Failed to update credentials.")

@router.get("/suspended-accounts", response_model=Dict[str, Any])
async def get_suspended_accounts(db: Session = Depends(get_db)):
    """获取封号账号列表"""
    try:
        suspended_accounts = db.query(SuspendedAccount).all()
        suspended_usernames = [account.username for account in suspended_accounts]
        
        logger.info(f"Retrieved {len(suspended_usernames)} suspended usernames")
        
        return {
            "suspended_usernames": suspended_usernames,
            "count": len(suspended_usernames)
        }
    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching suspended accounts: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error fetching suspended accounts: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@router.get("/system/max-instance-slots")
async def get_max_instance_slots(db: Session = Depends(get_db)):
    """
    获取系统最大实例位数量配置
    从数据库读取所有设备的device_index并去重计算
    
    Returns:
        dict: 包含最大实例位数量的配置信息
    """
    try:
        # 从数据库查询所有设备的device_index
        device_indices = db.query(models.DeviceUser.device_index).filter(
            models.DeviceUser.device_index.isnot(None)
        ).all()
        
        # 提取所有非空的device_index值
        valid_indices = [idx[0] for idx in device_indices if idx[0] is not None and idx[0] >= 0]
        
        # 去重并排序
        unique_indices = sorted(list(set(valid_indices)))
        
        logger.info(f"数据库中找到的实例位: {unique_indices}")
        
        # 计算最大实例位数量
        if unique_indices:
            # 如果有实例位，计算实际可用的实例位数量
            min_index = min(unique_indices)
            max_index = max(unique_indices)
            
            # 如果实例位从0开始，最大实例位数量 = 最大索引 + 1
            # 如果实例位从1开始，最大实例位数量 = 最大索引
            if min_index == 0:
                max_instance_slots = max_index + 1
            else:
                max_instance_slots = max_index
                
            # 但实际可用的实例位数量应该是唯一实例位的个数
            actual_slots_count = len(unique_indices)
            
            logger.info(f"计算结果: 最小索引={min_index}, 最大索引={max_index}, 唯一实例位数量={actual_slots_count}")
            
            # 使用实际的唯一实例位数量
            max_instance_slots = actual_slots_count
        else:
            # 如果没有找到任何实例位，使用默认值
            max_instance_slots = 1
            logger.info("数据库中未找到任何实例位，使用默认值1")
        
        # 确保值在合理范围内
        if max_instance_slots < 1:
            max_instance_slots = 1
        elif max_instance_slots > 20:  # 提高上限到20
            max_instance_slots = 20
            
        return {
            "success": True,
            "max_instance_slots": max_instance_slots,
            "unique_indices": unique_indices,
            "total_devices_with_index": len(valid_indices),
            "message": f"系统最大实例位数量: {max_instance_slots} (基于数据库中的 {len(unique_indices)} 个唯一实例位)"
        }
    except Exception as e:
        logger.error(f"获取系统最大实例位数量时出错: {str(e)}")
        # 出错时返回默认值
        return {
            "success": False,
            "max_instance_slots": 1,
            "message": f"获取配置失败，使用默认值: {str(e)}"
        } 