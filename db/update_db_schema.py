import os
import sys
import logging
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, UniqueConstraint
from sqlalchemy.sql import text
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 数据库连接信息
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///./twitter_automation.db')

def backup_database():
    """备份当前数据库"""
    import shutil
    from datetime import datetime
    
    db_path = "./twitter_automation.db"
    if os.path.exists(db_path):
        backup_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"./twitter_automation_backup_{backup_time}.db"
        shutil.copy2(db_path, backup_path)
        logger.info(f"数据库已备份到: {backup_path}")
        return True
    else:
        logger.warning(f"找不到数据库文件: {db_path}，跳过备份")
        return False

def update_schema():
    """更新数据库架构，将端口唯一约束改为设备IP+端口的组合唯一约束"""
    engine = create_engine(DATABASE_URL)
    metadata = MetaData()
    connection = engine.connect()
    
    try:
        # 开始一个事务
        with connection.begin():
            # 1. 查看是否已经有组合唯一约束
            existing_constraints = connection.execute(text("""
                SELECT name FROM sqlite_master 
                WHERE type='index' AND 
                (name='uix_device_ip_u2_port' OR name='uix_device_ip_myt_rpc_port')
            """)).fetchall()
            
            if len(existing_constraints) >= 2:
                logger.info("检测到组合唯一约束已存在，跳过更新")
                return True
            
            # 2. 创建临时表
            connection.execute(text("""
                CREATE TABLE device_users_new (
                    id VARCHAR(36) PRIMARY KEY,
                    device_ip VARCHAR(15) NOT NULL,
                    u2_port INTEGER,
                    myt_rpc_port INTEGER,
                    username VARCHAR(50),
                    password VARCHAR(50),
                    secret_key VARCHAR(16),
                    device_name VARCHAR(100) NOT NULL UNIQUE,
                    device_index INTEGER,
                    CONSTRAINT uix_device_ip_u2_port UNIQUE (device_ip, u2_port),
                    CONSTRAINT uix_device_ip_myt_rpc_port UNIQUE (device_ip, myt_rpc_port)
                )
            """))
            
            # 3. 复制数据
            connection.execute(text("""
                INSERT INTO device_users_new 
                SELECT id, device_ip, u2_port, myt_rpc_port, username, password, secret_key, device_name, device_index
                FROM device_users
            """))
            
            # 4. 删除旧表
            connection.execute(text("DROP TABLE device_users"))
            
            # 5. 重命名新表
            connection.execute(text("ALTER TABLE device_users_new RENAME TO device_users"))
            
            # 6. 创建索引
            connection.execute(text("CREATE INDEX idx_device_users_device_ip ON device_users(device_ip)"))
            
            logger.info("成功更新数据库架构，添加了组合唯一约束")
            return True
            
    except SQLAlchemyError as e:
        logger.error(f"更新数据库架构时出错: {str(e)}")
        return False
    finally:
        connection.close()

def check_conflicts():
    """检查现有数据中是否有可能冲突的记录"""
    engine = create_engine(DATABASE_URL)
    connection = engine.connect()
    
    try:
        # 查找相同IP下有相同u2_port的记录
        u2_conflicts = connection.execute(text("""
            SELECT d1.device_name, d2.device_name, d1.device_ip, d1.u2_port
            FROM device_users d1
            JOIN device_users d2 ON d1.device_ip = d2.device_ip 
                AND d1.u2_port = d2.u2_port 
                AND d1.id < d2.id
            WHERE d1.u2_port IS NOT NULL
        """)).fetchall()
        
        # 查找相同IP下有相同myt_rpc_port的记录
        rpc_conflicts = connection.execute(text("""
            SELECT d1.device_name, d2.device_name, d1.device_ip, d1.myt_rpc_port
            FROM device_users d1
            JOIN device_users d2 ON d1.device_ip = d2.device_ip 
                AND d1.myt_rpc_port = d2.myt_rpc_port 
                AND d1.id < d2.id
            WHERE d1.myt_rpc_port IS NOT NULL
        """)).fetchall()
        
        if u2_conflicts:
            logger.warning(f"发现 {len(u2_conflicts)} 个相同IP下有相同u2_port的冲突:")
            for conflict in u2_conflicts:
                logger.warning(f"  设备 '{conflict[0]}' 和 '{conflict[1]}' 在IP {conflict[2]} 下使用相同的u2_port: {conflict[3]}")
            
        if rpc_conflicts:
            logger.warning(f"发现 {len(rpc_conflicts)} 个相同IP下有相同myt_rpc_port的冲突:")
            for conflict in rpc_conflicts:
                logger.warning(f"  设备 '{conflict[0]}' 和 '{conflict[1]}' 在IP {conflict[2]} 下使用相同的myt_rpc_port: {conflict[3]}")
        
        return len(u2_conflicts) + len(rpc_conflicts)
    
    except SQLAlchemyError as e:
        logger.error(f"检查冲突时出错: {str(e)}")
        return -1
    finally:
        connection.close()

