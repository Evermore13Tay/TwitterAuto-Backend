# backend/main.py
import os
import sys
import time # time 模块通常不需要显式导入，datetime 已经导入
from datetime import datetime
import multiprocessing # <--- 确保此导入存在
# 添加信号处理相关导入
import signal
import atexit
import threading

# --- 详细文件日志记录 ---
_log_file_dir = "."
if hasattr(sys, '_MEIPASS'):
    _log_file_dir = os.path.dirname(sys.executable) # For bundled app, log next to exe
else:
    _log_file_dir = os.path.dirname(os.path.abspath(__file__)) # For dev, log next to main.py
_trace_log_path = os.path.join(_log_file_dir, "DETAILED_IMPORT_TRACE.log")

def write_trace(message):
    try:
        with open(_trace_log_path, "a", encoding="utf-8") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"[{timestamp}] {message}\n")
            f.flush()
    except Exception:
        pass

write_trace(f"--- Script started. Python Executable: {sys.executable} ---")

# Windows控制台设置 - 防止控制台选择模式导致的阻塞
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # 获取控制台句柄
        console_handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        # 获取当前控制台模式
        old_mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(console_handle, ctypes.byref(old_mode))
        # 禁用快速编辑模式 (ENABLE_QUICK_EDIT_MODE = 0x0040)
        new_mode = old_mode.value & ~0x0040
        # 设置新的控制台模式
        kernel32.SetConsoleMode(console_handle, new_mode)
        write_trace("Windows控制台快速编辑模式已禁用，避免意外阻塞")
    except Exception as e:
        write_trace(f"设置Windows控制台模式失败: {e}")
write_trace(f"sys.path: {str(sys.path)}")
write_trace(f"Current Working Directory: {os.getcwd()}")
if hasattr(sys, '_MEIPASS'):
    write_trace(f"_MEIPASS Bundle Directory: {sys._MEIPASS}")
else:
    write_trace("Not running from PyInstaller bundle (no _MEIPASS).")


write_trace("Attempting to import: asyncio")
import asyncio
write_trace("Successfully imported: asyncio")

write_trace("Attempting to import: logging")
import logging
write_trace("Successfully imported: logging")

write_trace("Attempting to import: socket")
import socket
write_trace("Successfully imported: socket")

write_trace("Attempting to import: FastAPI, Request from fastapi")
from fastapi import FastAPI, Request
write_trace("Successfully imported: FastAPI, Request")

write_trace("Attempting to import: CORSMiddleware from fastapi.middleware.cors")
from fastapi.middleware.cors import CORSMiddleware
write_trace("Successfully imported: CORSMiddleware")

write_trace("Attempting to import: ThreadPoolExecutor from concurrent.futures")
from concurrent.futures import ThreadPoolExecutor
write_trace("Successfully imported: ThreadPoolExecutor")

write_trace("Attempting to import: engine, Base from database")
from db.database import engine, Base
write_trace("Successfully imported: engine, Base from database")

write_trace("Attempting to import: routes modules (device_routes, etc.)")
from routes import login_routes, interaction_routes, websocket_routes, change_profile_routes, change_signature_routes, change_nickname_routes, follow_routes, post_tweet_routes
from routes.device import router as device_router
from routes.device.sync import router_no_prefix as device_sync_direct_router
from routes.device.connection import router as device_connection_router
from routes.container import router as container_router
from routes.tasks import router as tasks_router
from routes.accounts import router as accounts_router
from routes.box_ips import router as box_ips_router
from routes.proxies import router as proxies_router
from routes.integrated_operation_routes import router as integrated_operation_router
write_trace("Successfully imported: basic route modules")

# groups_router will be imported after database initialization

write_trace("Attempting to import: create_static_routes from routes.static_routes")
from routes.static_routes import create_static_routes
write_trace("Successfully imported: create_static_routes")

write_trace("Attempting to import: get_and_combine_data from getDevice")
from getDevice import get_and_combine_data # Assuming getDevice.py is in PYTHONPATH or same dir
write_trace("Successfully imported: get_and_combine_data")

write_trace("Attempting to import: twitter_polling from api")
from api import twitter_polling # Assuming api is a package
write_trace("Successfully imported: twitter_polling")

write_trace("--- All initial imports attempted. Proceeding with script... ---")


write_trace("Setting up configuration parameters (DEVICE_API_BASE_URL, DEVICE_INITIAL_IP)...")
DEVICE_API_BASE_URL = os.environ.get("DEVICE_API_BASE_URL", "http://127.0.0.1:5000")
DEVICE_INITIAL_IP = os.environ.get("DEVICE_INITIAL_IP", "192.168.8.74")
write_trace("Configuration parameters set.")

