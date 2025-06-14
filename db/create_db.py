import pymysql
import os
from .database import Base, engine
from .models import DeviceUser
from suspended_account import SuspendedAccount
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 数据库连接信息
DB_USER = "x"
DB_PASSWORD = "2AXR2cHjE6CPBrkz"
DB_HOST = "154.12.84.15"
DB_PORT = 6666  # 作为整数
DB_NAME = "x"

def create_database():
    # 使用硬编码的数据库凭据
    logger.info(f"尝试连接到数据库服务器: 主机={DB_HOST}, 端口={DB_PORT}")
    
    # 先不指定数据库名称进行连接
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=10
    )
    
    try:
        with conn.cursor() as cursor:
            # 如果数据库不存在，则创建
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
        logger.info(f"数据库 '{DB_NAME}' 创建成功或已存在！")
    except Exception as e:
        logger.error(f"创建数据库时出错: {e}")
    finally:
        conn.close()

def create_tables():
    try:
        # 先删除已存在的 device_users 表
        DeviceUser.__table__.drop(bind=engine, checkfirst=True)
        logger.info(f"表 '{DeviceUser.__tablename__}' 成功删除（如果存在）。")

        # 创建所有表
        Base.metadata.create_all(bind=engine)
        logger.info("表创建成功！")
    except Exception as e:
        logger.error(f"创建表时出错: {e}")

if __name__ == "__main__":
    logger.info("开始数据库初始化流程...")
    create_database()
    create_tables()
    logger.info("数据库初始化完成！") 
