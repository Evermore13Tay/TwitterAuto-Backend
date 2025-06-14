import os
import sys
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import logging

logger = logging.getLogger(__name__)

def get_static_base_path():
    """获取静态文件目录的正确基础路径"""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller打包后的路径
        return sys._MEIPASS
    else:
        # 开发环境路径
        return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def create_static_routes(app: FastAPI):
    """配置静态文件服务 - 仅用于上传文件等基本静态资源"""
    static_base = get_static_base_path()
    static_files_dir = os.path.join(static_base, "static")

    logger.info(f"📁 Configuring static files from: {static_files_dir}")

    # 确保静态目录存在
    if not os.path.exists(static_files_dir):
        try:
            os.makedirs(static_files_dir, exist_ok=True)
            logger.info(f"✅ Created static directory: {static_files_dir}")
        except Exception as e:
            logger.error(f"❌ Failed to create static directory: {e}")
            return app

    # 挂载静态文件服务（仅用于上传等）
    try:
        app.mount("/static", StaticFiles(directory=static_files_dir), name="static")
        logger.info(f"✅ Static files mounted at /static")
    except Exception as e:
        logger.error(f"❌ Failed to mount static files: {e}")
    
    # 明确说明：这是API-only后端，前端由Electron处理
    logger.info("🚀 Backend ready: API-only mode (frontend handled by Electron)")
    return app