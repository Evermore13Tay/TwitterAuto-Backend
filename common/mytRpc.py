import ctypes
import sys
import time
import os
import threading
import random
from common.logger import logger
from common.ToolsKit import ToolsKit
from common.mytSelector import mytSelector
import json
import socket

CB_FUNC = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p), ctypes.c_int)
AUDIO_CB_FUNC = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_int)


@CB_FUNC
def video_cb(rot, data, len):
    # 在这里处理接收到的数据
    buf = ctypes.cast(data, ctypes.POINTER(ctypes.c_ubyte * len)).contents
    bin_buf = bytearray(buf)
    # 此次为解析出来的h264流数据 可以做相应的操作处理 这里只是给出保存到文件的示例
    with open("video.raw", 'ab') as f:
        f.write(bin_buf)
    # print("video",rot, data, len)
    # res = ctypes.string_at(data, len)
    # g_data += res
    # if time.time() - start < 10:
    #    with open("video.raw", 'ab+') as f:
    #        f.write(res)
# cb = CB_FUNC(cb1)


#播放acc 文件 就添加头 如果直接解码 就不需要添加adts 头
def add_adts_header(aac_data):
    # ADTS 头部格式
    adts = [0] * 7
    # ADTS 头部详细参数
    profile = 1  # AAC LC (Low Complexity) profile is 1
    freq_idx = 4            #44100
    chan_cfg = 2            #channels =2 
    # 计算帧长度
    frame_length = len(aac_data) 
    # 构造 ADTS 头部
    adts[0] = 0xFF  # 同步字
    adts[1] = 0xF1  # 同步字，MPEG-2 Layer (0 for MPEG-4)，保护标志
    adts[2] = (profile << 6) + (freq_idx << 2) + (chan_cfg >> 2)
    adts[3] = ((chan_cfg & 3) << 6) + ((frame_length + 7) >> 11)
    adts[4] = ((frame_length + 7) & 0x7FF) >> 3
    adts[5] = (((frame_length + 7) & 7) << 5) + 0x1F
    adts[6] = 0xFC  # Number of raw data blocks in frame
    # 合并 ADTS 头部和 AAC 数据
    adts_aac_data = bytearray(adts) + aac_data
    return adts_aac_data

@AUDIO_CB_FUNC
def audio_cb(data, len):
    
    if len == 2:
        #该2个字节为myt 添加的标记 不用处理 
        #print(f"audio_cb :len={len}")
        pass
    else:
        buf = ctypes.cast(data, ctypes.POINTER(ctypes.c_ubyte * len)).contents
        bin_buf = bytearray(buf)

        #播放acc 文件 就添加头 如果直接解码 就不需要添加adts 头
        adts_aac_data = add_adts_header(bin_buf)
        # 此次为解析出来的aac 原始音频流数据 可以做相应的操作处理 这里只是给出保存到文件的示例
        with open("audio.aac", 'ab') as f:
            f.write(adts_aac_data)

# 添加全局连接管理器
class MytRpcConnectionManager:
    """🔧 并发连接管理器，支持多端口同时连接"""
    _instance = None
    _lock = threading.Lock()
    _active_connections = {}
    _connection_delays = {}
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_connection_delay(self, port):
        """获取端口连接延迟，避免并发冲突"""
        with self._lock:
            if port not in self._connection_delays:
                # 为不同端口分配更大的延迟时间差，避免并发
                base_delay = (port % 10) * 2.0  # 0-18秒的基础延迟
                random_delay = random.uniform(0.5, 2.0)  # 0.5-2秒的随机延迟
                self._connection_delays[port] = base_delay + random_delay
            return self._connection_delays[port]
    
    def register_connection(self, port, handle):
        """注册活跃连接"""
        with self._lock:
            self._active_connections[port] = handle
            logger.debug(f"Registered connection for port {port}, handle: {handle}")
    
    def unregister_connection(self, port):
        """注销连接"""
        with self._lock:
            if port in self._active_connections:
                del self._active_connections[port]
                logger.debug(f"Unregistered connection for port {port}")
    


