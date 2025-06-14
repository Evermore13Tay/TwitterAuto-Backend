from sqlalchemy import Column, String, Integer, UniqueConstraint, Index, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from db.database import Base
import uuid

class DeviceUser(Base):
    __tablename__ = "device_users"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    device_ip = Column(String(15), nullable=False, index=True)
    box_ip = Column(String(15), nullable=True, index=True)
    u2_port = Column(Integer, nullable=True)
    myt_rpc_port = Column(Integer, nullable=True)
    username = Column(String(50), nullable=True, index=True)
    password = Column(String(50), nullable=True)
    secret_key = Column(String(16), nullable=True)
    device_name = Column(String(100), nullable=False, unique=True, index=True)
    device_index = Column(Integer, nullable=True, index=True)
    status = Column(String(20), nullable=False, default="offline", index=True)
    # 添加代理相关字段
    proxy_ip = Column(String(50), nullable=True, comment="代理服务器IP地址")
    proxy_port = Column(Integer, nullable=True, comment="代理服务器端口")
    language = Column(String(10), nullable=True, default="en", comment="账号使用的语言设置")
    # 添加分组字段
    group_name = Column(String(100), nullable=True, default="默认分组", comment="设备分组名称")
    # 添加忙碌状态字段
    is_busy = Column(Integer, nullable=True, default=0, comment="设备是否忙碌(0-空闲,1-忙碌)")
    
    __table_args__ = (
        Index('idx_device_ip_status', 'device_ip', 'status'),
        Index('idx_box_ip_status', 'box_ip', 'status'),
        Index('idx_device_ip_device_index', 'device_ip', 'device_index'),
    )
    
    def __init__(self, **kwargs):
        if 'id' not in kwargs:
            kwargs['id'] = str(uuid.uuid4())
        super().__init__(**kwargs)

class BoxIP(Base):
    """用户自定义盒子IP地址表"""
    __tablename__ = "box_ips"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    ip_address = Column(String(15), nullable=False, unique=True, index=True, comment="盒子IP地址")
    name = Column(String(100), nullable=True, comment="盒子名称/备注")
    description = Column(String(255), nullable=True, comment="盒子描述")
    status = Column(String(20), nullable=False, default="active", comment="状态：active-启用, inactive-禁用")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    __table_args__ = (
        Index('idx_box_ip_address', 'ip_address'),
        Index('idx_box_ip_status', 'status'),
    )
    
    def __init__(self, **kwargs):
        if 'id' not in kwargs:
            kwargs['id'] = str(uuid.uuid4())
        super().__init__(**kwargs)

class Proxy(Base):
    """代理服务器表"""
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    ip = Column(String(15), nullable=False, index=True, comment="代理IP地址")
    port = Column(Integer, nullable=False, comment="代理端口")
    username = Column(String(100), nullable=True, comment="代理用户名")
    password = Column(String(100), nullable=True, comment="代理密码")
    proxy_type = Column(String(20), nullable=False, default="http", comment="代理类型：http, https, socks5")
    country = Column(String(10), nullable=True, comment="代理所在国家/地区")
    status = Column(String(20), nullable=False, default="active", comment="状态：active-启用, inactive-禁用")
    name = Column(String(100), nullable=True, comment="代理名称/备注")
    created_time = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_time = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 反向关系
    accounts = relationship("SocialAccount", back_populates="proxy")
    
    __table_args__ = (
        Index('idx_proxy_ip_port', 'ip', 'port'),
        Index('idx_proxy_status', 'status'),
        Index('idx_proxy_country', 'country'),
        UniqueConstraint('ip', 'port', 'username', name='uk_proxy_unique'),
    )

class AccountGroup(Base):
    __tablename__ = "account_groups"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True, comment="分组名称")
    description = Column(Text, nullable=True, comment="分组描述")
    color = Column(String(7), nullable=False, default="#2196f3", comment="分组颜色(hex)")
    created_time = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_time = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 反向关系
    accounts = relationship("SocialAccount", back_populates="group")

