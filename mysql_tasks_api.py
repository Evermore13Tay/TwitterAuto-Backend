#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pymysql
import json
from datetime import datetime
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 数据库连接信息
DB_USER = "x"
DB_PASSWORD = "2AXR2cHjE6CPBrkz"
DB_HOST = "154.12.84.15"
DB_PORT = 6666
DB_NAME = "x"

def get_db_connection():
    """获取MySQL数据库连接"""
    try:
        connection = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        return connection
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        return None

def get_tasks(search="", status="全部", page=1, per_page=10):
    """获取任务列表（分页）"""
    connection = get_db_connection()
    if not connection:
        return {"success": False, "message": "数据库连接失败"}
    
    try:
        cursor = connection.cursor()
        
        # 构建查询条件
        where_conditions = []
        params = []
        
        if search and search.strip():
            where_conditions.append("(task_name LIKE %s OR description LIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])
        
        if status and status != "全部":
            where_conditions.append("status = %s")
            params.append(status)
        
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        # 计算总数
        count_sql = f"SELECT COUNT(*) as total FROM tasks {where_clause}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()['total']
        
        # 计算偏移量
        offset = (page - 1) * per_page
        
        # 获取任务列表
        list_sql = f"""
        SELECT id, task_name, task_type, status, priority, description, 
               params, device_ids, created_by, create_time, start_time, 
               finish_time, updated_time, error_message, result
        FROM tasks {where_clause}
        ORDER BY create_time DESC
        LIMIT %s OFFSET %s
        """
        
        cursor.execute(list_sql, params + [per_page, offset])
        tasks = cursor.fetchall()
        
        # 处理日期格式和参数反序列化
        for task in tasks:
            for date_field in ['create_time', 'start_time', 'finish_time', 'updated_time']:
                if task[date_field]:
                    task[date_field] = task[date_field].strftime('%Y-%m-%d %H:%M:%S')
            
            # 反序列化params字段
            if task.get('params') and isinstance(task['params'], str):
                try:
                    task['params'] = json.loads(task['params'])
                except json.JSONDecodeError as e:
                    logger.warning(f"任务 {task['id']} 参数反序列化失败: {e}")
                    task['params'] = {}
            elif not task.get('params'):
                task['params'] = {}
        
        return {
            "success": True,
            "tasks": tasks,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page
        }
        
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}")
        return {"success": False, "message": f"获取任务列表失败: {str(e)}"}
    finally:
        connection.close()

