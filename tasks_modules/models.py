"""
Pydantic 模型定义
提取自原 tasks.py 文件
"""

from pydantic import BaseModel
from typing import Optional, List

class TaskCreate(BaseModel):
    task_name: str
    task_type: str = 'custom'
    status: str = 'pending'
    priority: str = '中'
    description: Optional[str] = None
    params: Optional[dict] = None
    device_ids: Optional[List[int]] = None
    created_by: str = 'admin'

class TaskStatusUpdate(BaseModel):
    status: str
