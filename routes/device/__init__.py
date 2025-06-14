"""
设备路由模块
整合所有设备相关的子路由
"""
from fastapi import APIRouter

# 导入所有子路由
from .crud import router as crud_router
from .sync import router as sync_router
from .container import router as container_router
from .proxy import router as proxy_router

# 创建主路由器
router = APIRouter(tags=["devices"])

# 包含所有子路由
router.include_router(crud_router)
router.include_router(sync_router)
router.include_router(container_router)
router.include_router(proxy_router) 