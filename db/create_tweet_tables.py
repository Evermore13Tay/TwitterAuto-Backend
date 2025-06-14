#!/usr/bin/env python3
"""
创建推文作品库相关表
包括：推文分类表、推文模板表、推文图片表
"""

import os
import sys
import logging
from sqlalchemy import text

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
sys.path.insert(0, backend_dir)

from db.database import engine, SessionLocal
from db.models import TweetCategory, TweetTemplate, TweetImage, Base

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def create_tweet_tables():
    """创建推文作品库相关表"""
    try:
        logger.info("开始创建推文作品库相关表...")
        
        # 创建表
        Base.metadata.create_all(bind=engine, tables=[
            TweetCategory.__table__,
            TweetTemplate.__table__,
            TweetImage.__table__
        ])
        
        logger.info("✅ 推文作品库表创建成功")
        
        # 创建默认分类
        create_default_categories()
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 创建推文作品库表失败: {e}")
        return False

def create_default_categories():
    """创建默认的推文分类"""
    try:
        db = SessionLocal()
        
        # 检查是否已有分类
        existing_count = db.query(TweetCategory).count()
        if existing_count > 0:
            logger.info(f"已存在 {existing_count} 个推文分类，跳过默认分类创建")
            return
        
        # 创建默认分类
        default_categories = [
            {
                "name": "日常分享",
                "description": "日常生活、心情分享类推文",
                "color": "#4CAF50",
                "sort_order": 1
            },
            {
                "name": "行业资讯",
                "description": "行业新闻、资讯类推文",
                "color": "#2196F3",
                "sort_order": 2
            },
            {
                "name": "产品推广",
                "description": "产品宣传、营销类推文",
                "color": "#FF9800",
                "sort_order": 3
            },
            {
                "name": "互动问答",
                "description": "提问、投票、互动类推文",
                "color": "#9C27B0",
                "sort_order": 4
            },
            {
                "name": "节日祝福",
                "description": "节日、庆祝、祝福类推文",
                "color": "#F44336",
                "sort_order": 5
            },
            {
                "name": "其他",
                "description": "其他类型推文",
                "color": "#607D8B",
                "sort_order": 99
            }
        ]
        
        for category_data in default_categories:
            category = TweetCategory(**category_data)
            db.add(category)
        
        db.commit()
        logger.info(f"✅ 成功创建 {len(default_categories)} 个默认推文分类")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 创建默认分类失败: {e}")
    finally:
        db.close()

def create_uploads_directory():
    """创建上传文件存储目录"""
    try:
        # 创建上传目录
        uploads_dir = os.path.join(backend_dir, "static", "uploads", "tweets")
        os.makedirs(uploads_dir, exist_ok=True)
        
        # 创建按年月分组的子目录
        from datetime import datetime
        current_month = datetime.now().strftime("%Y%m")
        month_dir = os.path.join(uploads_dir, current_month)
        os.makedirs(month_dir, exist_ok=True)
        
        logger.info(f"✅ 创建上传目录: {uploads_dir}")
        return True
        
    except Exception as e:
        logger.error(f"❌ 创建上传目录失败: {e}")
        return False

def check_tables_exist():
    """检查表是否存在"""
    try:
        db = SessionLocal()
        
        # 检查各表是否存在且有数据
        tables_info = []
        
        # 检查分类表
        category_count = db.query(TweetCategory).count()
        tables_info.append(f"tweet_categories: {category_count} 条记录")
        
        # 检查推文表
        tweet_count = db.query(TweetTemplate).count()
        tables_info.append(f"tweet_templates: {tweet_count} 条记录")
        
        # 检查图片表
        image_count = db.query(TweetImage).count()
        tables_info.append(f"tweet_images: {image_count} 条记录")
        
        logger.info("📊 推文作品库表状态:")
        for info in tables_info:
            logger.info(f"  - {info}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 检查表状态失败: {e}")
        return False
    finally:
        db.close()

def main():
    """主函数"""
    logger.info("=" * 50)
    logger.info("🚀 推文作品库数据库初始化")
    logger.info("=" * 50)
    
    # 1. 创建表
    if not create_tweet_tables():
        sys.exit(1)
    
    # 2. 创建上传目录
    if not create_uploads_directory():
        sys.exit(1)
    
    # 3. 检查表状态
    if not check_tables_exist():
        sys.exit(1)
    
    logger.info("=" * 50)
    logger.info("✅ 推文作品库初始化完成！")
    logger.info("🎯 功能说明:")
    logger.info("  - 推文分类管理")
    logger.info("  - 推文模板保存")
    logger.info("  - 推文图片上传（最多4张）")
    logger.info("  - 推文标签和收藏功能")
    logger.info("  - 使用次数统计")
    logger.info("=" * 50)

if __name__ == "__main__":
    main() 