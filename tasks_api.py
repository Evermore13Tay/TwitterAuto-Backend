#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify
import sqlite3
import os
import json
from datetime import datetime

# 数据库文件路径
DB_PATH = os.path.join(os.path.dirname(__file__), 'twitter_automation.db')

def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_tasks(search_term=None, status_filter=None, page=1, per_page=10):
    """获取任务列表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 构建查询条件
        where_conditions = []
        params = []
        
        if search_term:
            where_conditions.append("task_name LIKE ?")
            params.append(f"%{search_term}%")
        
        if status_filter and status_filter != '全部':
            where_conditions.append("status = ?")
            params.append(status_filter)
        
        where_clause = " WHERE " + " AND ".join(where_conditions) if where_conditions else ""
        
        # 计算总数
        count_query = f"SELECT COUNT(*) FROM tasks{where_clause}"
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()[0]
        
        # 分页查询
        offset = (page - 1) * per_page
        query = f"""
            SELECT id, task_name, task_type, status, priority, description, 
                   params, device_ids, created_by, create_time, start_time, 
                   finish_time, error_message
            FROM tasks{where_clause} 
            ORDER BY create_time DESC 
            LIMIT ? OFFSET ?
        """
        params.extend([per_page, offset])
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        tasks = []
        for row in rows:
            task = {
                'id': row['id'],
                'taskName': row['task_name'],
                'taskType': row['task_type'],
                'status': row['status'],
                'priority': row['priority'],
                'description': row['description'],
                'params': row['params'],
                'deviceIds': row['device_ids'],
                'createdBy': row['created_by'],
                'createTime': row['create_time'],
                'startTime': row['start_time'],
                'finishTime': row['finish_time'] or '-',
                'errorMessage': row['error_message'],
                'operation': get_task_operations(row['status'])
            }
            tasks.append(task)
        
        return {
            'success': True,
            'data': {
                'tasks': tasks,
                'total': total_count,
                'page': page,
                'per_page': per_page,
                'total_pages': (total_count + per_page - 1) // per_page
            }
        }
        
    except Exception as e:
        return {'success': False, 'message': str(e)}
    finally:
        if conn:
            conn.close()

def get_task_operations(status):
    """根据任务状态返回可执行的操作"""
    operations_map = {
        '运行中': ['暂停', '删除'],
        '已完成': ['重启', '删除'],
        '已暂停': ['启动', '删除'],
        '失败': ['重试', '删除'],
        'pending': ['启动', '删除']
    }
    return operations_map.get(status, ['删除'])

def create_task(task_data):
    """创建新任务"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO tasks (task_name, task_type, status, priority, description, params, device_ids, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task_data.get('task_name'),
            task_data.get('task_type', 'custom'),
            task_data.get('status', 'pending'),
            task_data.get('priority', '中'),
            task_data.get('description'),
            json.dumps(task_data.get('params', {})),
            ','.join(map(str, task_data.get('device_ids', []))),
            task_data.get('created_by', 'admin')
        ))
        
        task_id = cursor.lastrowid
        conn.commit()
        
        return {'success': True, 'task_id': task_id, 'message': '任务创建成功'}
        
    except Exception as e:
        return {'success': False, 'message': str(e)}
    finally:
        if conn:
            conn.close()

def update_task_status(task_id, new_status):
    """更新任务状态并实时广播状态变化"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 先获取任务信息用于广播
        cursor.execute("SELECT task_name FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        task_name = task_row['task_name'] if task_row else f"任务{task_id}"
        
        update_data = {
            'status': new_status
        }
        
        if new_status == '运行中':
            update_data['start_time'] = datetime.now().isoformat()
        elif new_status in ['已完成', '失败', '已暂停']:
            update_data['finish_time'] = datetime.now().isoformat()
        
        set_clause = ', '.join([f"{key} = ?" for key in update_data.keys()])
        query = f"UPDATE tasks SET {set_clause} WHERE id = ?"
        
        cursor.execute(query, list(update_data.values()) + [task_id])
        conn.commit()
        
        if cursor.rowcount > 0:
            # 🚀 实时广播任务状态变化
            try:
                # 导入全局管理器并广播状态变化
                import asyncio
                from utils.connection import manager
                
                # 如果当前不在异步上下文中，创建任务来执行广播
                try:
                    loop = asyncio.get_running_loop()
                    # 在现有的事件循环中创建任务
                    loop.create_task(manager.broadcast_task_status_change(
                        task_id=str(task_id),
                        new_status=new_status,
                        task_name=task_name
                    ))
                except RuntimeError:
                    # 没有运行的事件循环，创建新的
                    asyncio.run(manager.broadcast_task_status_change(
                        task_id=str(task_id),
                        new_status=new_status,
                        task_name=task_name
                    ))
                    
                print(f"✅ 已广播任务状态变化: {task_name} (ID: {task_id}) -> {new_status}")
                
            except Exception as broadcast_error:
                print(f"⚠️ 广播任务状态失败: {broadcast_error}")
                # 广播失败不影响状态更新的成功
            
            return {'success': True, 'message': '任务状态更新成功'}
        else:
            return {'success': False, 'message': '任务不存在'}
            
    except Exception as e:
        return {'success': False, 'message': str(e)}
    finally:
        if conn:
            conn.close()

def delete_task(task_id):
    """删除任务"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        
        if cursor.rowcount > 0:
            return {'success': True, 'message': '任务删除成功'}
        else:
            return {'success': False, 'message': '任务不存在'}
            
    except Exception as e:
        return {'success': False, 'message': str(e)}
    finally:
        if conn:
            conn.close()

