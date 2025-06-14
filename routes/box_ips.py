"""
盒子IP管理路由
提供完整的增删改查功能
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Optional
import re
from datetime import datetime

from db.database import get_db
from db import models
from schemas.models import BoxIP, BoxIPCreate, BoxIPUpdate

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/box-ips", tags=["box-ips"])

def validate_ip_address(ip: str) -> bool:
    """验证IP地址格式"""
    ip_pattern = r'^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
    return bool(re.match(ip_pattern, ip))

@router.get("/", response_model=List[BoxIP])
async def get_box_ips(
    skip: int = Query(0, ge=0, description="跳过的记录数"),
    limit: int = Query(100, ge=1, le=1000, description="返回的记录数"),
    status: Optional[str] = Query(None, description="状态过滤：active, inactive"),
    search: Optional[str] = Query(None, description="搜索关键词（IP地址或名称）"),
    db: Session = Depends(get_db)
):
    """获取盒子IP列表"""
    try:
        query = db.query(models.BoxIP)
        
        # 状态过滤
        if status:
            query = query.filter(models.BoxIP.status == status)
        
        # 搜索过滤
        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (models.BoxIP.ip_address.like(search_pattern)) |
                (models.BoxIP.name.like(search_pattern))
            )
        
        # 排序和分页
        query = query.order_by(models.BoxIP.created_at.desc())
        box_ips = query.offset(skip).limit(limit).all()
        
        return box_ips
        
    except Exception as e:
        logger.error(f"获取盒子IP列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取盒子IP列表失败: {str(e)}")

@router.get("/active", response_model=List[str])
async def get_active_box_ips(db: Session = Depends(get_db)):
    """获取所有活跃的盒子IP地址列表（简单字符串列表）"""
    try:
        box_ips = db.query(models.BoxIP.ip_address).filter(
            models.BoxIP.status == "active"
        ).order_by(models.BoxIP.created_at.desc()).all()
        
        return [ip.ip_address for ip in box_ips]
        
    except Exception as e:
        logger.error(f"获取活跃盒子IP列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取活跃盒子IP列表失败: {str(e)}")

@router.post("/", response_model=BoxIP)
async def create_box_ip(box_ip_create: BoxIPCreate, db: Session = Depends(get_db)):
    """创建新的盒子IP"""
    try:
        # 验证IP地址格式
        if not validate_ip_address(box_ip_create.ip_address):
            raise HTTPException(status_code=400, detail="无效的IP地址格式")
        
        # 检查IP是否已存在
        existing_box_ip = db.query(models.BoxIP).filter(
            models.BoxIP.ip_address == box_ip_create.ip_address
        ).first()
        
        if existing_box_ip:
            raise HTTPException(status_code=400, detail="该IP地址已存在")
        
        # 创建新记录
        db_box_ip = models.BoxIP(**box_ip_create.model_dump())
        db.add(db_box_ip)
        db.commit()
        db.refresh(db_box_ip)
        
        logger.info(f"成功创建盒子IP: {box_ip_create.ip_address}")
        return db_box_ip
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建盒子IP失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建盒子IP失败: {str(e)}")

@router.get("/{box_ip_id}", response_model=BoxIP)
async def get_box_ip(box_ip_id: str, db: Session = Depends(get_db)):
    """获取单个盒子IP详情"""
    try:
        box_ip = db.query(models.BoxIP).filter(models.BoxIP.id == box_ip_id).first()
        
        if not box_ip:
            raise HTTPException(status_code=404, detail="盒子IP不存在")
        
        return box_ip
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取盒子IP详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取盒子IP详情失败: {str(e)}")

@router.put("/{box_ip_id}", response_model=BoxIP)
async def update_box_ip(
    box_ip_id: str, 
    box_ip_update: BoxIPUpdate, 
    db: Session = Depends(get_db)
):
    """更新盒子IP"""
    try:
        box_ip = db.query(models.BoxIP).filter(models.BoxIP.id == box_ip_id).first()
        
        if not box_ip:
            raise HTTPException(status_code=404, detail="盒子IP不存在")
        
        # 如果要更新IP地址，需要验证格式和唯一性
        if box_ip_update.ip_address and box_ip_update.ip_address != box_ip.ip_address:
            if not validate_ip_address(box_ip_update.ip_address):
                raise HTTPException(status_code=400, detail="无效的IP地址格式")
            
            existing_box_ip = db.query(models.BoxIP).filter(
                models.BoxIP.ip_address == box_ip_update.ip_address,
                models.BoxIP.id != box_ip_id
            ).first()
            
            if existing_box_ip:
                raise HTTPException(status_code=400, detail="该IP地址已存在")
        
        # 更新字段
        update_data = box_ip_update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(box_ip, field, value)
        
        # 更新时间
        box_ip.updated_at = datetime.now()
        
        db.commit()
        db.refresh(box_ip)
        
        logger.info(f"成功更新盒子IP: {box_ip.ip_address}")
        return box_ip
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新盒子IP失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新盒子IP失败: {str(e)}")

@router.delete("/{box_ip_id}")
async def delete_box_ip(box_ip_id: str, db: Session = Depends(get_db)):
    """删除盒子IP"""
    try:
        box_ip = db.query(models.BoxIP).filter(models.BoxIP.id == box_ip_id).first()
        
        if not box_ip:
            raise HTTPException(status_code=404, detail="盒子IP不存在")
        
        ip_address = box_ip.ip_address
        db.delete(box_ip)
        db.commit()
        
        logger.info(f"成功删除盒子IP: {ip_address}")
        return {"success": True, "message": f"成功删除盒子IP: {ip_address}"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除盒子IP失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除盒子IP失败: {str(e)}")

@router.delete("/by-ip/{ip_address}")
async def delete_box_ip_by_address(ip_address: str, db: Session = Depends(get_db)):
    """通过IP地址删除盒子IP"""
    try:
        box_ip = db.query(models.BoxIP).filter(models.BoxIP.ip_address == ip_address).first()
        
        if not box_ip:
            raise HTTPException(status_code=404, detail="盒子IP不存在")
        
        db.delete(box_ip)
        db.commit()
        
        logger.info(f"成功删除盒子IP: {ip_address}")
        return {"success": True, "message": f"成功删除盒子IP: {ip_address}"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除盒子IP失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除盒子IP失败: {str(e)}")

@router.patch("/{box_ip_id}/status")
async def toggle_box_ip_status(box_ip_id: str, db: Session = Depends(get_db)):
    """切换盒子IP状态（启用/禁用）"""
    try:
        box_ip = db.query(models.BoxIP).filter(models.BoxIP.id == box_ip_id).first()
        
        if not box_ip:
            raise HTTPException(status_code=404, detail="盒子IP不存在")
        
        # 切换状态
        new_status = "inactive" if box_ip.status == "active" else "active"
        box_ip.status = new_status
        box_ip.updated_at = datetime.now()
        
        db.commit()
        db.refresh(box_ip)
        
        logger.info(f"成功切换盒子IP状态: {box_ip.ip_address} -> {new_status}")
        return box_ip
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"切换盒子IP状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"切换盒子IP状态失败: {str(e)}") 