# 全局连接管理器实例
connection_manager = MytRpcConnectionManager()

# 🔧 日志消息辅助函数
def _log_with_fallback(level, message_with_emoji, message_plain):
    """根据系统环境选择合适的日志消息格式"""
    try:
        # 尝试使用带 emoji 的消息
        getattr(logger, level)(message_with_emoji)
    except UnicodeEncodeError:
        # 如果编码失败，使用纯文本消息
        getattr(logger, level)(message_plain)

# myt rpc  lib
#  add node oper 2024.1.31
class MytRpc(object):
    def __init__(self) -> None:

        try:
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            # This is the base path when running as a bundled app
            base_path = sys._MEIPASS
            tools_root_path_debug = ToolsKit().GetRootPath() 
        except AttributeError:
            # Not bundled, running in development (e.g., python main.py)
            # Assume 'lib' is relative to the main script's directory (e.g., backend/main.py and backend/lib/)
            base_path = os.path.abspath(os.path.dirname(sys.argv[0]))
            tools_root_path_debug = ToolsKit().GetRootPath() # or base_path, depending on dev CWD

        if sys.platform == "linux":
            self._lib_PATH = os.path.join(base_path, "lib", "libmytrpc.so")
        else:
            self._lib_PATH = os.path.join(base_path, "lib", "libmytrpc.dll")

        self._handle = 0
        self._port = None  # 添加端口记录
    
    def __del__(self) :
        if self._handle>0 :
            # 考虑在此处添加一个延迟，确保 RPC 库有时间处理关闭请求
            # 或者确保在调用 closeDevice 前没有其他操作正在进行
            try:
                self._rpc.closeDevice(self._handle)
            except AttributeError:
                # 如果 _rpc 还没初始化就删除了对象，会发生 AttributeError
                pass
            if self._port:
                connection_manager.unregister_connection(self._port)
    
    #获取SDK 版本
    def get_sdk_version(self):
        ret = ''
        if os.path.exists(self._lib_PATH) == True:
            if sys.platform == "linux":
                dll = ctypes.CDLL(self._lib_PATH)
            else:
                dll = ctypes.WinDLL(self._lib_PATH)

            ret = dll.getVersion()
        return ret

    # 初始化
    def init(self, ip, port, timeout, max_retries=1):
        """🔧 真正并发初始化 - 移除全局锁，支持同时连接多个端口"""
        ret = False
        self._port = port  # 记录端口
        
        if not os.path.exists(self._lib_PATH):
            logger.error(f"MytRpc library file not found: {self._lib_PATH}")
            return False
        
        try:
            # 🔧 1. 基础等待 - 只针对当前端口，不影响其他端口
            connection_delay = connection_manager.get_connection_delay(port)
            logger.info(f"🕒 MytRpc {ip}:{port} 并发连接前等待 {connection_delay:.2f}秒")
            time.sleep(connection_delay)
            
            # 🔧 2. 简化检查 - 单次快速端口检查
            logger.info(f"🔍 MytRpc {ip}:{port} 快速端口检查...")
            port_accessible = self._simple_port_check(ip, port)
            if not port_accessible:
                logger.warning(f"⚠️ MytRpc {ip}:{port} 端口不可访问，但继续尝试连接")
                # 不直接返回False，给连接一个机会
            
            # 🔧 3. 初始化 RPC 库
            if sys.platform == "linux":
                self._rpc = ctypes.CDLL(self._lib_PATH)
            else:
                self._rpc = ctypes.WinDLL(self._lib_PATH)
                
            # 🔧 4. 真正并发连接（无全局锁，每个端口独立连接）
            logger.info(f"🔄 MytRpc {ip}:{port} 开始真正并发连接...")
            
            success = self._attempt_connection(ip, port, timeout + 3)  # 延长超时时间
            if success:
                ret = True
                connection_manager.register_connection(port, self._handle)
                _log_with_fallback('info',
                                    f"✅ MytRpc {ip}:{port} 真正并发连接成功",
                                    f"MytRpc {ip}:{port} concurrent connection successful")
            else:
                logger.error(f"❌ MytRpc {ip}:{port} 并发连接失败")
        
        except Exception as e:
            logger.error(f"❌ MytRpc {ip}:{port} 连接异常: {e}")
            ret = False
        
        return ret

    def _simple_port_check(self, ip, port, timeout=2):
        """简化的端口检查 - 单次快速检查"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            sock.close()
            
            if result == 0:
                logger.debug(f"✅ MytRpc {ip}:{port} 端口检查成功")
                return True
            else:
                logger.debug(f"⚠️ MytRpc {ip}:{port} 端口检查失败 (错误:{result})")
                return False
                
        except Exception as e:
            logger.debug(f"⚠️ MytRpc {ip}:{port} 端口检查异常: {e}")
            return False

    def _wait_for_service_ready(self, ip, port, max_wait=10):
        """等待MytRpc服务真正就绪 - 持续检查直到稳定可用"""
        
        
        logger.info(f"🔍 检查 {ip}:{port} 服务就绪状态...")
        
        start_time = time.time()
        consecutive_success = 0
        required_success = 2  # 需要连续2次成功才认为服务就绪
        
        while time.time() - start_time < max_wait:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((ip, port))
                sock.close()
                
                if result == 0:
                    consecutive_success += 1
                    if consecutive_success >= required_success:
                        logger.info(f"✅ MytRpc {ip}:{port} 服务就绪 (连续{consecutive_success}次成功)")
                        return True
                    else:
                        logger.debug(f"🔄 MytRpc {ip}:{port} 检查成功 {consecutive_success}/{required_success}")
                        time.sleep(0.5)  # 短暂等待再次检查
                else:
                    consecutive_success = 0  # 重置计数
                    elapsed = time.time() - start_time
                    logger.debug(f"⏳ MytRpc {ip}:{port} 服务未就绪 (错误:{result}, 已等待{elapsed:.1f}s)")
                    time.sleep(1)  # 等待1秒后重试
                    
            except Exception as e:
                consecutive_success = 0  # 重置计数
                elapsed = time.time() - start_time
                logger.debug(f"⏳ MytRpc {ip}:{port} 检查异常 (已等待{elapsed:.1f}s): {e}")
                time.sleep(1)
        
        logger.warning(f"⚠️ MytRpc {ip}:{port} 等待{max_wait}秒后服务仍未就绪")
        return False

    def _port_health_check(self, ip, port, timeout=3):
        """增强端口健康检查 - 通用重试机制应对随机连接问题"""
        try:
            import socket
            
            # 🔧 通用重试机制：所有端口统一2次检查机会
            max_attempts = 2
            check_timeout = timeout + 1  # 统一延长检查超时1秒
            
            for attempt in range(max_attempts):
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(check_timeout)
                    result = sock.connect_ex((ip, port))
                    sock.close()
                    
                    if result == 0:
                        if attempt > 0:
                            logger.info(f"🔧 MytRpc {ip}:{port} 端口检查成功 (第{attempt + 1}次尝试)")
                        return True
                    else:
                        if attempt < max_attempts - 1:
                            logger.info(f"🔄 MytRpc {ip}:{port} 端口检查失败 (错误:{result}), 等待1秒后重试...")
                            time.sleep(1)  # 等待1秒后重试，避免过长延迟
                            continue
                        else:
                            logger.error(f"❌ MytRpc {ip}:{port} 端口检查最终失败 (错误:{result})")
                            return False
                
                except Exception as check_error:
                    if attempt < max_attempts - 1:
                        logger.warning(f"⚠️ MytRpc {ip}:{port} 端口检查异常，重试中: {check_error}")
                        time.sleep(1)
                        continue
                    else:
                        logger.error(f"❌ MytRpc {ip}:{port} 端口检查异常: {check_error}")
                        return False
            
            return False
        except Exception as e:
            logger.error(f"❌ MytRpc {ip}:{port} 端口健康检查严重异常: {e}")
            return False
    
    def _attempt_connection(self, ip, port, timeout):
        """尝试建立连接 - 增强重试策略"""
        start_time = time.time()
        
        # 🔧 使用更长的超时时间，更多重试机会
        internal_timeout = min(timeout, 12)  # 允许更长的内部超时
        max_attempts = 3  # 增加重试次数
        
        logger.debug(f"🔄 MytRpc {ip}:{port} attempting connection with {internal_timeout}s timeout, max {max_attempts} attempts")
        
        for attempt in range(max_attempts):
            if time.time() - start_time >= timeout:
                logger.warning(f"⏰ MytRpc {ip}:{port} overall timeout reached")
                break
                
            try:
                logger.debug(f"🔄 MytRpc {ip}:{port} connection attempt {attempt + 1}/{max_attempts}")
                
                # 使用较长的内部超时，给openDevice更多时间
                self._handle = self._rpc.openDevice(bytes(ip, "utf-8"), port, internal_timeout) 
                
                if self._handle > 0:
                    # 🔧 连接成功，简单验证一下连接状态
                    logger.debug(f"✅ MytRpc {ip}:{port} openDevice successful, handle: {self._handle}")
                    
                    # 简单的连接验证（不过度依赖）
                    try:
                        self._rpc.checkLive.argtypes = [ctypes.c_long]
                        self._rpc.checkLive.restype = ctypes.c_int
                        live_check = self._rpc.checkLive(self._handle)
                        if live_check > 0:
                            logger.debug(f"✅ MytRpc {ip}:{port} connection verified")
                            return True
                        else:
                            logger.debug(f"⚠️ MytRpc {ip}:{port} connection not live, but accepting handle")
                            return True  # 仍然接受连接，即使checkLive失败
                    except Exception as check_e:
                        logger.debug(f"⚠️ MytRpc {ip}:{port} live check failed: {check_e}, but accepting handle")
                        return True  # 即使验证失败也接受连接
                else:
                    # openDevice 返回 0，等待后重试
                    logger.debug(f"⚠️ MytRpc {ip}:{port} openDevice returned 0 (attempt {attempt + 1})")
                    if attempt < max_attempts - 1:
                        wait_time = 1.5 + attempt * 0.5  # 递增等待时间
                        logger.debug(f"⏳ MytRpc {ip}:{port} waiting {wait_time}s before retry")
                        time.sleep(wait_time)
                        
            except Exception as e:
                # 捕获 CTypes 调用的异常
                logger.warning(f"⚠️ MytRpc {ip}:{port} openDevice exception (attempt {attempt + 1}): {e}")
                if attempt < max_attempts - 1:
                    wait_time = 2 + attempt * 0.5  # 异常时等待更长时间
                    logger.debug(f"⏳ MytRpc {ip}:{port} waiting {wait_time}s after exception")
                    time.sleep(wait_time)
        
        elapsed = time.time() - start_time
        logger.error(f"❌ MytRpc {ip}:{port} all connection attempts failed after {elapsed:.1f}s")
        return False
    
    def _verify_connection(self):
        """验证连接是否真正可用"""
        try:
            if self._handle > 0:
                self._rpc.checkLive.argtypes = [ctypes.c_long]
                self._rpc.checkLive.restype = ctypes.c_int
                result = self._rpc.checkLive(self._handle)
                # checkLive 返回 0 表示不活跃，大于 0 表示活跃
                return result > 0
        except Exception as e:
            logger.error(f"MytRpc connection verification failed for handle {self._handle}: {e}")
            pass
        return False
    
    def _cleanup_failed_connection(self):
        """清理失败的连接"""
        try:
            if self._handle > 0 and hasattr(self, '_rpc'): # 确保 _rpc 已加载
                self._rpc.closeDevice(self._handle)
                self._handle = 0
                logger.debug(f"Cleaned up failed MytRpc connection.")
        except Exception as e:
            logger.error(f"Error cleaning up failed MytRpc connection: {e}")
            pass

    #检查远程连接是否处于连接状态
    def check_connect_state(self):
        ret = False
        if self._handle>0 and hasattr(self, '_rpc'):
            self._rpc.checkLive.argtypes = [ctypes.c_long]
            self._rpc.checkLive.restype = ctypes.c_int
            exec_ret = self._rpc.checkLive(self._handle)
            if exec_ret == 0:
                ret = False
            else:
                ret = True
        return ret
            #LIBMYTRPC_API int MYAPI checkLive(long handle);

    # 执行命令
    #返回状态值 和 内容
    def exec_cmd(self, cmd):
        ret = False
        out_put = ''
        if self._handle > 0 and hasattr(self, '_rpc'):
            self._rpc.execCmd.restype = ctypes.c_char_p
            ptr = self._rpc.execCmd(self._handle, ctypes.c_int(1), ctypes.c_char_p(cmd.encode('utf-8'))) 
            if ptr is not None:
                out_put = ptr.decode('utf-8')
                logger.debug("exec " + cmd + "  :" + out_put)
                ret = True
            else:
                # 即使返回空指针，也认为命令执行成功，但结果为空
                ret = True 
        return out_put, ret

    # 导出节点信息
    # bDumpAll 导出所有节点  0  1
    def dumpNodeXml(self, bDumpAll):
        """
        导出节点XML信息。

        参数:
        - bDumpAll (bool): 是否导出所有信息，True表示导出全部，False表示仅导出部分信息。

        返回:
        - ret: 成功时返回XML字符串，失败时返回False。
        """
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            self._rpc.dumpNodeXml.argtypes = [ctypes.c_long, ctypes.c_int]
            self._rpc.dumpNodeXml.restype = ctypes.c_void_p
            ptr = self._rpc.dumpNodeXml(self._handle, bDumpAll)
            if ptr:
                p2 = ctypes.cast(ptr, ctypes.c_char_p)
                ret = p2.value.decode("utf-8")
                self._rpc.freeRpcPtr.argtypes = [ctypes.c_void_p]
                self._rpc.freeRpcPtr(ptr)
            else:
                logger.debug('dumpNodeXml is NULL ptr!')
        return ret

    def dumpNodeXmlEx(self, workMode, timeout):
            """
            导出节点XML信息。

            参数:
                workMode True  表示开启无障碍 
                             False  表示关闭无障碍 
                timeout    超时  单位豪秒(1秒=1000毫秒)  -1 为永不超时

            返回:
            - ret: 成功时返回XML字符串，失败时返回False。
            原型
            LIBMYTRPC_API char* MYAPI dumpNodeXmlEx(long handle, int useNewMode, int timeout);
            """
            ret = False
            if self._handle > 0 and hasattr(self, '_rpc'):
                self._rpc.dumpNodeXmlEx.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_int]
                self._rpc.dumpNodeXmlEx.restype = ctypes.c_void_p
                if workMode == True:
                    iMode = 1
                else:
                    iMode = 0
                ptr = self._rpc.dumpNodeXmlEx(self._handle, iMode, timeout)
                if ptr:
                    p2 = ctypes.cast(ptr, ctypes.c_char_p)
                    ret = p2.value.decode("utf-8")
                    self._rpc.freeRpcPtr.argtypes = [ctypes.c_void_p]
                    self._rpc.freeRpcPtr(ptr)
                else:
                    logger.debug('dumpNodeXmlEx is NULL ptr!')
            return ret

    # 截图导出为bytes 数组
    # type  0 png  1 jpg
    # quality  图片质量  0-100
    # 返回字节数组
    def takeCaptrueCompress(self, type, quality):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            dataLen = ctypes.c_int(0)
            self._rpc.takeCaptrueCompress.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_int,  ctypes.POINTER(ctypes.c_int)]
            self._rpc.takeCaptrueCompress.restype = ctypes.c_void_p
            ptr = self._rpc.takeCaptrueCompress(self._handle, type, quality, ctypes.byref(dataLen))
            if ptr:
                try:
                    buf = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ubyte * dataLen.value)).contents
                    ret = bytearray(buf)
                finally:
                    self._rpc.freeRpcPtr.argtypes = [ctypes.c_void_p]
                    self._rpc.freeRpcPtr(ptr)
        return ret
    
    #指定区域截图
    def takeCaptrueCompressEx(self, left, top, right, bottom, type, quality):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            dataLen = ctypes.c_int(0)
            self._rpc.takeCaptrueCompressEx.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_int,ctypes.c_int, ctypes.c_int,ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
            self._rpc.takeCaptrueCompressEx.restype = ctypes.c_void_p
            ptr = self._rpc.takeCaptrueCompressEx(self._handle, left, top,right, bottom, type, quality, ctypes.byref(dataLen))
            if ptr:
                try:
                    buf = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ubyte * dataLen.value)).contents
                    ret = bytearray(buf)
                finally:
                    self._rpc.freeRpcPtr.argtypes = [ctypes.c_void_p]
                    self._rpc.freeRpcPtr(ptr)
            else:
                logger.debug(f"takeCaptrueCompressEx error {ptr}")
        return ret
    
    
    #截图到文件
    def screentshotEx(self,left, top, right, bottom, type, quality, file_path):
        ret = False
        byte_data = self.takeCaptrueCompressEx(left, top, right, bottom,type, quality) 
        if byte_data != False:
            with open(file_path, 'wb') as file:
                file.write(byte_data)
            ret = True
        else:
            logger.debug("screentshotEx error")
        return ret

    #截图到文件
    def screentshot(self, type, quality, file_path):
        ret = False
        byte_data = self.takeCaptrueCompress(type, quality) 
        if byte_data != False:
            with open(file_path, 'wb') as file:
                file.write(byte_data)
            ret = True
        return ret

    # 文字输入
    def sendText(self, text):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            exec_ret =  self._rpc.sendText(self._handle, ctypes.c_char_p(text.encode('utf-8')))
            if exec_ret == 1:
                ret = True
        return ret

    #清除输入的文字
    def ClearText(self, count):
        for i in range(0, count):
            self.keyPress(67)
        

    # 开启指定的应用
    def openApp(self, pkg):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            exec_ret = self._rpc.openApp(self._handle, ctypes.c_char_p(pkg.encode('utf-8')))
            if exec_ret == 1:
                ret = True
        return ret

    #停止指定的应用
    def stopApp(self, pkg):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            exec_ret = self._rpc.stopApp(self._handle, ctypes.c_char_p(pkg.encode('utf-8')))
            if exec_ret == 1:
                ret = True
        return ret

    #获取当前屏幕的方向
    # 4个方向（0,1,2,3）
    def getDisplayRotate(self):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            if self._rpc.getDisplayRotate(self._handle) == 1:
                ret = True
        return ret
    
    #按下操作
    def touchDown(self, finger_id, x, y):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            if self._rpc.touchDown(self._handle, finger_id, x, y) == 1:
                ret = True
        return ret
    
    #弹起操作
    def touchUp(self, finger_id, x, y):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            if self._rpc.touchUp(self._handle, finger_id, x, y) == 1:
                ret = True
        return ret
    
    #滑动操作
    def touchMove(self, finger_id, x, y):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            if self._rpc.touchMove(self._handle, finger_id, x, y) == 1:
                ret = True
        return ret
    
    #单击操作
    def touchClick(self, finger_id, x, y):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            if self._rpc.touchClick(self._handle, finger_id, x, y) == 1:
                ret = True
        return ret

    #长按操作
    #t 为长按的时长 单位: 秒(float)
    def longClick(self, finger_id, x, y, t):
        ret = False
        if self._handle>0 and hasattr(self, '_rpc'):
            if self._rpc.touchDown(self._handle, finger_id, x, y) > 0:
                time.sleep(t)
                exec_ret = self._rpc.touchUp(self._handle, finger_id, x, y)
                if exec_ret ==1 :
                    ret = True
        return ret

    #按键操作
    # 键值 参考: https://blog.csdn.net/yaoyaozaiye/article/details/122826340
    def keyPress(self, code):
        ret = False
        if self._handle > 0 and hasattr(self, '_rpc'):
            if self._rpc.keyPress(self._handle, code) == 1:
                ret = True
        return ret
    
    #Back按键
    def pressBack(self):
        return self.keyPress(4)
    
    #Enter 按键
    def pressEnter(self):
        return self.keyPress(66)
    
    #Home 按键
    def pressHome(self):
        return self.keyPress(3)
    
    #Menu 按键
    def pressRecent(self):
        return self.keyPress(82)

    #滑动操作
    # x0 y0 起始坐标
    # x1 y1 终点坐标
    # elapse 时长  (单位:毫秒)  
    def swipe(self, id, x0, y0, x1, y1, elapse):
        ret = False
        if self._handle>0 and hasattr(self, '_rpc'):
            ret = self._rpc.swipe(self._handle,id,  x0, y0, x1, y1, elapse, False)
        return ret
    
    #创建selector筛选器对象
    def create_selector(self):
        ret = None
        if self._handle>0 and hasattr(self, '_rpc'):
            ret = mytSelector(self._handle, self._rpc)
        return ret
    
    #释放 selector 对象
    def release_selector(self, sel):
        del sel
    
    #按照Node的属性执行点击
    def clickText(self, text):
        ret = False
        selector = self.create_selector() 
        if selector: # 确保 selector 被成功创建
            selector.addQuery_TextEqual(text)
            node = selector.execQueryOne(200)
            if node is not None:
                ret = node.Click_events()
            self.release_selector(selector)
        return ret

    def clickTextMatchStart(self, text):
        ret = False
        selector = self.create_selector()
        if selector:
            selector.addQuery_TextStartWith(text)
            node = selector.execQueryOne(200)
            if node is not None:
                ret = node.Click_events()
            self.release_selector(selector)
        return ret
        
    def clickClass(self, clzName):
        ret = False
        selector = self.create_selector() 
        if selector:
            selector.addQuery_ClzEqual(clzName)
            node = selector.execQueryOne(200)
            if node is not None:
                ret = node.Click_events()
            self.release_selector(selector)
        return ret
    
    def clickId(self, id):
        ret = False
        selector = self.create_selector() 
        if selector:
            selector.addQuery_IdEqual(id)
            node = selector.execQueryOne(200)
            if node is not None:
                ret = node.Click_events()
            self.release_selector(selector)
        return ret
    
    def clickDesc(self, des):
        ret = False
        selector = self.create_selector() 
        if selector:
            selector.addQuery_DescEqual(des)
            node = selector.execQueryOne(200)
            if node is not None:
                ret = node.Click_events()
            self.release_selector(selector)
        return ret

    #依据Text 获取Node节点
    def getNodeByText(self, text):
        ret  = None
        selector = self.create_selector() 
        if selector:
            selector.addQuery_TextEqual(text)
            node_arr = selector.execQuery(999,200)
            if len(node_arr)>0 :
                arr = []
                for n in node_arr:
                    json_str = n.getNodeJson()
                    json_obj = json.loads(json_str)
                    arr.append(json_obj)
                ret = json.dumps(arr)
            self.release_selector(selector)
        return ret

    def getNodeByTextMatchEnd(self, text):
        ret  = None
        selector = self.create_selector()
        if selector:
            selector.addQuery_TextEndWith(text)
            node_arr = selector.execQuery(999,200)
            if len(node_arr)>0 :
                arr = []
                for n in node_arr:
                    json_str = n.getNodeJson()
                    json_obj = json.loads(json_str)
                    arr.append(json_obj)
                ret = json.dumps(arr)
            self.release_selector(selector)
        return ret

    def getNodeByTextMatchStart(self, text):
        ret  = None
        selector = self.create_selector()
        if selector:
            selector.addQuery_TextStartWith(text)
            node_arr = selector.execQuery(999,200)
            if len(node_arr)>0 :
                arr = []
                for n in node_arr:
                    json_str = n.getNodeJson()
                    json_obj = json.loads(json_str)
                    arr.append(json_obj)
                ret = json.dumps(arr)
            self.release_selector(selector)
        return ret

    #根据pkg 获取Node节点
    def getNodeByPkg(self,pkg):
        ret = None
        selector = self.create_selector()
        if selector:
            selector.addQuery_PackageEqual(pkg)
            node_arr = selector.execQuery(999, 200)
            if len(node_arr) > 0:
                arr = []
                for n in node_arr:
                    json_str = n.getNodeJson()
                    json_obj = json.loads(json_str)
                    arr.append(json_obj)
                ret = json.dumps(arr)
            self.release_selector(selector)
        return ret

    def getNodeByClass(self, clzName):
        ret  = None
        selector = self.create_selector() 
        if selector:
            selector.addQuery_ClzEqual(clzName)
            node_arr = selector.execQuery(999,200)
            if len(node_arr)>0 :
                arr = []
                for n in node_arr:
                    json_str = n.getNodeJson()
                    json_obj = json.loads(json_str)
                    arr.append(json_obj)
                ret = json.dumps(arr)
            self.release_selector(selector)
        return ret

    def getNodeById(self, id):
        ret  = None
        selector = self.create_selector() 
        if selector:
            selector.addQuery_IdEqual(id)
            node_arr = selector.execQuery(999,200)
            if len(node_arr)>0 :
                arr = []
                for n in node_arr:
                    json_str = n.getNodeJson()
                    json_obj = json.loads(json_str)
                    arr.append(json_obj)
                ret = json.dumps(arr)
            self.release_selector(selector)
        return ret
    
    def getNodeByDesc(self, desc):
        ret  = None
        selector = self.create_selector() 
        if selector:
            selector.addQuery_DescEqual(desc)
            node_arr = selector.execQuery(999,200)
            if len(node_arr)>0 :
                arr = []
                for n in node_arr:
                    json_str = n.getNodeJson()
                    json_obj = json.loads(json_str)
                    arr.append(json_obj)
                ret = json.dumps(arr)
            self.release_selector(selector)
        return ret
    
    #设置rpa 的工作模式    1   表示开启无障碍 （默认的工作模式）  
    #                     0   表示关闭无障碍 
    # 设置RPA工作模式
    # 本函数用于设置RPA的工作模式，主要是为了确定是否使用无障碍模式
    # 开启无障碍模式后，可以获取更加完整的节点信息，但某些应用环境会检测是否开启了无障碍
    # 该方法需要 最新的额固件版本支持  
    # 参数:
    #   mode: 工作模式的设置值，决定是否使用无障碍模式
    # 返回值:
    #   成功设置返回True，否则返回False
    def setRpaWorkMode(self, mode):
        ret = False
        if self._handle>0 and hasattr(self, '_rpc'):
            self._rpc.useNewNodeMode.argtypes = [ctypes.c_long, ctypes.c_int]
            self._rpc.useNewNodeMode.restype = ctypes.c_int
            exec_ret = self._rpc.useNewNodeMode(self._handle, mode)
            if exec_ret == 0: # 假设 0 表示失败
                ret = False
            else: # 假设非 0 表示成功
                ret = True
        return ret

    def startVideoStream(self):
        """
        启动视频流。

        在调用此方法之前，需要确保已经成功连接到设备，并且_handle是有效的。
        该方法将根据指定的参数（分辨率和比特率）启动视频流，并注册回调函数以处理视频和音频数据。
        
        video_cb 视频回调函数
        audio_cb 音频回调函数
        Returns:
            bool: 如果视频流成功启动并运行，则返回True；否则返回False。
        """
        if self._handle > 0 and hasattr(self, '_rpc'):
            self._rpc.startVideoStream.argtypes = [ctypes.c_long,
                                                    ctypes.c_int,
                                                    ctypes.c_int,
                                                    ctypes.c_int,
                                                    CB_FUNC,
                                                    AUDIO_CB_FUNC
                                                    ]
            self._rpc.startVideoStream.restype = ctypes.c_int

            w = 400
            h = 720
            bitrate = 1000 * 20
            exec_ret = self._rpc.startVideoStream(self._handle, w, h, bitrate, video_cb, audio_cb)
            if exec_ret == 1:
                while True:
                    time.sleep(1)
                    print('is running')
            else:
                return False
        else:
            return False
        return True # 视频流启动成功后会进入无限循环，这里表示成功启动并开始运行