def get_task_templates():
    """获取任务模板列表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, template_name, template_type, description, default_params, 
                   is_active, created_by, created_time
            FROM task_templates 
            WHERE is_active = 1
            ORDER BY created_time DESC
        ''')
        
        rows = cursor.fetchall()
        templates = []
        
        for row in rows:
            template = {
                'id': row['id'],
                'templateName': row['template_name'],
                'templateType': row['template_type'],
                'description': row['description'],
                'defaultParams': json.loads(row['default_params']) if row['default_params'] else {},
                'isActive': row['is_active'],
                'createdBy': row['created_by'],
                'createdTime': row['created_time']
            }
            templates.append(template)
        
        return {'success': True, 'data': templates}
        
    except Exception as e:
        return {'success': False, 'message': str(e)}
    finally:
        if conn:
            conn.close()

def get_task_statistics():
    """获取任务统计信息"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 获取各状态任务数量
        cursor.execute('''
            SELECT status, COUNT(*) as count
            FROM tasks
            GROUP BY status
        ''')
        
        status_stats = {}
        for row in cursor.fetchall():
            status_stats[row['status']] = row['count']
        
        # 获取总任务数
        cursor.execute("SELECT COUNT(*) as total FROM tasks")
        total_tasks = cursor.fetchone()['total']
        
        # 获取今日创建的任务数
        cursor.execute('''
            SELECT COUNT(*) as today_count
            FROM tasks
            WHERE DATE(create_time) = DATE('now')
        ''')
        today_tasks = cursor.fetchone()['today_count']
        
        return {
            'success': True,
            'data': {
                'total_tasks': total_tasks,
                'today_tasks': today_tasks,
                'status_stats': status_stats,
                'running_tasks': status_stats.get('运行中', 0),
                'completed_tasks': status_stats.get('已完成', 0),
                'failed_tasks': status_stats.get('失败', 0),
                'paused_tasks': status_stats.get('已暂停', 0)
            }
        }
        
    except Exception as e:
        return {'success': False, 'message': str(e)}
    finally:
        if conn:
            conn.close()

# Flask路由处理函数（如果需要作为独立API服务）
def create_tasks_api(app):
    """创建任务管理API路由"""
    
    @app.route('/api/tasks', methods=['GET'])
    def api_get_tasks():
        search_term = request.args.get('search', '')
        status_filter = request.args.get('status', '全部')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        
        result = get_tasks(search_term, status_filter, page, per_page)
        return jsonify(result)
    
    @app.route('/api/tasks', methods=['POST'])
    def api_create_task():
        task_data = request.get_json()
        result = create_task(task_data)
        return jsonify(result)
    
    @app.route('/api/tasks/<int:task_id>/status', methods=['PUT'])
    def api_update_task_status(task_id):
        data = request.get_json()
        new_status = data.get('status')
        result = update_task_status(task_id, new_status)
        return jsonify(result)
    
    @app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
    def api_delete_task(task_id):
        result = delete_task(task_id)
        return jsonify(result)
    
    @app.route('/api/tasks/templates', methods=['GET'])
    def api_get_task_templates():
        result = get_task_templates()
        return jsonify(result)
    
    @app.route('/api/tasks/statistics', methods=['GET'])
    def api_get_task_statistics():
        result = get_task_statistics()
        return jsonify(result)

if __name__ == "__main__":
    # 测试API函数
    print("测试任务管理API...")
    
    # 获取任务列表
    result = get_tasks()
    print("任务列表:", result)
    
    # 获取统计信息
    stats = get_task_statistics()
    print("统计信息:", stats) 