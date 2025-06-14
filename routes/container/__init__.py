"""
容器路由模块
整合所有容器相关的子路由
"""
from fastapi import APIRouter

# 导入所有子路由
from .file_mgmt import router as file_mgmt_router
from .export import router as export_router
from .management import router as management_router
from .logs import router as logs_router
from .config import router as config_router
from .reboot import router as reboot_router
from .image import router as image_router

# 创建主路由器
router = APIRouter(tags=["containers"])

# 包含所有子路由
router.include_router(file_mgmt_router)
router.include_router(export_router)
router.include_router(management_router)
router.include_router(logs_router)
router.include_router(config_router)
router.include_router(reboot_router)
router.include_router(image_router) 