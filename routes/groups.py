from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from db.database import get_db
from db.models import AccountGroup, SocialAccount

router = APIRouter(prefix="/api/groups", tags=["groups"])

# Pydantic models
class GroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: str = "#2196f3"

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None

class GroupResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    color: str
    account_count: int
    created_time: datetime
    updated_time: datetime

    class Config:
        from_attributes = True

class BatchSetGroupRequest(BaseModel):
    account_ids: List[int]
    group_id: Optional[int] = None

# API endpoints
@router.get("/", response_model=List[GroupResponse])
async def get_groups(db: Session = Depends(get_db)):
    """获取所有分组列表"""
    try:
        # 查询分组并统计账号数量
        groups_with_count = db.query(
            AccountGroup,
            func.count(SocialAccount.id).label('account_count')
        ).outerjoin(
            SocialAccount, AccountGroup.id == SocialAccount.group_id
        ).group_by(AccountGroup.id).all()
        
        result = []
        for group, account_count in groups_with_count:
            group_dict = {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "color": group.color,
                "account_count": account_count,
                "created_time": group.created_time,
                "updated_time": group.updated_time
            }
            result.append(GroupResponse(**group_dict))
        
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取分组列表失败: {str(e)}"
        )

@router.post("/", response_model=GroupResponse)
async def create_group(group: GroupCreate, db: Session = Depends(get_db)):
    """创建新分组"""
    try:
        # 检查名称是否已存在
        existing_group = db.query(AccountGroup).filter(AccountGroup.name == group.name).first()
        if existing_group:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="分组名称已存在"
            )
        
        # 创建新分组
        db_group = AccountGroup(
            name=group.name,
            description=group.description,
            color=group.color
        )
        db.add(db_group)
        db.commit()
        db.refresh(db_group)
        
        # 返回包含账号数量的响应
        group_dict = {
            "id": db_group.id,
            "name": db_group.name,
            "description": db_group.description,
            "color": db_group.color,
            "account_count": 0,
            "created_time": db_group.created_time,
            "updated_time": db_group.updated_time
        }
        
        return GroupResponse(**group_dict)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建分组失败: {str(e)}"
        )

@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(group_id: int, group: GroupUpdate, db: Session = Depends(get_db)):
    """更新分组信息"""
    try:
        # 查找分组
        db_group = db.query(AccountGroup).filter(AccountGroup.id == group_id).first()
        if not db_group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="分组不存在"
            )
        
        # 检查名称是否与其他分组冲突
        if group.name and group.name != db_group.name:
            existing_group = db.query(AccountGroup).filter(
                AccountGroup.name == group.name,
                AccountGroup.id != group_id
            ).first()
            if existing_group:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="分组名称已存在"
                )
        
        # 更新字段
        if group.name is not None:
            db_group.name = group.name
        if group.description is not None:
            db_group.description = group.description
        if group.color is not None:
            db_group.color = group.color
        
        db.commit()
        db.refresh(db_group)
        
        # 获取账号数量
        account_count = db.query(SocialAccount).filter(SocialAccount.group_id == group_id).count()
        
        group_dict = {
            "id": db_group.id,
            "name": db_group.name,
            "description": db_group.description,
            "color": db_group.color,
            "account_count": account_count,
            "created_time": db_group.created_time,
            "updated_time": db_group.updated_time
        }
        
        return GroupResponse(**group_dict)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新分组失败: {str(e)}"
        )

@router.delete("/{group_id}")
async def delete_group(group_id: int, db: Session = Depends(get_db)):
    """删除分组"""
    try:
        # 查找分组
        db_group = db.query(AccountGroup).filter(AccountGroup.id == group_id).first()
        if not db_group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="分组不存在"
            )
        
        # 将该分组下的账号设为无分组
        db.query(SocialAccount).filter(SocialAccount.group_id == group_id).update(
            {"group_id": None}
        )
        
        # 删除分组
        db.delete(db_group)
        db.commit()
        
        return {"success": True, "message": "分组删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除分组失败: {str(e)}"
        )

@router.get("/{group_id}/accounts")
async def get_group_accounts(group_id: int, db: Session = Depends(get_db)):
    """获取指定分组下的所有账号"""
    try:
        # 验证分组是否存在
        group = db.query(AccountGroup).filter(AccountGroup.id == group_id).first()
        if not group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="分组不存在"
            )
        
        # 查询分组下的所有账号
        accounts = db.query(SocialAccount).filter(SocialAccount.group_id == group_id).all()
        
        # 转换为字典格式
        account_list = []
        for account in accounts:
            account_dict = {
                "id": account.id,
                "username": account.username,
                "password": account.password,
                "secret_key": account.secret_key,
                "platform": account.platform,
                "status": account.status,
                "group_id": account.group_id,
                "created_time": account.created_time.isoformat() if account.created_time else None,
                "updated_time": account.updated_time.isoformat() if account.updated_time else None
            }
            account_list.append(account_dict)
        
        return {
            "success": True,
            "group_id": group_id,
            "group_name": group.name,
            "accounts": account_list,
            "count": len(account_list)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取分组账号失败: {str(e)}"
        )

@router.post("/batch-set")
async def batch_set_group(request: BatchSetGroupRequest, db: Session = Depends(get_db)):
    """批量设置账号分组"""
    try:
        # 验证分组是否存在（如果不是None）
        if request.group_id is not None:
            group = db.query(AccountGroup).filter(AccountGroup.id == request.group_id).first()
            if not group:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="目标分组不存在"
                )
        
        # 批量更新账号分组
        updated_count = db.query(SocialAccount).filter(
            SocialAccount.id.in_(request.account_ids)
        ).update(
            {"group_id": request.group_id},
            synchronize_session=False
        )
        
        db.commit()
        
        return {
            "success": True,
            "message": f"成功为 {updated_count} 个账号设置分组",
            "updated_count": updated_count
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"批量设置分组失败: {str(e)}"
        ) 