def create_task(task_data):
    """创建新任务"""
    connection = get_db_connection()
    if not connection:
        return {"success": False, "message": "数据库连接失败"}
    
    try:
        cursor = connection.cursor()
        
        # 处理device_ids列表
        device_ids_str = ""
        if task_data.get('device_ids'):
            device_ids_str = ",".join(map(str, task_data['device_ids']))
        
        sql = """
        INSERT INTO tasks (task_name, task_type, status, priority, description, 
                          params, device_ids, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        cursor.execute(sql, (
            task_data.get('task_name'),
            task_data.get('task_type', 'custom'),
            task_data.get('status', 'pending'),
            task_data.get('priority', '中'),
            task_data.get('description'),
            json.dumps(task_data.get('params', {})) if task_data.get('params') else None,
            device_ids_str,
            task_data.get('created_by', 'admin')
        ))
        
        connection.commit()
        task_id = cursor.lastrowid
        
        return {"success": True, "task_id": task_id, "message": "任务创建成功"}
        
    except Exception as e:
        logger.error(f"创建任务失败: {e}")
        connection.rollback()
        return {"success": False, "message": f"创建任务失败: {str(e)}"}
    finally:
        connection.close()

def update_task_status(task_id, status):
    """更新任务状态"""
    connection = get_db_connection()
    if not connection:
        return {"success": False, "message": "数据库连接失败"}
    
    try:
        cursor = connection.cursor()
        
        # 检查任务是否存在 - 增强调试
        logger.info(f"检查任务存在性: task_id={task_id}, type={type(task_id)}")
        cursor.execute("SELECT id FROM tasks WHERE id = %s", (task_id,))
        result = cursor.fetchone()
        logger.info(f"数据库查询结果: {result}")
        
        if not result:
            # 额外调试：查看数据库中实际有哪些任务ID
            cursor.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 10")
            recent_tasks = cursor.fetchall()
            logger.info(f"数据库中最近的10个任务ID: {[task['id'] for task in recent_tasks]}")
            return {"success": False, "message": "任务不存在"}
        
        # 根据状态决定是否更新特定时间字段
        if status == '运行中':
            # 开始运行时设置开始时间
            sql = "UPDATE tasks SET status = %s, start_time = CURRENT_TIMESTAMP, updated_time = CURRENT_TIMESTAMP WHERE id = %s"
        elif status in ['已完成', '失败']:
            # 完成或失败时设置完成时间
            sql = "UPDATE tasks SET status = %s, finish_time = CURRENT_TIMESTAMP, updated_time = CURRENT_TIMESTAMP WHERE id = %s"
        else:
            # 其他状态只更新状态和更新时间
            sql = "UPDATE tasks SET status = %s, updated_time = CURRENT_TIMESTAMP WHERE id = %s"
        
        cursor.execute(sql, (status, task_id))
        connection.commit()
        
        return {"success": True, "message": "任务状态更新成功"}
        
    except Exception as e:
        logger.error(f"更新任务状态失败: {e}")
        connection.rollback()
        return {"success": False, "message": f"更新任务状态失败: {str(e)}"}
    finally:
        connection.close()

def delete_task(task_id):
    """删除任务"""
    connection = get_db_connection()
    if not connection:
        return {"success": False, "message": "数据库连接失败"}
    
    try:
        cursor = connection.cursor()
        
        # 检查任务是否存在
        cursor.execute("SELECT id FROM tasks WHERE id = %s", (task_id,))
        if not cursor.fetchone():
            return {"success": False, "message": "任务不存在"}
        
        # 删除任务（外键约束会自动删除相关记录）
        cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        connection.commit()
        
        return {"success": True, "message": "任务删除成功"}
        
    except Exception as e:
        logger.error(f"删除任务失败: {e}")
        connection.rollback()
        return {"success": False, "message": f"删除任务失败: {str(e)}"}
    finally:
        connection.close()

def get_task_templates():
    """获取任务模板列表"""
    connection = get_db_connection()
    if not connection:
        return {"success": False, "message": "数据库连接失败"}
    
    try:
        cursor = connection.cursor()
        
        sql = """
        SELECT id, template_name, template_type, description, default_params, 
               is_active, created_by, created_time, updated_time
        FROM task_templates 
        WHERE is_active = 1
        ORDER BY created_time DESC
        """
        
        cursor.execute(sql)
        templates = cursor.fetchall()
        
        # 处理日期格式
        for template in templates:
            for date_field in ['created_time', 'updated_time']:
                if template[date_field]:
                    template[date_field] = template[date_field].strftime('%Y-%m-%d %H:%M:%S')
        
        return {"success": True, "templates": templates}
        
    except Exception as e:
        logger.error(f"获取任务模板失败: {e}")
        return {"success": False, "message": f"获取任务模板失败: {str(e)}"}
    finally:
        connection.close()

def get_task_statistics():
    """获取任务统计信息"""
    connection = get_db_connection()
    if not connection:
        return {"success": False, "message": "数据库连接失败"}
    
    try:
        cursor = connection.cursor()
        
        # 按状态统计
        cursor.execute("""
        SELECT status, COUNT(*) as count 
        FROM tasks 
        GROUP BY status
        """)
        status_stats = {row['status']: row['count'] for row in cursor.fetchall()}
        
        # 按类型统计
        cursor.execute("""
        SELECT task_type, COUNT(*) as count 
        FROM tasks 
        GROUP BY task_type
        """)
        type_stats = {row['task_type']: row['count'] for row in cursor.fetchall()}
        
        # 总数统计
        cursor.execute("SELECT COUNT(*) as total FROM tasks")
        total_tasks = cursor.fetchone()['total']
        
        return {
            "success": True,
            "total_tasks": total_tasks,
            "status_stats": status_stats,
            "type_stats": type_stats
        }
        
    except Exception as e:
        logger.error(f"获取任务统计失败: {e}")
        return {"success": False, "message": f"获取任务统计失败: {str(e)}"}
    finally:
        connection.close()

# 测试函数
def test_api():
    """测试API功能"""
    print("=== 测试MySQL任务API ===")
    
    # 测试获取任务列表
    print("\n1. 测试获取任务列表:")
    result = get_tasks(page=1, per_page=5)
    if result['success']:
        print(f"总任务数: {result['total']}")
        print(f"当前页任务数: {len(result['tasks'])}")
        
        if result['tasks']:
            print("前几个任务:")
            for task in result['tasks'][:3]:
                print(f"  - {task['task_name']} ({task['task_type']}) - {task['status']}")
    else:
        print(f"获取失败: {result['message']}")
    
    # 测试统计信息
    print("\n2. 测试统计信息:")
    stats = get_task_statistics()
    if stats['success']:
        print(f"总任务数: {stats.get('total_tasks', 0)}")
        print(f"状态统计: {stats.get('status_stats', {})}")
        print(f"类型统计: {stats.get('type_stats', {})}")
    else:
        print(f"统计失败: {stats['message']}")

if __name__ == "__main__":
    test_api() 