class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(255), nullable=False, unique=True, index=True, comment="社媒账号用户名")
    password = Column(String(255), nullable=False, comment="账号密码")
    secret_key = Column(String(255), nullable=True, comment="2FA密钥")
    platform = Column(String(50), nullable=False, default="twitter", index=True, comment="平台类型")
    status = Column(String(50), nullable=False, default="active", index=True, comment="账号状态")
    group_id = Column(Integer, ForeignKey("account_groups.id"), nullable=True, index=True, comment="所属分组ID")
    proxy_id = Column(Integer, ForeignKey("proxies.id"), nullable=True, index=True, comment="关联的代理ID")
    last_login_time = Column(DateTime, nullable=True, comment="最后登录时间")
    backup_exported = Column(Integer, nullable=False, default=0, comment="是否已导出备份(0-未导出,1-已导出)")
    created_time = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_time = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    notes = Column(Text, nullable=True, comment="备注信息")
    
    # 关系
    group = relationship("AccountGroup", back_populates="accounts")
    proxy = relationship("Proxy", back_populates="accounts")
    
    __table_args__ = (
        Index('idx_username_platform', 'username', 'platform'),
        Index('idx_status_platform', 'status', 'platform'),
        Index('idx_group_id', 'group_id'),
        Index('idx_proxy_id', 'proxy_id'),
        Index('idx_backup_exported', 'backup_exported'),
    )

# 新增：推文作品库分类表
class TweetCategory(Base):
    __tablename__ = "tweet_categories"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True, index=True, comment="分类名称")
    description = Column(Text, nullable=True, comment="分类描述")
    color = Column(String(7), nullable=False, default="#2196f3", comment="分类颜色(hex)")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序顺序")
    created_time = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_time = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 反向关系
    tweets = relationship("TweetTemplate", back_populates="category")
    
    __table_args__ = (
        Index('idx_category_name', 'name'),
        Index('idx_category_sort', 'sort_order'),
    )

# 新增：推文模板表
class TweetTemplate(Base):
    __tablename__ = "tweet_templates"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(200), nullable=False, index=True, comment="推文标题")
    content = Column(Text, nullable=False, comment="推文内容")
    category_id = Column(Integer, ForeignKey("tweet_categories.id"), nullable=True, index=True, comment="所属分类ID")
    tags = Column(String(500), nullable=True, comment="标签，逗号分隔")
    is_favorite = Column(Integer, nullable=False, default=0, comment="是否收藏(0-否,1-是)")
    use_count = Column(Integer, nullable=False, default=0, comment="使用次数")
    last_used_time = Column(DateTime, nullable=True, comment="最后使用时间")
    status = Column(String(20), nullable=False, default="active", comment="状态：active-启用, inactive-禁用")
    created_time = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_time = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 关系
    category = relationship("TweetCategory", back_populates="tweets")
    images = relationship("TweetImage", back_populates="tweet", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_tweet_title', 'title'),
        Index('idx_tweet_category', 'category_id'),
        Index('idx_tweet_status', 'status'),
        Index('idx_tweet_favorite', 'is_favorite'),
        Index('idx_tweet_created', 'created_time'),
    )

# 新增：推文图片表
class TweetImage(Base):
    __tablename__ = "tweet_images"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    tweet_id = Column(Integer, ForeignKey("tweet_templates.id", ondelete="CASCADE"), nullable=False, index=True, comment="关联推文ID")
    original_name = Column(String(255), nullable=False, comment="原始文件名")
    file_name = Column(String(255), nullable=False, comment="存储文件名")
    file_path = Column(String(500), nullable=False, comment="文件存储路径")
    file_size = Column(Integer, nullable=False, comment="文件大小(字节)")
    mime_type = Column(String(100), nullable=False, comment="文件MIME类型")
    width = Column(Integer, nullable=True, comment="图片宽度")
    height = Column(Integer, nullable=True, comment="图片高度")
    sort_order = Column(Integer, nullable=False, default=0, comment="图片排序")
    created_time = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    
    # 关系
    tweet = relationship("TweetTemplate", back_populates="images")
    
    __table_args__ = (
        Index('idx_image_tweet_id', 'tweet_id'),
        Index('idx_image_sort', 'tweet_id', 'sort_order'),
    )