write_trace("Attempting to configure application logging...")
try:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler() # Streams to console
        ]
    )
    logger = logging.getLogger("TwitterAutomationAPI")
    write_trace("Application logging configured via basicConfig.")

    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    write_trace("Set sqlalchemy.engine log level to WARNING.")
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    write_trace("Set urllib3 log level to WARNING.")
    logging.getLogger('uvicorn').setLevel(logging.WARNING)
    write_trace("Set uvicorn log level to WARNING (pre-run).")
    logging.getLogger('fastapi').setLevel(logging.WARNING)
    write_trace("Set fastapi log level to WARNING.")
    write_trace("Third-party log levels adjusted.")
except Exception as e:
    write_trace(f"Error during logging setup: {e!r}")

write_trace("Creating FastAPI app instance...")
app = FastAPI() # app 实例在这里创建
write_trace("FastAPI app instance created.")

# 全局变量，用于优雅关闭
is_shutting_down = False
shutdown_lock = threading.Lock()

def setup_graceful_shutdown():
    """设置优雅关闭处理器"""
    global is_shutting_down
    
    def signal_handler(signum, frame):
        global is_shutting_down
        with shutdown_lock:
            if is_shutting_down:
                write_trace("强制退出信号已接收，立即退出")
                os._exit(1)
            
            is_shutting_down = True
            write_trace(f"接收到停止信号 {signum}，开始优雅关闭...")
            
            try:
                # 设置5秒超时，强制退出
                def force_exit():
                    time.sleep(5)
                    write_trace("优雅关闭超时，强制退出")
                    os._exit(1)
                
                # 启动强制退出定时器
                force_exit_thread = threading.Thread(target=force_exit, daemon=True)
                force_exit_thread.start()
                
                # 关闭线程池
                if 'executor' in globals():
                    write_trace("正在关闭线程池...")
                    executor.shutdown(wait=False)
                    write_trace("线程池已关闭")
                
                # 正常退出
                write_trace("优雅关闭完成")
                sys.exit(0)
                
            except Exception as e:
                write_trace(f"优雅关闭过程中出错: {e}")
                os._exit(1)
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 注册退出清理函数
    atexit.register(lambda: write_trace("程序正常退出"))
    
    write_trace("优雅关闭处理器已设置")

# 在创建 FastAPI app 后立即设置
setup_graceful_shutdown()

def get_base_path():
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    else:
        return os.path.abspath(os.path.dirname(__file__))

BASE_PATH = get_base_path()
write_trace(f"Application base path (BASE_PATH): {BASE_PATH}")
if 'logger' in locals():
    logger.info(f"Application base path (BASE_PATH): {BASE_PATH}")


def init_db():
    write_trace("Attempting to initialize database (create_all)...")
    try:
        Base.metadata.create_all(bind=engine)
        write_trace("Database tables created successfully via Base.metadata.create_all.")
        if 'logger' in locals():
            logger.info("Database tables created successfully")
    except Exception as e:
        write_trace(f"Error creating database tables: {e!r}")
        if 'logger' in locals():
            logger.error(f"Error creating database tables: {e}")
        raise

write_trace("Calling init_db()...")
try:
    init_db() # 数据库初始化
    write_trace("init_db() called successfully.")
except Exception as e:
    write_trace(f"Exception caught from init_db() call: {e!r}")

# Import groups_router after database initialization
write_trace("Importing groups_router after database initialization...")
try:
    from routes.groups import router as groups_router
    write_trace("Successfully imported groups_router after database init.")
except Exception as e:
    write_trace(f"Error importing groups_router: {e!r}")
    groups_router = None

write_trace("Adding CORS middleware...")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)
write_trace("CORS middleware added.")

write_trace("Creating ThreadPoolExecutor...")
executor = ThreadPoolExecutor(max_workers=10)
write_trace("ThreadPoolExecutor created.")

