# backend/common/base_path_util.py
import sys
import os
from pathlib import Path

def resource_path(relative_path: str) -> Path:
    """
    获取资源的绝对路径。
    在开发环境中，它返回相对于脚本的路径。
    在 PyInstaller 打包的 .exe 中，它返回解压到临时文件夹 (_MEIPASS) 中的路径。
    """
    try:
        # PyInstaller 创建一个临时文件夹并将路径存储在 _MEIPASS 中
        base_path = Path(sys._MEIPASS)
    except Exception:
        # 如果不是通过 PyInstaller 运行 (例如，在开发环境中)
        # 我们将基路径设置为当前文件所在目录的上一级目录 (即项目根目录 backend/)
        # 假设 base_path_util.py 在 common/ 文件夹下，项目根目录是 common/ 的父目录
        base_path = Path(__file__).resolve().parent.parent
    return base_path / relative_path

def get_base_path() -> str:
    """
    获取应用程序的基础路径。
    在开发环境中，返回项目根目录。
    在打包环境中，返回PyInstaller解压的临时目录。
    """
    try:
        # PyInstaller 创建一个临时文件夹并将路径存储在 _MEIPASS 中
        base_path = sys._MEIPASS
    except Exception:
        # 如果不是通过 PyInstaller 运行 (例如，在开发环境中)
        # 返回项目根目录
        base_path = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    return base_path

def get_app_data_dir(app_name: str = "YourAppName") -> Path:
    """
    获取用户特定的应用程序数据目录。
    这对于存储数据库、日志等用户可写文件非常有用。
    """
    if os.name == 'nt':  # Windows
        path = Path(os.getenv('APPDATA')) / app_name
    else:  # macOS, Linux
        path = Path.home() / ".local" / "share" / app_name
    path.mkdir(parents=True, exist_ok=True)
    return path