from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from db.database import get_db
from db.models import Proxy, SocialAccount
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/proxies", tags=["代理管理"])

# Pydantic schemas
class ProxyBase(BaseModel):
    ip: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    proxy_type: str = "http"
    country: Optional[str] = None
    name: Optional[str] = None
    status: str = "active"

class ProxyCreate(ProxyBase):
    pass

class ProxyUpdate(BaseModel):
    ip: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    proxy_type: Optional[str] = None
    country: Optional[str] = None
    name: Optional[str] = None
    status: Optional[str] = None

class ProxyResponse(ProxyBase):
    id: int
    created_time: datetime
    updated_time: datetime
    
    class Config:
        from_attributes = True

class BatchAssignProxyRequest(BaseModel):
    account_ids: List[int]
    proxy_id: Optional[int] = None  # None表示取消分配代理

class ProxyListResponse(BaseModel):
    data: List[ProxyResponse]
    total: int

@router.get("/", response_model=ProxyListResponse)
async def get_proxies(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    country: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取代理列表"""
    try:
        query = db.query(Proxy)
        
        # 状态过滤
        if status:
            query = query.filter(Proxy.status == status)
        
        # 国家过滤
        if country:
            query = query.filter(Proxy.country == country)
        
        # 搜索过滤
        if search:
            query = query.filter(
                (Proxy.ip.contains(search)) |
                (Proxy.name.contains(search)) |
                (Proxy.username.contains(search))
            )
        
        # 总数
        total = query.count()
        
        # 分页
        offset = (page - 1) * page_size
        proxies = query.offset(offset).limit(page_size).all()
        
        return ProxyListResponse(data=proxies, total=total)
        
    except Exception as e:
        logger.error(f"获取代理列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取代理列表失败"
        )

@router.post("/", response_model=ProxyResponse)
async def create_proxy(proxy: ProxyCreate, db: Session = Depends(get_db)):
    """创建代理"""
    try:
        # 检查是否已存在相同的代理
        existing = db.query(Proxy).filter_by(
            ip=proxy.ip, 
            port=proxy.port, 
            username=proxy.username
        ).first()
        
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="相同配置的代理已存在"
            )
        
        db_proxy = Proxy(**proxy.dict())
        db.add(db_proxy)
        db.commit()
        db.refresh(db_proxy)
        
        logger.info(f"代理创建成功: {db_proxy.id}")
        return db_proxy
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"创建代理失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建代理失败"
        )

@router.get("/{proxy_id}", response_model=ProxyResponse)
async def get_proxy(proxy_id: int, db: Session = Depends(get_db)):
    """获取单个代理详情"""
    proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
    if not proxy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="代理不存在"
        )
    return proxy

@router.put("/{proxy_id}", response_model=ProxyResponse)
async def update_proxy(
    proxy_id: int, 
    proxy_update: ProxyUpdate, 
    db: Session = Depends(get_db)
):
    """更新代理"""
    try:
        db_proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
        if not db_proxy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="代理不存在"
            )
        
        # 更新字段
        update_data = proxy_update.dict(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_proxy, field, value)
        
        db.commit()
        db.refresh(db_proxy)
        
        logger.info(f"代理更新成功: {proxy_id}")
        return db_proxy
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"更新代理失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新代理失败"
        )

@router.delete("/{proxy_id}")
async def delete_proxy(proxy_id: int, db: Session = Depends(get_db)):
    """删除代理"""
    try:
        db_proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
        if not db_proxy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="代理不存在"
            )
        
        # 检查是否有账号在使用这个代理
        using_accounts = db.query(SocialAccount).filter(
            SocialAccount.proxy_id == proxy_id
        ).count()
        
        if using_accounts > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无法删除代理，还有 {using_accounts} 个账号正在使用"
            )
        
        db.delete(db_proxy)
        db.commit()
        
        logger.info(f"代理删除成功: {proxy_id}")
        return {"message": "代理删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"删除代理失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除代理失败"
        )

@router.post("/batch-assign")
async def batch_assign_proxy(
    request: BatchAssignProxyRequest, 
    db: Session = Depends(get_db)
):
    """批量分配代理给账号"""
    try:
        # 验证代理是否存在（如果指定了代理ID）
        if request.proxy_id:
            proxy = db.query(Proxy).filter(Proxy.id == request.proxy_id).first()
            if not proxy:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="指定的代理不存在"
                )
            
            if proxy.status != "active":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="代理状态不可用"
                )
        
        # 验证账号是否存在
        accounts = db.query(SocialAccount).filter(
            SocialAccount.id.in_(request.account_ids)
        ).all()
        
        if len(accounts) != len(request.account_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="部分账号不存在"
            )
        
        # 批量更新账号的代理
        updated_count = db.query(SocialAccount).filter(
            SocialAccount.id.in_(request.account_ids)
        ).update(
            {"proxy_id": request.proxy_id},
            synchronize_session=False
        )
        
        db.commit()
        
        action = "分配" if request.proxy_id else "取消分配"
        logger.info(f"批量{action}代理成功，影响账号数: {updated_count}")
        
        return {
            "message": f"批量{action}代理成功",
            "updated_count": updated_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"批量分配代理失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="批量分配代理失败"
        )

@router.get("/{proxy_id}/accounts")
async def get_proxy_accounts(
    proxy_id: int, 
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db)
):
    """获取使用指定代理的账号列表"""
    try:
        # 验证代理是否存在
        proxy = db.query(Proxy).filter(Proxy.id == proxy_id).first()
        if not proxy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="代理不存在"
            )
        
        # 查询使用该代理的账号
        query = db.query(SocialAccount).filter(SocialAccount.proxy_id == proxy_id)
        
        total = query.count()
        offset = (page - 1) * page_size
        accounts = query.offset(offset).limit(page_size).all()
        
        account_list = []
        for account in accounts:
            account_list.append({
                "id": account.id,
                "username": account.username,
                "platform": account.platform,
                "status": account.status,
                "created_time": account.created_time
            })
        
        return {
            "proxy_info": {
                "id": proxy.id,
                "ip": proxy.ip,
                "port": proxy.port,
                "name": proxy.name
            },
            "accounts": account_list,
            "total": total
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取代理账号列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取代理账号列表失败"
        )

@router.get("/stats/summary")
async def get_proxy_stats(db: Session = Depends(get_db)):
    """获取代理统计信息"""
    try:
        from sqlalchemy import func
        
        # 基本统计
        total_proxies = db.query(Proxy).count()
        active_proxies = db.query(Proxy).filter(Proxy.status == "active").count()
        
        # 使用代理的账号数 - 简化查询
        used_proxies_count = db.query(SocialAccount.proxy_id).filter(
            SocialAccount.proxy_id.isnot(None)
        ).distinct().count()
        
        # 各国家代理数量
        country_stats = db.query(
            Proxy.country, 
            func.count(Proxy.id).label('count')
        ).group_by(Proxy.country).all()
        
        return {
            "total_proxies": total_proxies,
            "active_proxies": active_proxies,
            "used_proxies": used_proxies_count,
            "unused_proxies": max(0, active_proxies - used_proxies_count),
            "country_distribution": [
                {"country": country or "未知", "count": count} 
                for country, count in country_stats
            ]
        }
        
    except Exception as e:
        logger.error(f"获取代理统计失败: {e}")
        import traceback
        logger.error(f"错误详情: {traceback.format_exc()}")
        # 返回默认值
        return {
            "total_proxies": 0,
            "active_proxies": 0,
            "used_proxies": 0,
            "unused_proxies": 0,
            "country_distribution": []
        } 