# startup_event 保持不变，除非您想现在就切换到 lifespan
write_trace("Defining FastAPI startup_event...")
@app.on_event("startup")
async def startup_event():
    write_trace("FastAPI startup_event triggered.")
    if 'logger' in locals():
        logger.info("应用启动中...")
        logger.info(f"使用API基础URL: {DEVICE_API_BASE_URL}")
        logger.info(f"使用初始列表IP: {DEVICE_INITIAL_IP}")
    else:
        write_trace("Logger not available in startup_event. Logging API URL and IP to trace.")
        write_trace(f"API_BASE_URL: {DEVICE_API_BASE_URL}")
        write_trace(f"DEVICE_INITIAL_IP: {DEVICE_INITIAL_IP}")

    try:
        hostname = socket.gethostname()
        write_trace(f"Server hostname: {hostname}")
        if 'logger' in locals(): logger.info(f"服务器主机名: {hostname}")
        
        addresses = socket.getaddrinfo(hostname, None)
        logged_ips = set()
        for addr in addresses:
            ip_address = addr[4][0]
            if ip_address not in logged_ips:
                write_trace(f"Server listening on IP: {ip_address}")
                if 'logger' in locals(): logger.info(f"服务器正在监听IP: {ip_address}")
                logged_ips.add(ip_address)
        write_trace("Server listening on all interfaces (0.0.0.0) port 8000 (explicit log).")
        if 'logger' in locals(): logger.info("服务器正在监听所有接口 (0.0.0.0) 的 8000 端口")
    except socket.gaierror as e_gaierror:
        write_trace(f"Socket gaierror getting server IP: {e_gaierror!r}")
        if 'logger' in locals(): logger.warning("无法自动获取服务器IP地址。请检查网络配置。服务器正在监听 0.0.0.0:8000")
    except Exception as e_ip:
        write_trace(f"Error getting server IP: {e_ip!r}")
        if 'logger' in locals(): 
            logger.error(f"获取服务器IP时出错: {e_ip}")
            logger.info("服务器正在监听所有接口 (0.0.0.0) 的 8000 端口")

    write_trace("Device info auto-get disabled. Application startup tasks complete in startup_event.")
    if 'logger' in locals(): logger.info("已禁用自动获取设备信息，应用启动完成")
write_trace("FastAPI startup_event defined.")

write_trace("Including routers...")
try:
    write_trace("Including device_router...")
    app.include_router(device_router, prefix="")
    write_trace("Including device_sync_direct_router...")
    app.include_router(device_sync_direct_router, prefix="")  # 添加不带前缀的设备同步路由
    write_trace("Including device_connection_router...")
    app.include_router(device_connection_router, prefix="")  # 添加设备连接测试路由
    write_trace("Including container_router...")
    app.include_router(container_router, prefix="")
    write_trace("Including login_routes.router...")
    app.include_router(login_routes.router, prefix="")
    write_trace("Including interaction_routes.router...")
    app.include_router(interaction_routes.router, prefix="")
    write_trace("Including websocket_routes.router...")
    app.include_router(websocket_routes.router, prefix="")
    write_trace("Including change_profile_routes.router...")
    app.include_router(change_profile_routes.router, prefix="")
    write_trace("Including change_signature_routes.router...")
    app.include_router(change_signature_routes.router, prefix="")
    write_trace("Including change_nickname_routes.router...")
    app.include_router(change_nickname_routes.router, prefix="")
    write_trace("Including follow_routes.router...")
    app.include_router(follow_routes.router, prefix="")
    write_trace("Including post_tweet_routes.router...")
    app.include_router(post_tweet_routes.router, prefix="")
    write_trace("Including twitter_polling.router...")
    app.include_router(twitter_polling.router, prefix="/api")
    write_trace("Including tasks_router...")
    app.include_router(tasks_router, prefix="")
    write_trace("Including accounts_router...")
    app.include_router(accounts_router, prefix="")
    write_trace("Including proxies_router...")
    app.include_router(proxies_router, prefix="")
    write_trace("Including box_ips_router...")
    app.include_router(box_ips_router, prefix="")
    
    write_trace("About to include groups_router...")
    if groups_router is not None:
        write_trace(f"groups_router info: {groups_router}")
        write_trace(f"groups_router routes count: {len(groups_router.routes)}")
        app.include_router(groups_router, prefix="")
        write_trace("✅ Successfully included groups_router!")
    else:
        write_trace("❌ groups_router is None, skipping inclusion.")

    # 添加新的更新设备代理API路由
    write_trace("Including update_device_proxy_router...")
    from api import update_device_proxy_router
    app.include_router(update_device_proxy_router, prefix="")
    
    # 添加推文作品库API路由
    write_trace("Including tweets_router...")
    from routes.tweets import router as tweets_router
    app.include_router(tweets_router, prefix="")
    write_trace("Successfully included tweets_router!")
    
    # 添加一体化操作API路由
    write_trace("Including integrated_operation_router...")
    app.include_router(integrated_operation_router, prefix="")
    write_trace("Successfully included integrated_operation_router!")
    
    write_trace("All primary routers included.")
except Exception as e:
    write_trace(f"Error including primary routers: {e!r}")
    import traceback
    write_trace(f"Traceback: {traceback.format_exc()}")


write_trace("Attempting to create static routes...")
try:
    static_router_or_app_result = create_static_routes(app)
    write_trace(f"create_static_routes called. Result type: {type(static_router_or_app_result)}")
except Exception as e:
    write_trace(f"Error calling create_static_routes: {e!r}")


