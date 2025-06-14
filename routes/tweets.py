#!/usr/bin/env python3
"""
推文作品库API路由
包括推文模板、分类、图片的CRUD操作
"""

import os
import uuid
import shutil
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, asc, or_
from PIL import Image

from db.database import get_db
from db.models import TweetTemplate, TweetCategory, TweetImage
from pydantic import BaseModel

router = APIRouter(prefix="/api/tweets", tags=["推文作品库"])

# Pydantic 模型
class TweetCategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: str = "#2196f3"
    sort_order: int = 0

class TweetCategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None

class TweetTemplateCreate(BaseModel):
    title: str
    content: str
    category_id: Optional[int] = None
    tags: Optional[str] = None

class TweetTemplateUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    category_id: Optional[int] = None
    tags: Optional[str] = None
    is_favorite: Optional[int] = None

# 分类相关API
@router.get("/categories")
async def get_categories(db: Session = Depends(get_db)):
    """获取所有推文分类"""
    try:
        categories = db.query(TweetCategory).order_by(asc(TweetCategory.sort_order), asc(TweetCategory.name)).all()
        
        # 添加每个分类的推文数量
        result = []
        for category in categories:
            tweet_count = db.query(TweetTemplate).filter(
                TweetTemplate.category_id == category.id,
                TweetTemplate.status == "active"
            ).count()
            
            category_dict = {
                "id": category.id,
                "name": category.name,
                "description": category.description,
                "color": category.color,
                "sort_order": category.sort_order,
                "tweet_count": tweet_count,
                "created_time": category.created_time,
                "updated_time": category.updated_time
            }
            result.append(category_dict)
        
        return {"success": True, "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分类失败: {str(e)}")

@router.post("/categories")
async def create_category(category: TweetCategoryCreate, db: Session = Depends(get_db)):
    """创建推文分类"""
    try:
        # 检查名称是否已存在
        existing = db.query(TweetCategory).filter(TweetCategory.name == category.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="分类名称已存在")
        
        db_category = TweetCategory(**category.dict())
        db.add(db_category)
        db.commit()
        db.refresh(db_category)
        
        return {"success": True, "data": db_category, "message": "分类创建成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建分类失败: {str(e)}")

@router.put("/categories/{category_id}")
async def update_category(
    category_id: int, 
    category: TweetCategoryUpdate, 
    db: Session = Depends(get_db)
):
    """更新推文分类"""
    try:
        db_category = db.query(TweetCategory).filter(TweetCategory.id == category_id).first()
        if not db_category:
            raise HTTPException(status_code=404, detail="分类不存在")
        
        # 检查名称是否已存在（排除当前分类）
        if category.name:
            existing = db.query(TweetCategory).filter(
                TweetCategory.name == category.name,
                TweetCategory.id != category_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="分类名称已存在")
        
        # 更新字段
        for field, value in category.dict(exclude_unset=True).items():
            setattr(db_category, field, value)
        
        db.commit()
        db.refresh(db_category)
        
        return {"success": True, "data": db_category, "message": "分类更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新分类失败: {str(e)}")

@router.delete("/categories/{category_id}")
async def delete_category(category_id: int, db: Session = Depends(get_db)):
    """删除推文分类"""
    try:
        db_category = db.query(TweetCategory).filter(TweetCategory.id == category_id).first()
        if not db_category:
            raise HTTPException(status_code=404, detail="分类不存在")
        
        # 检查是否有推文使用该分类
        tweet_count = db.query(TweetTemplate).filter(TweetTemplate.category_id == category_id).count()
        if tweet_count > 0:
            raise HTTPException(status_code=400, detail=f"该分类下有 {tweet_count} 个推文，无法删除")
        
        db.delete(db_category)
        db.commit()
        
        return {"success": True, "message": "分类删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除分类失败: {str(e)}")

