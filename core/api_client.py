"""
API客户端核心模块
统一管理HTTP请求、错误处理、重试机制、响应解析等功能
"""

import asyncio
import aiohttp
import logging
import time
import json
from typing import Optional, Dict, Any, Tuple, Union
from urllib.parse import urljoin
import os

logger = logging.getLogger(__name__)

class ApiClient:
    """API客户端核心类"""
    
    def __init__(self, base_url: Optional[str] = None, timeout: int = 30):
        self.base_url = base_url
        self.default_timeout = timeout
        self.session = None
        self.max_retries = 3
        self.retry_delay = 2
        self.retry_statuses = {500, 502, 503, 504, 408, 429}  # 需要重试的HTTP状态码
        
        # 请求统计
        self.request_count = 0
        self.success_count = 0
        self.error_count = 0
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.create_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close_session()
    
    async def create_session(self) -> None:
        """创建HTTP会话"""
        if not self.session or self.session.closed:
            connector = aiohttp.TCPConnector(
                limit=100,  # 总连接池大小
                limit_per_host=20,  # 每个主机的连接数
                keepalive_timeout=30,
                enable_cleanup_closed=True
            )
            
            timeout = aiohttp.ClientTimeout(total=self.default_timeout)
            
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'TwitterAutomation/1.0',
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                }
            )
    
    async def close_session(self) -> None:
        """关闭HTTP会话"""
        if self.session and not self.session.closed:
            await self.session.close()
            # 等待连接器完全关闭
            await asyncio.sleep(0.1)
    
    async def make_request(
        self,
        url: str,
        method: str = 'GET',
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        retries: Optional[int] = None
    ) -> Tuple[bool, Optional[Union[Dict, str]], Optional[str]]:
        """
        发起HTTP请求
        
        Args:
            url: 请求URL
            method: HTTP方法
            params: URL参数
            data: 表单数据
            json_data: JSON数据
            headers: 请求头
            timeout: 超时时间
            retries: 重试次数
        
        Returns:
            Tuple[bool, Optional[Union[Dict, str]], Optional[str]]: (成功状态, 响应数据, 错误信息)
        """
        if retries is None:
            retries = self.max_retries
        
        if timeout is None:
            timeout = self.default_timeout
        
        # 确保会话已创建
        await self.create_session()
        
        # 构建完整URL
        if self.base_url and not url.startswith('http'):
            full_url = urljoin(self.base_url, url)
        else:
            full_url = url
        
        # 合并请求头
        request_headers = {}
        if headers:
            request_headers.update(headers)
        
        self.request_count += 1
        last_exception = None
        
        for attempt in range(retries + 1):
            try:
                # 创建请求参数
                request_kwargs = {
                    'url': full_url,
                    'timeout': aiohttp.ClientTimeout(total=timeout)
                }
                
                if params:
                    request_kwargs['params'] = params
                
                if headers:
                    request_kwargs['headers'] = request_headers
                
                if json_data:
                    request_kwargs['json'] = json_data
                elif data:
                    request_kwargs['data'] = data
                
                # 发起请求
                async with getattr(self.session, method.lower())(**request_kwargs) as response:
                    # 检查状态码
                    if response.status == 200:
                        try:
                            # 尝试解析JSON
                            response_data = await response.json()
                            self.success_count += 1
                            
                            if attempt > 0:
                                logger.info(f"✅ 请求在第 {attempt + 1} 次尝试后成功: {method} {full_url}")
                            
                            return True, response_data, None
                        except json.JSONDecodeError:
                            # 如果不是JSON，返回文本
                            response_data = await response.text()
                            self.success_count += 1
                            return True, response_data, None
                    
                    elif response.status in self.retry_statuses and attempt < retries:
                        # 可重试的错误状态码
                        error_msg = f"HTTP {response.status}: {response.reason}"
                        logger.warning(f"⚠️ 请求失败，准备重试: {error_msg} (第 {attempt + 1}/{retries + 1} 次)")
                        await asyncio.sleep(self.retry_delay * (2 ** attempt))
                        continue
                    
                    else:
                        # 不可重试的错误或已达到重试上限
                        error_text = await response.text()
                        error_msg = f"HTTP {response.status}: {error_text}"
                        self.error_count += 1
                        return False, None, error_msg
            
            except asyncio.TimeoutError as e:
                last_exception = e
                error_msg = f"请求超时 ({timeout}秒)"
                
                if attempt < retries:
                    logger.warning(f"⚠️ {error_msg}，准备重试 (第 {attempt + 1}/{retries + 1} 次)")
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
                else:
                    self.error_count += 1
                    return False, None, error_msg
            
            except aiohttp.ClientError as e:
                last_exception = e
                error_msg = f"客户端错误: {str(e)}"
                
                if attempt < retries:
                    logger.warning(f"⚠️ {error_msg}，准备重试 (第 {attempt + 1}/{retries + 1} 次)")
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
                else:
                    self.error_count += 1
                    return False, None, error_msg
            
            except Exception as e:
                last_exception = e
                error_msg = f"未知错误: {str(e)}"
                logger.error(f"❌ 请求异常: {error_msg}", exc_info=True)
                self.error_count += 1
                return False, None, error_msg
        
        # 所有重试都失败
        if last_exception:
            error_msg = f"请求最终失败，已重试 {retries} 次: {str(last_exception)}"
        else:
            error_msg = f"请求失败，已重试 {retries} 次"
        
        self.error_count += 1
        return False, None, error_msg
    
    async def get(self, url: str, **kwargs) -> Tuple[bool, Optional[Union[Dict, str]], Optional[str]]:
        """GET请求的便捷方法"""
        return await self.make_request(url, method='GET', **kwargs)
    
    async def post(self, url: str, **kwargs) -> Tuple[bool, Optional[Union[Dict, str]], Optional[str]]:
        """POST请求的便捷方法"""
        return await self.make_request(url, method='POST', **kwargs)
    
    async def put(self, url: str, **kwargs) -> Tuple[bool, Optional[Union[Dict, str]], Optional[str]]:
        """PUT请求的便捷方法"""
        return await self.make_request(url, method='PUT', **kwargs)
    
    async def delete(self, url: str, **kwargs) -> Tuple[bool, Optional[Union[Dict, str]], Optional[str]]:
        """DELETE请求的便捷方法"""
        return await self.make_request(url, method='DELETE', **kwargs)
    
    async def head(self, url: str, **kwargs) -> Tuple[bool, Optional[Union[Dict, str]], Optional[str]]:
        """HEAD请求的便捷方法"""
        return await self.make_request(url, method='HEAD', **kwargs)
    
    async def check_health(self, url: str, timeout: int = 10) -> bool:
        """
        检查服务健康状态
        
        Args:
            url: 健康检查URL
            timeout: 超时时间
        
        Returns:
            bool: 是否健康
        """
        try:
            success, _, _ = await self.make_request(
                url, method='GET', timeout=timeout, retries=0
            )
            return success
        except Exception as e:
            logger.debug(f"健康检查失败: {e}")
            return False
    
    async def download_file(
        self,
        url: str,
        file_path: str,
        chunk_size: int = 8192,
        timeout: int = 300
    ) -> bool:
        """
        下载文件
        
        Args:
            url: 文件URL
            file_path: 本地文件路径
            chunk_size: 分块大小
            timeout: 超时时间
        
        Returns:
            bool: 是否成功
        """
        try:
            await self.create_session()
            
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                if response.status == 200:
                    import os
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    
                    with open(file_path, 'wb') as file:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            file.write(chunk)
                    
                    logger.info(f"✅ 文件下载成功: {file_path}")
                    return True
                else:
                    logger.error(f"❌ 文件下载失败: HTTP {response.status}")
                    return False
        
        except Exception as e:
            logger.error(f"❌ 下载文件异常: {e}", exc_info=True)
            return False
    
    async def upload_file(
        self,
        url: str,
        file_path: str,
        field_name: str = 'file',
        additional_data: Optional[Dict[str, Any]] = None,
        timeout: int = 300
    ) -> Tuple[bool, Optional[Union[Dict, str]], Optional[str]]:
        """
        上传文件
        
        Args:
            url: 上传URL
            file_path: 本地文件路径
            field_name: 文件字段名
            additional_data: 额外的表单数据
            timeout: 超时时间
        
        Returns:
            Tuple[bool, Optional[Union[Dict, str]], Optional[str]]: (成功状态, 响应数据, 错误信息)
        """
        try:
            await self.create_session()
            
            # 创建表单数据
            data = aiohttp.FormData()
            
            # 添加文件
            with open(file_path, 'rb') as file:
                data.add_field(field_name, file, filename=os.path.basename(file_path))
            
            # 添加额外数据
            if additional_data:
                for key, value in additional_data.items():
                    data.add_field(key, str(value))
            
            # 发起上传请求
            async with self.session.post(
                url,
                data=data,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status == 200:
                    try:
                        response_data = await response.json()
                        logger.info(f"✅ 文件上传成功: {file_path}")
                        return True, response_data, None
                    except json.JSONDecodeError:
                        response_data = await response.text()
                        return True, response_data, None
                else:
                    error_text = await response.text()
                    error_msg = f"HTTP {response.status}: {error_text}"
                    logger.error(f"❌ 文件上传失败: {error_msg}")
                    return False, None, error_msg
        
        except Exception as e:
            error_msg = f"上传文件异常: {str(e)}"
            logger.error(f"❌ {error_msg}", exc_info=True)
            return False, None, error_msg
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取客户端统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        total_requests = self.request_count
        success_rate = (self.success_count / total_requests * 100) if total_requests > 0 else 0
        
        return {
            'total_requests': total_requests,
            'success_count': self.success_count,
            'error_count': self.error_count,
            'success_rate': f"{success_rate:.1f}%",
            'max_retries': self.max_retries,
            'retry_delay': self.retry_delay,
            'default_timeout': self.default_timeout
        }
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        self.request_count = 0
        self.success_count = 0
        self.error_count = 0
    
    def configure_retries(self, max_retries: int, retry_delay: int = 2) -> None:
        """
        配置重试参数
        
        Args:
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        logger.info(f"🔧 API客户端重试配置已更新: 最大重试{max_retries}次, 延迟{retry_delay}秒")
    
    def configure_timeout(self, timeout: int) -> None:
        """
        配置默认超时时间
        
        Args:
            timeout: 超时时间（秒）
        """
        self.default_timeout = timeout
        logger.info(f"🔧 API客户端超时配置已更新: {timeout}秒") 