write_trace("Processing uploads directory...")
try:
    static_dir_for_uploads = os.path.join(BASE_PATH, "static")
    uploads_dir = os.path.join(static_dir_for_uploads, "uploads")
    write_trace(f"Target static directory for uploads: {static_dir_for_uploads}")
    write_trace(f"Target uploads directory: {uploads_dir}")

    if not os.path.exists(static_dir_for_uploads):
        write_trace(f"Static directory for uploads does not exist. Creating: {static_dir_for_uploads}")
        os.makedirs(static_dir_for_uploads, exist_ok=True)
        write_trace(f"Created static directory for uploads: {static_dir_for_uploads}")
    else:
        write_trace(f"Static directory for uploads already exists: {static_dir_for_uploads}")

    if not os.path.exists(uploads_dir):
        write_trace(f"Uploads directory does not exist. Creating: {uploads_dir}")
        os.makedirs(uploads_dir, exist_ok=True)
        write_trace(f"Created uploads directory: {uploads_dir}")
    else:
        write_trace(f"Uploads directory already exists: {uploads_dir}")
except Exception as e:
    write_trace(f"Error processing uploads directory: {e!r}")


write_trace("Defining root GET endpoint...")
@app.get("/")
async def read_root():
    write_trace("Root GET endpoint called.")
    return {"message": "Welcome to Twitter Automation Backend"}
write_trace("Root GET endpoint defined.")

# 添加备份文件夹选择API
write_trace("Defining backup folder selection endpoint...")
@app.post("/api/select-backup-folder")
async def select_backup_folder(request: Request):
    """选择备份文件夹并扫描.tar.gz文件"""
    import os
    import glob
    try:
        body = await request.json()
        folder_path = body.get('folder_path', '')
        
        write_trace(f"Received folder_path from frontend: '{folder_path}'") # 添加调试日志

        # 如果没有指定路径，返回错误
        if not folder_path:
            return {
                "success": False,
                "message": "未指定备份文件夹路径",
                "folder_path": "",
                "backup_files": []
            }
        
        # 确保路径存在
        if not os.path.exists(folder_path):
            return {
                "success": False,
                "message": f"指定的路径不存在: {folder_path}",
                "folder_path": "",
                "backup_files": []
            }
        
        # 扫描.tar.gz文件
        pattern = os.path.join(folder_path, "*.tar.gz")
        tar_files = glob.glob(pattern)
        
        # 只返回文件名，不包含路径
        backup_files = [os.path.basename(f) for f in tar_files]
        
        write_trace(f"Scanned folder: {folder_path}, found {len(backup_files)} .tar.gz files")
        
        return {
            "success": True,
            "folder_path": folder_path,
            "backup_files": backup_files,
            "message": f"找到 {len(backup_files)} 个备份文件"
        }
    except Exception as e:
        write_trace(f"Error in select_backup_folder: {e!r}")
        return {
            "success": False,
            "message": f"选择文件夹失败: {str(e)}",
            "folder_path": "",
            "backup_files": []
        }

# 添加文件夹浏览API
write_trace("Defining browse folder endpoint...")
@app.post("/api/browse")
async def browse_folder(request: Request):
    """浏览文件夹内容"""
    import os
    try:
        body = await request.json()
        path = body.get('path', 'C:\\')
        
        # 确保路径存在
        if not os.path.exists(path):
            return {
                "success": False,
                "message": f"路径不存在: {path}",
                "current_path": "",
                "directories": [],
                "files": [],
                "parent_path": None
            }
        
        # 获取目录内容
        directories = []
        files = []
        
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    directories.append(item_path)
                else:
                    files.append(item_path)
        except PermissionError:
            return {
                "success": False,
                "message": f"没有权限访问路径: {path}",
                "current_path": path,
                "directories": [],
                "files": [],
                "parent_path": None
            }
        
        # 获取父目录
        parent_path = os.path.dirname(path) if path != os.path.dirname(path) else None
        
        # 排序
        directories.sort()
        files.sort()
        
        write_trace(f"Browse folder: {path}, found {len(directories)} dirs, {len(files)} files")
        
        return {
            "success": True,
            "current_path": path,
            "directories": directories,
            "files": files,
            "parent_path": parent_path
        }
    except Exception as e:
        write_trace(f"Error in browse_folder: {e!r}")
        return {
            "success": False,
            "message": f"浏览文件夹失败: {str(e)}",
            "current_path": "",
            "directories": [],
            "files": [],
            "parent_path": None
        }
write_trace("Backup folder selection endpoint defined.")


if __name__ == "__main__":
    multiprocessing.freeze_support() # 确保这一行存在
    write_trace("__name__ == '__main__' block entered.")
    try:
        write_trace("Attempting to import uvicorn...")
        import uvicorn
        write_trace("Successfully imported uvicorn.")

        write_trace("About to start Uvicorn server...")
        uvicorn.run(
            app,  # <--- ***** 这是主要修改点 *****
            host="0.0.0.0",
            port=8000,
            log_config=None,
            reload=False, 
            workers=1 
        )
        write_trace("Uvicorn server has presumably stopped.")
    except Exception as e:
        write_trace(f"Error in __main__ block (likely Uvicorn startup): {e!r}")