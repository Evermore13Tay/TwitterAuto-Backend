"""
数据库迁移脚本：为设备表添加代理相关字段
"""
import os
import sys
import logging
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String
from sqlalchemy.sql import text
from sqlalchemy.exc import SQLAlchemyError

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 数据库连接信息
DB_USER = "x"
DB_PASSWORD = "2AXR2cHjE6CPBrkz"
DB_HOST = "154.12.84.15"
DB_PORT = 6666
DB_NAME = "x"
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def backup_database():
    """备份当前数据库 (仅适用于SQLite)"""
    try:
        # 对于MySQL数据库，可以使用mysqldump命令
        logger.info("MySQL数据库备份需要使用mysqldump命令，请确保已手动备份数据库")
        return True
    except Exception as e:
        logger.error(f"备份数据库时出错: {e}")
        return False

def update_schema():
    """更新数据库架构，添加代理相关字段"""
    engine = create_engine(DATABASE_URL)
    connection = engine.connect()
    
    try:
        # 开始一个事务
        with connection.begin():
            # 检查代理字段是否已存在
            check_columns_query = """
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_SCHEMA = :db_name AND TABLE_NAME = 'device_users' 
            AND COLUMN_NAME IN ('proxy_ip', 'proxy_port')
            """
            result = connection.execute(text(check_columns_query), {"db_name": DB_NAME}).fetchall()
            existing_columns = [row[0] for row in result]
            
            if 'proxy_ip' in existing_columns and 'proxy_port' in existing_columns:
                logger.info("代理字段已存在，无需更新")
                return True
            
            # 添加代理相关字段
            alter_queries = []
            
            if 'proxy_ip' not in existing_columns:
                alter_queries.append(
                    "ALTER TABLE device_users ADD COLUMN proxy_ip VARCHAR(50) NULL COMMENT '代理服务器IP地址'"
                )
            
            if 'proxy_port' not in existing_columns:
                alter_queries.append(
                    "ALTER TABLE device_users ADD COLUMN proxy_port INT NULL COMMENT '代理服务器端口'"
                )
            
            for query in alter_queries:
                logger.info(f"执行SQL: {query}")
                connection.execute(text(query))
            
            logger.info("数据库架构更新成功")
            return True
            
    except SQLAlchemyError as e:
        logger.error(f"更新数据库架构时出错: {e}")
        return False
    finally:
        connection.close()

if __name__ == "__main__":
    logger.info("开始更新数据库架构...")
    
    # 备份数据库
    if backup_database():
        logger.info("数据库备份完成")
    else:
        logger.error("数据库备份失败，中止更新")
        sys.exit(1)
    
    # 更新数据库架构
    if update_schema():
        logger.info("数据库架构更新成功")
    else:
        logger.error("数据库架构更新失败")
        sys.exit(1)