# 推文模板相关API
@router.get("/templates")
async def get_tweets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    is_favorite: Optional[int] = Query(None),
    sort_by: str = Query("created_time", regex="^(created_time|updated_time|use_count|title)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db)
):
    """获取推文模板列表（分页）"""
    try:
        # 构建查询
        query = db.query(TweetTemplate).filter(TweetTemplate.status == "active")
        
        # 分类筛选
        if category_id:
            query = query.filter(TweetTemplate.category_id == category_id)
        
        # 收藏筛选
        if is_favorite is not None:
            query = query.filter(TweetTemplate.is_favorite == is_favorite)
        
        # 搜索
        if search:
            search_term = f"%{search}%"
            query = query.filter(or_(
                TweetTemplate.title.like(search_term),
                TweetTemplate.content.like(search_term),
                TweetTemplate.tags.like(search_term)
            ))
        
        # 排序
        if sort_order == "desc":
            query = query.order_by(desc(getattr(TweetTemplate, sort_by)))
        else:
            query = query.order_by(asc(getattr(TweetTemplate, sort_by)))
        
        # 总数
        total = query.count()
        
        # 分页
        offset = (page - 1) * page_size
        tweets = query.offset(offset).limit(page_size).all()
        
        # 格式化结果
        result = []
        for tweet in tweets:
            # 获取分类信息
            category = None
            if tweet.category_id:
                category = db.query(TweetCategory).filter(TweetCategory.id == tweet.category_id).first()
            
            # 获取图片信息
            images = db.query(TweetImage).filter(
                TweetImage.tweet_id == tweet.id
            ).order_by(asc(TweetImage.sort_order)).all()
            
            tweet_dict = {
                "id": tweet.id,
                "title": tweet.title,
                "content": tweet.content,
                "category": {
                    "id": category.id,
                    "name": category.name,
                    "color": category.color
                } if category else None,
                "tags": tweet.tags.split(",") if tweet.tags else [],
                "is_favorite": tweet.is_favorite,
                "use_count": tweet.use_count,
                "last_used_time": tweet.last_used_time,
                "created_time": tweet.created_time,
                "updated_time": tweet.updated_time,
                "images": [{
                    "id": img.id,
                    "file_name": img.file_name,
                    "original_name": img.original_name,
                    "file_path": img.file_path,
                    "width": img.width,
                    "height": img.height,
                    "sort_order": img.sort_order
                } for img in images]
            }
            result.append(tweet_dict)
        
        return {
            "success": True,
            "data": result,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": (total + page_size - 1) // page_size
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取推文列表失败: {str(e)}")

@router.get("/templates/{tweet_id}")
async def get_tweet(tweet_id: int, db: Session = Depends(get_db)):
    """获取单个推文模板详情"""
    try:
        tweet = db.query(TweetTemplate).filter(
            TweetTemplate.id == tweet_id,
            TweetTemplate.status == "active"
        ).first()
        
        if not tweet:
            raise HTTPException(status_code=404, detail="推文不存在")
        
        # 获取分类信息
        category = None
        if tweet.category_id:
            category = db.query(TweetCategory).filter(TweetCategory.id == tweet.category_id).first()
        
        # 获取图片信息
        images = db.query(TweetImage).filter(
            TweetImage.tweet_id == tweet.id
        ).order_by(asc(TweetImage.sort_order)).all()
        
        result = {
            "id": tweet.id,
            "title": tweet.title,
            "content": tweet.content,
            "category": {
                "id": category.id,
                "name": category.name,
                "color": category.color
            } if category else None,
            "tags": tweet.tags.split(",") if tweet.tags else [],
            "is_favorite": tweet.is_favorite,
            "use_count": tweet.use_count,
            "last_used_time": tweet.last_used_time,
            "created_time": tweet.created_time,
            "updated_time": tweet.updated_time,
            "images": [{
                "id": img.id,
                "file_name": img.file_name,
                "original_name": img.original_name,
                "file_path": img.file_path,
                "width": img.width,
                "height": img.height,
                "sort_order": img.sort_order
            } for img in images]
        }
        
        return {"success": True, "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取推文详情失败: {str(e)}")

@router.post("/templates")
async def create_tweet(
    title: str = Form(...),
    content: str = Form(...),
    category_id: Optional[int] = Form(None),
    tags: Optional[str] = Form(None),
    images: List[UploadFile] = File([]),
    db: Session = Depends(get_db)
):
    """创建推文模板（支持图片上传）"""
    try:
        # 验证图片数量
        if len(images) > 4:
            raise HTTPException(status_code=400, detail="最多只能上传4张图片")
        
        # 创建推文记录
        tweet_data = TweetTemplateCreate(
            title=title,
            content=content,
            category_id=category_id,
            tags=tags
        )
        
        db_tweet = TweetTemplate(**tweet_data.dict())
        db.add(db_tweet)
        db.flush()  # 获取ID但不提交
        
        # 处理图片上传
        image_records = []
        if images and images[0].filename:  # 检查是否有实际上传的文件
            for i, image_file in enumerate(images):
                if image_file.filename:
                    image_record = await save_tweet_image(image_file, db_tweet.id, i, db)
                    if image_record:
                        image_records.append(image_record)
        
        db.commit()
        db.refresh(db_tweet)
        
        return {
            "success": True, 
            "data": {
                "id": db_tweet.id,
                "title": db_tweet.title,
                "images_count": len(image_records)
            },
            "message": "推文创建成功"
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"创建推文失败: {str(e)}")

@router.put("/templates/{tweet_id}")
async def update_tweet(
    tweet_id: int,
    tweet: TweetTemplateUpdate,
    db: Session = Depends(get_db)
):
    """更新推文模板"""
    try:
        db_tweet = db.query(TweetTemplate).filter(
            TweetTemplate.id == tweet_id,
            TweetTemplate.status == "active"
        ).first()
        
        if not db_tweet:
            raise HTTPException(status_code=404, detail="推文不存在")
        
        # 更新字段
        for field, value in tweet.dict(exclude_unset=True).items():
            setattr(db_tweet, field, value)
        
        db.commit()
        db.refresh(db_tweet)
        
        return {"success": True, "data": db_tweet, "message": "推文更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新推文失败: {str(e)}")

@router.delete("/templates/{tweet_id}")
async def delete_tweet(tweet_id: int, db: Session = Depends(get_db)):
    """删除推文模板"""
    try:
        db_tweet = db.query(TweetTemplate).filter(TweetTemplate.id == tweet_id).first()
        if not db_tweet:
            raise HTTPException(status_code=404, detail="推文不存在")
        
        # 软删除：标记为非活跃状态
        db_tweet.status = "inactive"
        db.commit()
        
        return {"success": True, "message": "推文删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除推文失败: {str(e)}")

@router.post("/templates/{tweet_id}/use")
async def use_tweet(tweet_id: int, db: Session = Depends(get_db)):
    """使用推文（增加使用次数）"""
    try:
        db_tweet = db.query(TweetTemplate).filter(
            TweetTemplate.id == tweet_id,
            TweetTemplate.status == "active"
        ).first()
        
        if not db_tweet:
            raise HTTPException(status_code=404, detail="推文不存在")
        
        # 增加使用次数并更新最后使用时间
        db_tweet.use_count += 1
        db_tweet.last_used_time = datetime.utcnow()
        
        db.commit()
        
        return {"success": True, "message": "使用次数已更新"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新使用次数失败: {str(e)}")

@router.post("/templates/{tweet_id}/images")
async def add_tweet_images(
    tweet_id: int,
    images: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """为现有推文添加图片"""
    try:
        # 验证推文是否存在
        tweet = db.query(TweetTemplate).filter(
            TweetTemplate.id == tweet_id,
            TweetTemplate.status == "active"
        ).first()
        
        if not tweet:
            raise HTTPException(status_code=404, detail="推文不存在")
        
        # 检查现有图片数量
        existing_images = db.query(TweetImage).filter(TweetImage.tweet_id == tweet_id).count()
        
        if existing_images + len(images) > 4:
            raise HTTPException(status_code=400, detail=f"推文最多只能有4张图片，当前已有{existing_images}张")
        
        # 保存新图片
        new_images = []
        for i, image_file in enumerate(images):
            if image_file.filename:
                sort_order = existing_images + i
                image_record = await save_tweet_image(image_file, tweet_id, sort_order, db)
                if image_record:
                    new_images.append(image_record)
        
        db.commit()
        
        return {
            "success": True,
            "data": {
                "added_images": len(new_images),
                "total_images": existing_images + len(new_images)
            },
            "message": f"成功添加{len(new_images)}张图片"
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"添加图片失败: {str(e)}")

@router.post("/templates/{tweet_id}/favorite")
async def toggle_favorite(tweet_id: int, db: Session = Depends(get_db)):
    """切换推文收藏状态"""
    try:
        db_tweet = db.query(TweetTemplate).filter(
            TweetTemplate.id == tweet_id,
            TweetTemplate.status == "active"
        ).first()
        
        if not db_tweet:
            raise HTTPException(status_code=404, detail="推文不存在")
        
        # 切换收藏状态
        db_tweet.is_favorite = 1 - db_tweet.is_favorite
        
        db.commit()
        
        return {
            "success": True, 
            "data": {"is_favorite": db_tweet.is_favorite},
            "message": "收藏状态已更新"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新收藏状态失败: {str(e)}")

# 图片相关API
@router.get("/images/{image_id}")
async def get_image(image_id: int, db: Session = Depends(get_db)):
    """获取推文图片"""
    try:
        image = db.query(TweetImage).filter(TweetImage.id == image_id).first()
        if not image:
            raise HTTPException(status_code=404, detail="图片不存在")
        
        # 检查文件是否存在
        if not os.path.exists(image.file_path):
            raise HTTPException(status_code=404, detail="图片文件不存在")
        
        return FileResponse(
            path=image.file_path,
            media_type=image.mime_type,
            filename=image.original_name
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取图片失败: {str(e)}")

@router.delete("/images/{image_id}")
async def delete_image(image_id: int, db: Session = Depends(get_db)):
    """删除推文图片"""
    try:
        image = db.query(TweetImage).filter(TweetImage.id == image_id).first()
        if not image:
            raise HTTPException(status_code=404, detail="图片不存在")
        
        # 删除文件
        if os.path.exists(image.file_path):
            os.remove(image.file_path)
        
        # 删除数据库记录
        db.delete(image)
        db.commit()
        
        return {"success": True, "message": "图片删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除图片失败: {str(e)}")

# 辅助函数
async def save_tweet_image(image_file: UploadFile, tweet_id: int, sort_order: int, db: Session) -> Optional[TweetImage]:
    """保存推文图片"""
    try:
        # 验证文件类型
        allowed_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if image_file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"不支持的图片格式: {image_file.content_type}")
        
        # 验证文件大小（5MB限制）
        file_size = 0
        content = await image_file.read()
        file_size = len(content)
        
        if file_size > 5 * 1024 * 1024:  # 5MB
            raise HTTPException(status_code=400, detail="图片文件大小不能超过5MB")
        
        # 生成文件名
        file_extension = os.path.splitext(image_file.filename)[1].lower()
        if not file_extension:
            file_extension = ".jpg"
        
        unique_filename = f"{uuid.uuid4().hex}{file_extension}"
        
        # 创建存储目录
        current_month = datetime.now().strftime("%Y%m")
        upload_dir = os.path.join("static", "uploads", "tweets", current_month)
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = os.path.join(upload_dir, unique_filename)
        
        # 保存文件
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 获取图片尺寸
        width, height = None, None
        try:
            with Image.open(file_path) as img:
                width, height = img.size
        except Exception:
            pass
        
        # 创建数据库记录
        image_record = TweetImage(
            tweet_id=tweet_id,
            original_name=image_file.filename,
            file_name=unique_filename,
            file_path=file_path,
            file_size=file_size,
            mime_type=image_file.content_type,
            width=width,
            height=height,
            sort_order=sort_order
        )
        
        db.add(image_record)
        return image_record
        
    except Exception as e:
        # 如果保存失败，删除已创建的文件
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        raise e 