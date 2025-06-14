"""
容器文件管理路由
包含文件上传、浏览目录、检查路径权限等功能
"""
import logging
import os
import shutil
import time
from fastapi import APIRouter, HTTPException, File, UploadFile, Form

# 配置日志
logger = logging.getLogger(__name__)
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)

router = APIRouter(tags=["container-file-management"])

# 备份文件存放目录
BACKUP_DIR = "D:/mytBackUp"

# 确保备份目录存在
os.makedirs(BACKUP_DIR, exist_ok=True)

@router.post("/save-temp-file")
async def save_temp_file(file: UploadFile = File(...), path: str = Form(...)):
    """保存上传的文件到指定路径"""
    logger.info(f"保存临时文件: {file.filename} 到 {path}")
    
    # 确保目标目录存在
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    
    try:
        # 保存文件
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"文件 {file.filename} 已保存到 {path}")
        return {"success": True, "message": "文件保存成功", "path": path}
    except Exception as e:
        logger.error(f"保存文件失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"保存文件失败: {str(e)}")
    finally:
        file.file.close()

@router.get("/browse-directories")
async def browse_directories(path: str = ""):
    """
    浏览服务器上的目录，用于导出容器时选择保存路径
    
    参数:
    path: 要浏览的路径，为空则列出根目录下的驱动器
    
    返回:
    目录列表和文件列表
    """
    try:
        # 如果路径为空，列出Windows系统下的所有驱动器
        if not path:
            import string
            from ctypes import windll
            
            drives = []
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(f"{letter}:/")
                bitmask >>= 1
                
            return {
                "success": True,
                "current_path": "",
                "parent_path": None,
                "directories": drives,
                "files": []
            }
            
        # 确保路径存在
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail=f"路径不存在: {path}")
            
        # 确保路径是目录
        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail=f"路径不是目录: {path}")
            
        # 获取目录列表和文件列表
        directories = []
        files = []
        
        # 获取父路径
        parent_path = os.path.abspath(os.path.join(path, os.pardir))
        if parent_path == path:  # 如果是根目录，则没有父路径
            parent_path = None
            
        # 列出目录和文件
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            if os.path.isdir(item_path):
                directories.append(item_path)
            else:
                files.append(item_path)
                
        return {
            "success": True,
            "current_path": path,
            "parent_path": parent_path,
            "directories": directories,
            "files": files
        }
        
    except Exception as e:
        logger.error(f"浏览目录出错: {str(e)}")
        raise HTTPException(status_code=500, detail=f"浏览目录出错: {str(e)}")

@router.get("/check-path-writable")
async def check_path_writable(path: str):
    """
    检查服务器上的路径是否可写
    
    参数:
    path: 要检查的路径
    
    返回:
    路径是否可写
    """
    try:
        # 确保路径存在，如果不存在则尝试创建
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                return {
                    "success": False,
                    "writable": False,
                    "message": f"无法创建目录: {str(e)}"
                }
                
        # 检查是否是目录
        if not os.path.isdir(path):
            return {
                "success": False,
                "writable": False,
                "message": f"路径不是目录: {path}"
            }
            
        # 尝试创建临时文件来测试写入权限
        test_file_path = os.path.join(path, f"test_write_{int(time.time())}.tmp")
        try:
            with open(test_file_path, 'w') as f:
                f.write("test")
            os.remove(test_file_path)
            return {
                "success": True,
                "writable": True,
                "message": "目录可写"
            }
        except Exception as e:
            return {
                "success": False,
                "writable": False,
                "message": f"目录不可写: {str(e)}"
            }
    except Exception as e:
        logger.error(f"检查路径可写性错误: {str(e)}")
        return {
            "success": False,
            "writable": False,
            "message": f"检查路径可写性错误: {str(e)}"
        } 