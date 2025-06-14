from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import logging

# 配置日志 - 只使用控制台输出
logger = logging.getLogger(__name__)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)

# 数据库连接信息
DB_USER = "x"
DB_PASSWORD = "2AXR2cHjE6CPBrkz"
DB_HOST = "154.12.84.15"
DB_PORT = "6666"
DB_NAME = "x"

# 构建数据库 URL
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# 创建引擎，设置 pool_recycle 以处理长连接
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    echo=False,  # 设置为False以减少SQL日志输出
    pool_recycle=3600,  # 连接回收时间（秒）
    pool_pre_ping=True,  # 连接前 ping 测试
    connect_args={
        "connect_timeout": 10,  # 连接超时10秒
        "read_timeout": 30,     # 读取超时30秒
        "write_timeout": 30,    # 写入超时30秒
    },
    pool_timeout=20,  # 获取连接池连接的超时时间
    max_overflow=0,   # 不允许超出连接池大小
    pool_size=5       # 连接池大小
)

# 配置SQLAlchemy的日志级别
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# 获取数据库会话的依赖项
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 安全的数据库连接包装函数（带超时）
def safe_db_operation(operation_func, timeout=15, operation_name="Database operation"):
    """
    安全执行数据库操作，带超时机制
    
    Args:
        operation_func: 数据库操作函数，该函数应该返回操作结果
        timeout: 超时时间（秒），默认15秒
        operation_name: 操作名称，用于日志记录
        
    Returns:
        操作结果，如果超时或失败则返回None
    """
    import threading
    import queue
    
    result_queue = queue.Queue()
    error_queue = queue.Queue()
    
    def db_operation():
        try:
            result = operation_func()
            result_queue.put(result)
        except Exception as e:
            error_queue.put(e)
    
    # 启动数据库操作线程
    db_thread = threading.Thread(target=db_operation)
    db_thread.daemon = True
    db_thread.start()
    db_thread.join(timeout=timeout)
    
    if db_thread.is_alive():
        logger.error(f"{operation_name} 超时（{timeout}秒）")
        return None
    elif not error_queue.empty():
        error = error_queue.get()
        logger.error(f"{operation_name} 出错: {error}")
        return None
    elif not result_queue.empty():
        return result_queue.get()
    else:
        logger.error(f"{operation_name} 失败：未知错误")
        return None 