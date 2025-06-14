#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
添加backup_exported字段到social_accounts表
用于跟踪账号是否已经导出过备份，避免重复导出操作
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 数据库配置
DB_USER = "x"
DB_PASSWORD = "2AXR2cHjE6CPBrkz"
DB_HOST = "154.12.84.15"
DB_PORT = 6666
DB_NAME = "x"
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def add_backup_exported_field():
    """添加backup_exported字段到social_accounts表"""
    engine = create_engine(DATABASE_URL)
    connection = engine.connect()
    
    try:
        # 开始一个事务
        with connection.begin():
            # 检查backup_exported字段是否已存在
            check_columns_query = """
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = :db_name AND TABLE_NAME = 'social_accounts' 
            AND COLUMN_NAME = 'backup_exported'
            """
            result = connection.execute(text(check_columns_query), {"db_name": DB_NAME}).fetchall()
            existing_columns = [row[0] for row in result]
            
            if 'backup_exported' in existing_columns:
                logger.info("backup_exported字段已存在，无需更新")
                return True
            
            # 添加backup_exported字段
            alter_query = """
            ALTER TABLE social_accounts 
            ADD COLUMN backup_exported INT NOT NULL DEFAULT 0 
            COMMENT '是否已导出备份(0-未导出,1-已导出)'
            AFTER last_login_time
            """
            
            logger.info(f"执行SQL: {alter_query}")
            connection.execute(text(alter_query))
            
            # 添加索引
            index_query = """
            CREATE INDEX idx_backup_exported ON social_accounts(backup_exported)
            """
            
            logger.info(f"执行SQL: {index_query}")
            connection.execute(text(index_query))
            
            logger.info("backup_exported字段添加成功")
            return True
            
    except SQLAlchemyError as e:
        logger.error(f"添加backup_exported字段时出错: {e}")
        return False
    finally:
        connection.close()

def main():
    """主函数"""
    logger.info("开始添加backup_exported字段...")
    
    success = add_backup_exported_field()
    
    if success:
        logger.info("backup_exported字段添加完成！")
        logger.info("新增字段说明：")
        logger.info("- backup_exported: 是否已导出备份(0-未导出,1-已导出)")
        logger.info("- 新增索引: idx_backup_exported")
    else:
        logger.error("backup_exported字段添加失败！")
        sys.exit(1)

if __name__ == "__main__":
    main() 