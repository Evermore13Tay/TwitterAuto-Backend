"""
为现有数据库添加索引以优化查询性能
"""
from sqlalchemy import create_engine, text
from database import SQLALCHEMY_DATABASE_URL
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_indexes():
    """为device_users表添加索引"""
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
    
    indexes = [
        # 单列索引
        ("idx_device_users_device_ip", "device_users", ["device_ip"]),
        ("idx_device_users_box_ip", "device_users", ["box_ip"]),
        ("idx_device_users_username", "device_users", ["username"]),
        ("idx_device_users_device_index", "device_users", ["device_index"]),
        ("idx_device_users_status", "device_users", ["status"]),
        
        # 复合索引
        ("idx_device_ip_status", "device_users", ["device_ip", "status"]),
        ("idx_box_ip_status", "device_users", ["box_ip", "status"]),
        ("idx_device_ip_device_index", "device_users", ["device_ip", "device_index"]),
    ]
    
    with engine.connect() as conn:
        # 开始事务
        trans = conn.begin()
        try:
            for index_name, table_name, columns in indexes:
                try:
                    # MySQL语法：检查索引是否已存在
                    check_sql = """
                        SELECT COUNT(*) as count 
                        FROM information_schema.statistics 
                        WHERE table_schema = DATABASE() 
                        AND table_name = :table_name 
                        AND index_name = :index_name
                    """
                    result = conn.execute(text(check_sql), {
                        "table_name": table_name,
                        "index_name": index_name
                    })
                    
                    row = result.fetchone()
                    if row and row[0] > 0:  # 使用索引访问而不是字典键
                        logger.info(f"索引 {index_name} 已存在，跳过")
                        continue
                    
                    # 创建索引
                    columns_str = ", ".join(columns)
                    create_sql = f"CREATE INDEX {index_name} ON {table_name} ({columns_str})"
                    
                    conn.execute(text(create_sql))
                    logger.info(f"成功创建索引: {index_name}")
                    
                except Exception as e:
                    logger.error(f"创建索引 {index_name} 失败: {str(e)}")
                    # 继续创建其他索引
                    
            # 提交事务
            trans.commit()
            logger.info("所有索引创建完成")
            
        except Exception as e:
            trans.rollback()
            logger.error(f"索引创建过程出错，已回滚: {str(e)}")
            raise

if __name__ == "__main__":
    logger.info("开始添加数据库索引...")
    try:
        add_indexes()
        logger.info("索引添加完成！")
    except Exception as e:
        logger.error(f"索引添加失败: {str(e)}") 