def resolve_conflicts():
    """解决相同IP下端口冲突的问题"""
    engine = create_engine(DATABASE_URL)
    connection = engine.connect()
    
    try:
        with connection.begin():
            # 解决u2_port冲突
            u2_conflicts = connection.execute(text("""
                SELECT d1.id, d1.device_name, d1.device_ip, d1.u2_port
                FROM device_users d1
                JOIN (
                    SELECT device_ip, u2_port, COUNT(*) as cnt
                    FROM device_users
                    WHERE u2_port IS NOT NULL
                    GROUP BY device_ip, u2_port
                    HAVING cnt > 1
                ) conflict ON d1.device_ip = conflict.device_ip AND d1.u2_port = conflict.u2_port
                ORDER BY d1.device_ip, d1.u2_port, d1.id
            """)).fetchall()
            
            # 为冲突设备分配新端口
            base_u2_port = 5001
            for conflict in u2_conflicts:
                device_id = conflict[0]
                device_name = conflict[1]
                device_ip = conflict[2]
                
                # 查找未使用的端口
                while True:
                    existing = connection.execute(text(
                        "SELECT 1 FROM device_users WHERE device_ip = :ip AND u2_port = :port"
                    ), {"ip": device_ip, "port": base_u2_port}).fetchone()
                    
                    if not existing:
                        break
                    base_u2_port += 1
                
                # 更新端口
                connection.execute(text(
                    "UPDATE device_users SET u2_port = :new_port WHERE id = :id"
                ), {"new_port": base_u2_port, "id": device_id})
                
                logger.info(f"已解决冲突: 设备 '{device_name}' (IP: {device_ip}) 的u2_port已更新为 {base_u2_port}")
                base_u2_port += 1
            
            # 解决myt_rpc_port冲突
            rpc_conflicts = connection.execute(text("""
                SELECT d1.id, d1.device_name, d1.device_ip, d1.myt_rpc_port
                FROM device_users d1
                JOIN (
                    SELECT device_ip, myt_rpc_port, COUNT(*) as cnt
                    FROM device_users
                    WHERE myt_rpc_port IS NOT NULL
                    GROUP BY device_ip, myt_rpc_port
                    HAVING cnt > 1
                ) conflict ON d1.device_ip = conflict.device_ip AND d1.myt_rpc_port = conflict.myt_rpc_port
                ORDER BY d1.device_ip, d1.myt_rpc_port, d1.id
            """)).fetchall()
            
            # 为冲突设备分配新端口
            base_rpc_port = 11001
            for conflict in rpc_conflicts:
                device_id = conflict[0]
                device_name = conflict[1]
                device_ip = conflict[2]
                
                # 查找未使用的端口
                while True:
                    existing = connection.execute(text(
                        "SELECT 1 FROM device_users WHERE device_ip = :ip AND myt_rpc_port = :port"
                    ), {"ip": device_ip, "port": base_rpc_port}).fetchone()
                    
                    if not existing:
                        break
                    base_rpc_port += 1
                
                # 更新端口
                connection.execute(text(
                    "UPDATE device_users SET myt_rpc_port = :new_port WHERE id = :id"
                ), {"new_port": base_rpc_port, "id": device_id})
                
                logger.info(f"已解决冲突: 设备 '{device_name}' (IP: {device_ip}) 的myt_rpc_port已更新为 {base_rpc_port}")
                base_rpc_port += 1
            
            return len(u2_conflicts) + len(rpc_conflicts)
            
    except SQLAlchemyError as e:
        logger.error(f"解决冲突时出错: {str(e)}")
        return -1
    finally:
        connection.close()

if __name__ == "__main__":
    # 显示操作说明
    print("""
数据库更新工具 - 端口唯一性约束更新

此工具将更新设备数据库架构，将u2_port和myt_rpc_port的全局唯一约束
修改为仅在相同IP地址下的唯一约束，以支持不同IP下使用相同端口的设备。

操作步骤:
1. 检查现有数据是否有冲突
2. 备份当前数据库
3. 解决数据冲突(如有)
4. 更新数据库架构

注意: 请确保更新前已关闭所有相关应用程序，以防止数据库被锁定。
    """)
    
    # 询问用户是否继续
    response = input("是否继续更新数据库? (y/n): ").strip().lower()
    if response != 'y':
        print("已取消操作。")
        sys.exit(0)
    
    # 检查冲突
    print("\n==== 步骤1: 检查数据冲突 ====")
    conflict_count = check_conflicts()
    if conflict_count < 0:
        print("无法检查冲突，操作已终止。")
        sys.exit(1)
    elif conflict_count > 0:
        print(f"发现 {conflict_count} 个端口冲突。")
    else:
        print("未发现数据冲突。")
    
    # 备份数据库
    print("\n==== 步骤2: 备份数据库 ====")
    if backup_database():
        print("数据库备份完成。")
    else:
        response = input("备份失败或数据库不存在，是否继续? (y/n): ").strip().lower()
        if response != 'y':
            print("已取消操作。")
            sys.exit(0)
    
    # 解决冲突
    if conflict_count > 0:
        print("\n==== 步骤3: 解决数据冲突 ====")
        resolved_count = resolve_conflicts()
        if resolved_count < 0:
            print("解决冲突失败，操作已终止。")
            sys.exit(1)
        elif resolved_count > 0:
            print(f"已成功解决 {resolved_count} 个冲突。")
        
        # 再次检查冲突
        remaining_conflicts = check_conflicts()
        if remaining_conflicts > 0:
            print(f"警告: 仍有 {remaining_conflicts} 个未解决的冲突。")
            response = input("是否继续更新数据库架构? (y/n): ").strip().lower()
            if response != 'y':
                print("已取消操作。")
                sys.exit(0)
    
    # 更新数据库架构
    print("\n==== 步骤4: 更新数据库架构 ====")
    if update_schema():
        print("数据库架构已成功更新!")
    else:
        print("更新数据库架构失败!")
        sys.exit(1)
    
    print("\n==== 数据库更新完成 ====")
    print("现在设备端口的唯一性限制仅在相同IP地址下生效，不同IP地址可以使用相同的端口。")
    print("数据库已经准备好接受来自不同IP地址的设备信息。") 