# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path
import site

# 获取当前目录
current_dir = os.path.abspath(os.path.dirname('main.py'))

# 获取uiautomator2资源文件路径
def get_site_packages_path():
    # 获取site-packages目录
    for path in site.getsitepackages():
        if 'site-packages' in path:
            return path
    return None

site_packages = get_site_packages_path()
uiautomator2_assets_path = None
if site_packages:
    uiautomator2_assets_path = os.path.join(site_packages, 'uiautomator2', 'assets')
    print(f"UIAutomator2 assets path: {uiautomator2_assets_path}")
    if not os.path.exists(uiautomator2_assets_path):
        print(f"Warning: UIAutomator2 assets path does not exist: {uiautomator2_assets_path}")
        uiautomator2_assets_path = None

# 检查关键文件是否存在的函数
def check_and_add_file(file_path, target_path=None):
    """检查文件是否存在，如果存在则添加到数据列表"""
    if os.path.exists(file_path):
        return (file_path, target_path or os.path.dirname(file_path))
    else:
        print(f"Warning: File not found: {file_path}")
        return None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # 添加所需的静态文件和数据
    datas=[
        # 包含static文件夹及其内容
        ('static', 'static'),
        # 包含lib目录及其DLL文件
        ('lib', 'lib'),
        
        # 添加automation目录下的Python脚本
        ('automation/logintest.py', 'automation'),
        ('automation/interactTest.py', 'automation'),
        ('automation/changeNicknameTest.py', 'automation'),
        ('automation/changeProfileTest.py', 'automation'),
        ('automation/changeSignatureTest.py', 'automation'),
        ('automation/followTest.py', 'automation'),
        ('automation/postTweetTest.py', 'automation'),
        ('automation/BoxManipulate.py', 'automation'),
        ('automation/get_device_by_ip.py', 'automation'),
        
        # 添加routes目录及其所有子文件
        ('routes', 'routes'),
        
        # 添加api目录及其所有子文件
        ('api', 'api'),
        
        # 添加tasks_modules目录（重要的任务模块）
        ('tasks_modules', 'tasks_modules'),
        
        # 添加其他重要脚本（在backend根目录下的文件）
        ('getDevice.py', '.'),
        ('check_twitter_login_status.py', '.'),
        ('suspended_account.py', '.'),
        ('tasks_api.py', '.'),
        ('mysql_tasks_api.py', '.'),
        
        # 添加清理和测试工具
        check_and_add_file('cleanup_active_tasks.py', '.'),
        check_and_add_file('force_clear_task.py', '.'),
        
        # 添加数据库相关文件
        ('db', 'db'),
        
        # 添加服务目录
        ('services', 'services'),
        
        # 添加utils目录
        ('utils', 'utils'),
        
        # 添加schemas目录
        ('schemas', 'schemas'),
        
        # 添加common目录
        ('common', 'common'),
        
        # 添加requirements.txt
        ('requirements.txt', '.'),
        
        # 添加数据库文件（如果存在）
        check_and_add_file('twitter_automation.db', '.'),
        
        # 添加配置文件
        check_and_add_file('start_backend.bat', '.'),
        
        # 添加日志目录（如果存在）
        check_and_add_file('logs', 'logs') if os.path.exists('logs') else None,
        
        # 添加临时目录（如果存在）
        check_and_add_file('temp', 'temp') if os.path.exists('temp') else None,
        
    ] + ([('{}/*'.format(uiautomator2_assets_path), 'uiautomator2/assets')] if uiautomator2_assets_path else []),
    hiddenimports=[
        # 主要依赖包
        'fastapi', 'uvicorn', 'sqlalchemy', 'pymysql', 'websockets',
        'pydantic', 'pydantic_settings', 'passlib', 'jose', 'bcrypt', 'multipart',
        'dotenv', 'cryptography', 'uiautomator2', 'aiofiles',
        'starlette', 'starlette.routing', 'starlette.applications', 'starlette.responses',
        'async_timeout', 'typing_extensions', 'attrs', 'charset_normalizer',
        'urllib3', 'httpx', 'httpcore', 'idna', 'sniffio', 'anyio',
        'pyotp', 'selenium', 'webdriver_manager',
        
        # 路由模块和子包（更新所有路由文件）
        'routes', 'routes.__init__',
        'routes.accounts', 'routes.tasks', 'routes.tasks_new', 'routes.proxies', 'routes.groups',
        'routes.box_ips', 'routes.login_routes', 'routes.interaction_routes', 
        'routes.websocket_routes', 'routes.change_profile_routes', 'routes.change_signature_routes',
        'routes.change_nickname_routes', 'routes.follow_routes', 'routes.post_tweet_routes',
        'routes.static_routes',
        
        # 路由子目录
        'routes.device', 'routes.device.__init__', 'routes.device.crud', 'routes.device.proxy',
        'routes.device.sync', 'routes.device.sync_backup', 'routes.device.container', 'routes.device.utils',
        'routes.container', 'routes.container.__init__', 'routes.container.image', 'routes.container.reboot',
        'routes.container.config', 'routes.container.logs', 'routes.container.management',
        'routes.container.export', 'routes.container.file_mgmt',
        
        # API模块和子包
        'api', 'api.__init__', 'api.twitter_polling', 'api.update_device_proxy',
        
        # 任务模块（重要模块）
        'tasks_modules', 'tasks_modules.__init__', 'tasks_modules.batch_operations',
        'tasks_modules.device_utils', 'tasks_modules.api_handlers', 'tasks_modules.rpc_repair',
        'tasks_modules.login_backup', 'tasks_modules.models',
        
        # 服务和工具模块
        'services', 'services.__init__', 'services.login_service', 'services.optimized_login_service',
        'common', 'common.__init__', 'common.base_path_util', 'common.mytRpc', 'common.ToolsKit',
        'common.logger', 'common.mytSelector', 'common.u2_reconnector', 'common.u2_connection', 
        'common.twitter_ui_handlers',
        
        # 数据库和模型
        'database', 'getDevice', 'models',
        'db', 'db.__init__', 'db.database', 'db.models', 'db.create_db', 'db.update_db_schema',
        
        # 自动化模块
        'automation', 'automation.__init__',
        'automation.logintest', 'automation.BoxManipulate', 'automation.changeNicknameTest', 
        'automation.changeProfileTest', 'automation.changeSignatureTest',
        'automation.followTest', 'automation.interactTest', 'automation.postTweetTest', 
        'automation.get_device_by_ip',
        
        # utils模块（包含新的关键模块）
        'utils', 'utils.__init__', 'utils.callbacks', 'utils.connection', 'utils.task_executor',
        'utils.advanced_task_executor', 'utils.optimized_nurture_executor', 'utils.port_manager',
        'utils.task_cancellation',  # 🚀 新增：关键的任务取消模块
        
        # schemas模块
        'schemas', 'schemas.__init__', 'schemas.models',
        
        # 其他模块
        'suspended_account', 'check_twitter_login_status', 'tasks_api', 'mysql_tasks_api',
        
        # uvicorn依赖
        'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.on',
        
        # FastAPI相关依赖
        'fastapi.routing', 'fastapi.middleware', 'fastapi.middleware.cors',
        'fastapi.middleware.trustedhost', 'fastapi.staticfiles',
        
        # Pydantic相关
        'pydantic.fields', 'pydantic.main', 'pydantic.types', 'pydantic.validators',
        'pydantic_settings.sources',
        
        # 额外的依赖
        'PIL', 'Pillow', 'adbutils', 'packaging', 'retry', 'cached_property',
        'python-multipart', 'python-jose', 'passlib.context',
        
        # 网络和HTTP相关
        'aiohttp', 'aiohttp.client', 'aiohttp.web', 'requests',
        
        # Selenium和WebDriver相关
        'selenium.webdriver', 'selenium.webdriver.chrome', 'selenium.webdriver.common',
        'webdriver_manager.chrome', 'webdriver_manager.core',
        
        # OTP相关
        'pyotp',
        
        # JSON和HTTP相关
        'json', 'http', 'http.client', 'urllib.parse',
        
        # asyncio相关（用于新的并行执行功能）
        'asyncio', 'asyncio.subprocess', 'asyncio.queues', 'asyncio.tasks',
        'concurrent.futures', 'threading', 'multiprocessing',
        
        # 其他重要的运行时依赖
        'time', 'datetime', 'logging', 'traceback', 'sys', 'os', 'pathlib',
        'collections', 'itertools', 'functools', 'operator',
        
        # 队列和同步模块
        'queue', 'threading', 'multiprocessing.pool',
        
        # 加密和安全模块
        'hashlib', 'hmac', 'secrets', 'base64',
        
        # 文件和IO模块
        'shutil', 'glob', 'tempfile', 'zipfile', 'tarfile',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# 过滤掉None值（用于条件包含的数据文件）
a.datas = [item for item in a.datas if item is not None]

# 确保正确收集相关模块的子模块
from PyInstaller.utils.hooks import collect_submodules

# 添加multiprocessing模块的依赖
hidden_imports = collect_submodules('multiprocessing')
a.hiddenimports.extend(hidden_imports)

# 添加uiautomator2模块的依赖
u2_imports = collect_submodules('uiautomator2')
a.hiddenimports.extend(u2_imports)

# 添加FastAPI模块的依赖
fastapi_imports = collect_submodules('fastapi')
a.hiddenimports.extend(fastapi_imports)

# 添加SQLAlchemy模块的依赖
sqlalchemy_imports = collect_submodules('sqlalchemy')
a.hiddenimports.extend(sqlalchemy_imports)

# 添加asyncio相关模块的依赖（用于并行执行）
asyncio_imports = collect_submodules('asyncio')
a.hiddenimports.extend(asyncio_imports)

# 添加aiohttp模块的依赖（用于异步HTTP请求）
aiohttp_imports = collect_submodules('aiohttp')
a.hiddenimports.extend(aiohttp_imports)

# 添加websockets模块的依赖
websockets_imports = collect_submodules('websockets')
a.hiddenimports.extend(websockets_imports)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TwitterAuto',  # 输出文件名
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 使用控制台模式便于查看日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 如果有图标文件可以在此处添加
)
