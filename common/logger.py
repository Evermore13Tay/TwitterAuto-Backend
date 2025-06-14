# common/logger.py
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from common.base_path_util import get_base_path # Ensure this import is correct
from datetime import datetime

# 🔧 检查是否启用简化日志模式
SIMPLIFIED_LOGGING = os.getenv('SIMPLIFIED_LOGGING', 'true').lower() == 'true'

# Get the base path
BASE_DIR = get_base_path()
LOG_DIR_NAME = "log" # Define the log directory name
LOG_DIR = os.path.join(BASE_DIR, LOG_DIR_NAME)

# Create log directory if it doesn't exist
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR, exist_ok=True) # Added exist_ok=True

# Path for the main log file
LOG_FILE_PATH = os.path.join(LOG_DIR, "myt.log")

# 🔧 自定义控制台处理器，处理 Windows 编码问题
class SafeStreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            
            # 在 Windows 上处理编码问题
            if sys.platform == "win32":
                try:
                    # 尝试直接写入
                    stream.write(msg + self.terminator)
                    stream.flush()
                except UnicodeEncodeError:
                    # 如果编码失败，移除 emoji 字符后重试
                    import re
                    clean_msg = re.sub(r'[^\x00-\x7F]+', '', msg)  # 移除非ASCII字符
                    stream.write(clean_msg + self.terminator)
                    stream.flush()
            else:
                stream.write(msg + self.terminator)
                stream.flush()
        except Exception:
            self.handleError(record)

# 🔧 简化日志格式化器
class SimplifiedFormatter(logging.Formatter):
    """简化模式下的格式化器，减少冗余信息"""
    
    def format(self, record):
        if SIMPLIFIED_LOGGING:
            # 简化模式：只显示关键信息
            if record.levelno >= logging.WARNING:
                # 警告和错误信息保持完整
                return super().format(record)
            elif record.levelno == logging.INFO:
                # INFO 级别：只显示重要的成功/失败信息
                msg = record.getMessage()
                if any(keyword in msg for keyword in ['✅', '❌', '🚀', '💾', '🔥', '成功', '失败', '完成', '开始']):
                    return super().format(record)
                else:
                    # 跳过不重要的 INFO 信息，但返回空字符串而不是 None
                    return ""
            else:
                # DEBUG 级别在简化模式下不显示
                return ""
        else:
            # 详细模式：显示所有信息
            return super().format(record)

# 🔧 自定义文件处理器，支持简化模式
class SimplifiedFileHandler(TimedRotatingFileHandler):
    def emit(self, record):
        try:
            formatted = self.format(record)
            if formatted and formatted.strip():  # 只记录非空的格式化结果
                if hasattr(self.stream, 'write'):
                    self.stream.write(formatted + self.terminator)
                    self.stream.flush()
        except Exception:
            self.handleError(record)

# 🔧 自定义控制台处理器，支持简化模式
class SimplifiedConsoleHandler(SafeStreamHandler):
    def emit(self, record):
        try:
            formatted = self.format(record)
            if formatted and formatted.strip():  # 只显示非空的格式化结果
                msg = formatted
                stream = self.stream
                
                # 在 Windows 上处理编码问题
                if sys.platform == "win32":
                    try:
                        stream.write(msg + self.terminator)
                        stream.flush()
                    except UnicodeEncodeError:
                        import re
                        clean_msg = re.sub(r'[^\x00-\x7F]+', '', msg)
                        stream.write(clean_msg + self.terminator)
                        stream.flush()
                else:
                    stream.write(msg + self.terminator)
                    stream.flush()
        except Exception:
            self.handleError(record)

# Create a logger
logger = logging.getLogger("TwitterAutomationAPI")

# 根据简化模式设置日志级别
if SIMPLIFIED_LOGGING:
    logger.setLevel(logging.INFO)  # 简化模式：只显示 INFO 及以上级别
else:
    logger.setLevel(logging.DEBUG)  # 详细模式：显示所有级别

# 🔧 使用简化格式化器
if SIMPLIFIED_LOGGING:
    formatter = SimplifiedFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
else:
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 🔧 文件处理器 - 使用简化处理器
file_handler = SimplifiedFileHandler(LOG_FILE_PATH, when='midnight', interval=1, backupCount=7, encoding='utf-8')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# 🔧 控制台处理器 - 使用简化处理器
console_handler = SimplifiedConsoleHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 🔧 添加日志模式提示
if SIMPLIFIED_LOGGING:
    logger.info("📝 日志系统已启动 - 简化模式（设置 SIMPLIFIED_LOGGING=false 启用详细模式）")
else:
    logger.info("📝 日志系统已启动 - 详细模式")

# Export the logger
__all__ = ['logger']

# Specific logger for device interactions, if needed
device_specific_loggers = {}

def get_device_logger(device_id):
    if device_id in device_specific_loggers:
        return device_specific_loggers[device_id]

    # Sanitize device_id for filename (replace common problematic characters)
    sanitized_device_id = device_id.replace(':', '_').replace('/', '_').replace('\\', '_')
    device_log_file = os.path.join(LOG_DIR, f"{sanitized_device_id}.log")

    device_logger = logging.getLogger(f"Device-{device_id}") # Use original device_id for logger name
    device_logger.setLevel(logging.INFO)

    # Prevent duplicating log messages if the root logger is also configured with handlers
    device_logger.propagate = False

    if not device_logger.handlers:
        handler = TimedRotatingFileHandler(device_log_file, when="midnight", interval=1, backupCount=7, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        device_logger.addHandler(handler)

    device_specific_loggers[device_id] = device_logger
    return device_logger

# Example usage:
# from common.logger import logger, get_device_logger
# logger.info("This is a general log message.")
# device_logger = get_device_logger("emulator-5554") # Or "192.168.1.100:5555"
# device_logger.info("This is a log message for emulator-5554.")

"""
通用日志配置模块
"""

# 配置日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

# 创建logger
logger = logging.getLogger("TwitterAutomationAPI")
logger.setLevel(logging.INFO)

# 如果logger还没有handler，添加一个
if not logger.handlers:
    # 创建console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # 创建formatter
    formatter = logging.Formatter(LOG_FORMAT)
    console_handler.setFormatter(formatter)
    
    # 添加handler到logger
    logger.addHandler(console_handler)

# 导出logger
__all__ = ['logger']