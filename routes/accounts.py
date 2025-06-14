#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from fastapi import APIRouter, Query, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator
from typing import List, Optional, Union
import re
from datetime import datetime

from db.database import get_db
from db.models import SocialAccount, AccountGroup, Proxy
from suspended_account import SuspendedAccount

router = APIRouter()

# Pydantic模型
class AccountCreate(BaseModel):
    username: str
    password: str
    secret_key: Optional[str] = None
    platform: str = "twitter"
    status: str = "active"
    notes: Optional[str] = None
    proxy_id: Optional[int] = None
    backup_exported: int = 0

class AccountUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    secret_key: Optional[str] = None
    platform: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    proxy_id: Optional[int] = None
    backup_exported: Optional[int] = None

class AccountResponse(BaseModel):
    id: int
    username: str
    password: str
    secret_key: Optional[str] = None
    platform: str
    status: str
    group_id: Optional[int] = None
    proxy_id: Optional[int] = None
    last_login_time: Optional[datetime] = None
    backup_exported: int = 0
    created_time: datetime
    updated_time: datetime
    notes: Optional[str] = None
    # 代理信息
    proxy_info: Optional[dict] = None

    class Config:
        from_attributes = True

class BatchAccountInput(BaseModel):
    accounts_text: str
    platform: str = "twitter"
    group_id: Optional[int] = None

@router.get("/api/accounts", response_model=dict)
async def get_accounts(
    search: str = Query("", description="搜索关键词"),
    status: str = Query("", description="状态筛选"),
    platform: str = Query("", description="平台筛选"),
    group_id: Optional[int] = Query(None, description="分组筛选"),
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(10, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db)
):
    """获取社媒账号列表"""
    try:
        query = db.query(SocialAccount)
        
        # 搜索过滤
        if search.strip():
            query = query.filter(
                SocialAccount.username.contains(search) |
                SocialAccount.notes.contains(search)
            )
        
        # 状态过滤 - 特殊处理封号状态
        if status.strip():
            if status == "suspended":
                # 如果查询封号账号，需要查询suspended_accounts表
                suspended_usernames = [acc.username for acc in db.query(SuspendedAccount).all()]
                if suspended_usernames:
                    query = query.filter(SocialAccount.username.in_(suspended_usernames))
                else:
                    # 如果没有封号账号，返回空结果
                    query = query.filter(SocialAccount.id == -1)  # 不存在的ID
            else:
                # 对于其他状态，使用原有逻辑，但排除已封号的账号
                suspended_usernames = [acc.username for acc in db.query(SuspendedAccount).all()]
                query = query.filter(SocialAccount.status == status)
                if suspended_usernames:
                    query = query.filter(~SocialAccount.username.in_(suspended_usernames))
        
        # 平台过滤
        if platform.strip():
            query = query.filter(SocialAccount.platform == platform)
        
        # 分组过滤
        if group_id is not None:
            query = query.filter(SocialAccount.group_id == group_id)
        
        # 总数统计
        total = query.count()
        
        # 分页
        offset = (page - 1) * per_page
        accounts = query.order_by(SocialAccount.created_time.desc()).offset(offset).limit(per_page).all()
        
        # 获取所有被封号的用户名列表
        suspended_accounts = db.query(SuspendedAccount).all()
        suspended_usernames = set(account.username for account in suspended_accounts)
        
        # 构建账号数据，包含代理信息和封号状态
        account_list = []
        for account in accounts:
            account_data = AccountResponse.from_orm(account).dict()
            
            # 检查是否在suspended_accounts表中，如果是则覆盖状态为suspended
            if account.username in suspended_usernames:
                account_data["status"] = "suspended"
            
            # 添加代理信息
            if account.proxy_id and account.proxy:
                account_data["proxy_info"] = {
                    "id": account.proxy.id,
                    "ip": account.proxy.ip,
                    "port": account.proxy.port,
                    "name": account.proxy.name,
                    "country": account.proxy.country,
                    "status": account.proxy.status
                }
            else:
                account_data["proxy_info"] = None
                
            account_list.append(account_data)
        
        return {
            "success": True,
            "accounts": account_list,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/accounts", response_model=dict)
async def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    """创建单个社媒账号"""
    try:
        # 检查用户名是否已存在
        existing = db.query(SocialAccount).filter(SocialAccount.username == account.username).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"用户名 {account.username} 已存在")
        
        db_account = SocialAccount(**account.dict())
        db.add(db_account)
        db.commit()
        db.refresh(db_account)
        
        return {
            "success": True,
            "account": AccountResponse.from_orm(db_account).dict(),
            "message": "账号创建成功"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/accounts/batch", response_model=dict)
async def batch_create_accounts(batch_input: BatchAccountInput, db: Session = Depends(get_db)):
    """批量创建社媒账号"""
    try:
        accounts_text = batch_input.accounts_text.strip()
        if not accounts_text:
            raise HTTPException(status_code=400, detail="批量输入内容不能为空")
        
        lines = accounts_text.split('\n')
        created_accounts = []
        skipped_accounts = []
        error_accounts = []
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                # 支持两种格式：空格分隔 和 双横线分隔
                if '--' in line:
                    # 格式：username--password--secret_key
                    parts = line.split('--')
                else:
                    # 格式：username password secret_key (空格分隔)
                    parts = re.split(r'\s+', line)
                
                if len(parts) < 2:
                    error_accounts.append({
                        "line": line_num,
                        "content": line,
                        "error": "格式错误：至少需要用户名和密码。支持格式：'用户名 密码 密钥' 或 '用户名--密码--密钥'"
                    })
                    continue
                
                username = parts[0].strip()
                password = parts[1].strip()
                secret_key = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
                
                # 检查用户名是否已存在
                existing = db.query(SocialAccount).filter(SocialAccount.username == username).first()
                if existing:
                    skipped_accounts.append({
                        "username": username,
                        "reason": "用户名已存在"
                    })
                    continue
                
                # 创建账号
                db_account = SocialAccount(
                    username=username,
                    password=password,
                    secret_key=secret_key,
                    platform=batch_input.platform,
                    status="active",
                    group_id=batch_input.group_id
                )
                
                db.add(db_account)
                created_accounts.append(username)
                
            except Exception as e:
                error_accounts.append({
                    "line": line_num,
                    "content": line,
                    "error": str(e)
                })
        
        # 提交所有有效的账号
        if created_accounts:
            db.commit()
        
        return {
            "success": True,
            "message": f"批量导入完成",
            "summary": {
                "created_count": len(created_accounts),
                "skipped_count": len(skipped_accounts),
                "error_count": len(error_accounts)
            },
            "details": {
                "created_accounts": created_accounts,
                "skipped_accounts": skipped_accounts,
                "error_accounts": error_accounts
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

class BatchUpdateGroupInput(BaseModel):
    account_ids: List[Union[int, str]]
    group_id: Optional[int] = None
    
    @validator('account_ids')
    def convert_to_int(cls, v):
        return [int(item) for item in v]

@router.put("/api/accounts/batch-group", response_model=dict)
async def batch_update_group(batch_input: BatchUpdateGroupInput, db: Session = Depends(get_db)):
    """批量修改账号分组"""
    try:
        account_ids = batch_input.account_ids
        group_id = batch_input.group_id
        
        if not account_ids:
            raise HTTPException(status_code=400, detail="请提供要修改的账号ID列表")
        
        # 如果提供了group_id，验证分组是否存在
        if group_id is not None:
            group_id = int(group_id)
            if group_id > 0:  # 0或None表示移到未分组
                from db.models import AccountGroup
                group = db.query(AccountGroup).filter(AccountGroup.id == group_id).first()
                if not group:
                    raise HTTPException(status_code=404, detail="指定的分组不存在")
        
        updated_count = 0
        updated_usernames = []
        
        for account_id in account_ids:
            db_account = db.query(SocialAccount).filter(SocialAccount.id == account_id).first()
            if db_account:
                db_account.group_id = group_id if group_id and group_id > 0 else None
                updated_usernames.append(db_account.username)
                updated_count += 1
        
        db.commit()
        
        return {
            "success": True,
            "message": f"成功修改 {updated_count} 个账号的分组",
            "updated_count": updated_count,
            "updated_usernames": updated_usernames
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# 代理相关的数据模型
class BatchUpdateProxyInput(BaseModel):
    account_ids: List[Union[int, str]]
    proxy_id: Optional[int] = None  # None表示取消分配代理
    
    @validator('account_ids')
    def convert_to_int(cls, v):
        return [int(item) for item in v]

@router.put("/api/accounts/batch/proxy", response_model=dict)
async def batch_update_proxy(batch_input: BatchUpdateProxyInput, db: Session = Depends(get_db)):
    """批量分配/取消代理"""
    try:
        account_ids = batch_input.account_ids
        proxy_id = batch_input.proxy_id
        
        if not account_ids:
            raise HTTPException(status_code=400, detail="请提供要修改的账号ID列表")
        
        # 如果提供了proxy_id，验证代理是否存在且可用
        if proxy_id is not None:
            proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
            if not proxy:
                raise HTTPException(status_code=404, detail="指定的代理不存在")
            if proxy.status != "active":
                raise HTTPException(status_code=400, detail="指定的代理状态不可用")
        
        updated_count = 0
        updated_usernames = []
        
        for account_id in account_ids:
            db_account = db.query(SocialAccount).filter(SocialAccount.id == account_id).first()
            if db_account:
                db_account.proxy_id = proxy_id
                updated_usernames.append(db_account.username)
                updated_count += 1
        
        db.commit()
        
        action = "分配代理" if proxy_id else "取消代理分配"
        return {
            "success": True,
            "message": f"成功为 {updated_count} 个账号{action}",
            "updated_count": updated_count,
            "updated_usernames": updated_usernames
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/api/accounts/{account_id}", response_model=dict)
async def update_account(account_id: int, account: AccountUpdate, db: Session = Depends(get_db)):
    """更新社媒账号"""
    try:
        db_account = db.query(SocialAccount).filter(SocialAccount.id == account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="账号不存在")
        
        # 更新非空字段
        update_data = account.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_account, field, value)
        
        db.commit()
        db.refresh(db_account)
        
        return {
            "success": True,
            "account": AccountResponse.from_orm(db_account).dict(),
            "message": "账号更新成功"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

class BatchDeleteInput(BaseModel):
    account_ids: List[Union[int, str]]
    
    @validator('account_ids')
    def convert_to_int(cls, v):
        return [int(item) for item in v]

@router.delete("/api/accounts/batch", response_model=dict)
async def batch_delete_accounts(batch_input: BatchDeleteInput, db: Session = Depends(get_db)):
    """批量删除社媒账号"""
    try:
        account_ids = batch_input.account_ids
        
        if not account_ids:
            raise HTTPException(status_code=400, detail="请提供要删除的账号ID列表")
        
        deleted_count = 0
        deleted_usernames = []
        
        for account_id in account_ids:
            db_account = db.query(SocialAccount).filter(SocialAccount.id == account_id).first()
            if db_account:
                deleted_usernames.append(db_account.username)
                db.delete(db_account)
                deleted_count += 1
        
        db.commit()
        
        return {
            "success": True,
            "message": f"成功删除 {deleted_count} 个账号",
            "deleted_count": deleted_count,
            "deleted_usernames": deleted_usernames
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/api/accounts/{account_id}", response_model=dict)
async def delete_account(account_id: int, db: Session = Depends(get_db)):
    """删除社媒账号"""
    try:
        db_account = db.query(SocialAccount).filter(SocialAccount.id == account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="账号不存在")
        
        username = db_account.username
        db.delete(db_account)
        db.commit()
        
        return {
            "success": True,
            "message": f"账号 {username} 删除成功"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/accounts/stats", response_model=dict)
async def get_accounts_stats(db: Session = Depends(get_db)):
    """获取账号统计信息"""
    try:
        # 获取所有封号账号的用户名
        suspended_usernames = set(acc.username for acc in db.query(SuspendedAccount).all())
        
        total_count = db.query(SocialAccount).count()
        
        # 重新计算各种状态的账号数量，考虑suspended_accounts表
        # 封号账号数量：从suspended_accounts表获取
        suspended_count = len(suspended_usernames)
        
        # 活跃账号：status为active且不在suspended_accounts表中
        if suspended_usernames:
            active_count = db.query(SocialAccount).filter(
                SocialAccount.status == "active",
                ~SocialAccount.username.in_(suspended_usernames)
            ).count()
            
            # 不活跃账号：status为inactive且不在suspended_accounts表中
            inactive_count = db.query(SocialAccount).filter(
                SocialAccount.status == "inactive", 
                ~SocialAccount.username.in_(suspended_usernames)
            ).count()
        else:
            active_count = db.query(SocialAccount).filter(SocialAccount.status == "active").count()
            inactive_count = db.query(SocialAccount).filter(SocialAccount.status == "inactive").count()
        
        platform_stats = {}
        platforms = db.query(SocialAccount.platform).distinct().all()
        for (platform,) in platforms:
            count = db.query(SocialAccount).filter(SocialAccount.platform == platform).count()
            platform_stats[platform] = count
        
        return {
            "success": True,
            "stats": {
                "total_count": total_count,
                "active_count": active_count,
                "inactive_count": inactive_count,
                "suspended_count": suspended_count,
                "platform_stats": platform_stats
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/accounts/proxy-stats", response_model=dict)
async def get_accounts_proxy_stats(db: Session = Depends(get_db)):
    """获取账号代理使用统计"""
    try:
        # 总账号数
        total_accounts = db.query(SocialAccount).count()
        
        # 已分配代理的账号数
        accounts_with_proxy = db.query(SocialAccount).filter(SocialAccount.proxy_id.isnot(None)).count()
        
        # 未分配代理的账号数
        accounts_without_proxy = total_accounts - accounts_with_proxy
        
        # 按代理分组统计
        from sqlalchemy import func
        proxy_usage = db.query(
            Proxy.id,
            Proxy.ip,
            Proxy.port,
            Proxy.name,
            Proxy.country,
            func.count(SocialAccount.id).label('account_count')
        ).outerjoin(
            SocialAccount, Proxy.id == SocialAccount.proxy_id
        ).group_by(
            Proxy.id, Proxy.ip, Proxy.port, Proxy.name, Proxy.country
        ).all()
        
        proxy_stats = []
        for usage in proxy_usage:
            proxy_stats.append({
                "proxy_id": usage.id,
                "proxy_ip": usage.ip,
                "proxy_port": usage.port,
                "proxy_name": usage.name,
                "proxy_country": usage.country,
                "account_count": usage.account_count
            })
        
        return {
            "success": True,
            "stats": {
                "total_accounts": total_accounts,
                "accounts_with_proxy": accounts_with_proxy,
                "accounts_without_proxy": accounts_without_proxy,
                "proxy_usage": proxy_stats
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 备份状态相关的模型
class BackupStatusUpdate(BaseModel):
    backup_exported: int

class BatchBackupStatusUpdate(BaseModel):
    account_ids: List[int]
    backup_exported: int

# 先定义批量更新路由（更具体的路由）
@router.put("/api/accounts/backup-status/batch", response_model=dict)
async def batch_update_backup_status(
    batch_update: BatchBackupStatusUpdate,
    db: Session = Depends(get_db)
):
    """批量更新账号备份导出状态"""
    try:
        # 验证backup_exported值
        if batch_update.backup_exported not in [0, 1]:
            raise HTTPException(status_code=400, detail="backup_exported值必须为0或1")
        
        if not batch_update.account_ids:
            raise HTTPException(status_code=400, detail="请提供要更新的账号ID列表")
        
        updated_count = 0
        updated_usernames = []
        
        for account_id in batch_update.account_ids:
            db_account = db.query(SocialAccount).filter(SocialAccount.id == account_id).first()
            if db_account:
                db_account.backup_exported = batch_update.backup_exported
                updated_usernames.append(db_account.username)
                updated_count += 1
        
        db.commit()
        
        return {
            "success": True,
            "message": f"成功更新 {updated_count} 个账号的备份状态为 {'已导出' if batch_update.backup_exported == 1 else '未导出'}",
            "updated_count": updated_count,
            "updated_usernames": updated_usernames
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

# 然后定义单个更新路由
@router.put("/api/accounts/{account_id}/backup-status", response_model=dict)
async def update_backup_status(account_id: int, backup_update: BackupStatusUpdate, db: Session = Depends(get_db)):
    """更新账号备份导出状态"""
    try:
        # 验证backup_exported值
        if backup_update.backup_exported not in [0, 1]:
            raise HTTPException(status_code=400, detail="backup_exported值必须为0或1")
        
        db_account = db.query(SocialAccount).filter(SocialAccount.id == account_id).first()
        if not db_account:
            raise HTTPException(status_code=404, detail="账号不存在")
        
        # 更新备份状态
        db_account.backup_exported = backup_update.backup_exported
        db.commit()
        db.refresh(db_account)
        
        return {
            "success": True,
            "account_id": account_id,
            "backup_exported": backup_update.backup_exported,
            "message": f"账号 {db_account.username} 备份状态已更新为 {'已导出' if backup_update.backup_exported == 1 else '未导出'}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e)) 