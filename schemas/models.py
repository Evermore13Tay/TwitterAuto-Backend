from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime

# --- Device User Models ---
class DeviceUserBase(BaseModel):
    device_ip: str
    box_ip: Optional[str] = None
    u2_port: Optional[int] = None
    myt_rpc_port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    secret_key: Optional[str] = None
    device_name: str
    device_index: Optional[int] = None
    status: Optional[str] = "offline"  # 默认状态为"offline"

    class Config:
        from_attributes = True

class DeviceUserCreate(DeviceUserBase):
    pass

class DeviceUser(DeviceUserBase):
    id: str | None = None
    proxy_ip: Optional[str] = None    # 代理IP
    proxy_port: Optional[int] = None  # 代理端口
    language: Optional[str] = "en"    # 语言设置
    proxy: Optional[str] = None       # 默认无代理
    is_suspended: Optional[bool] = False  # 账号是否被封

class DeviceUserUpdate(BaseModel):
    device_ip: Optional[str] = None
    box_ip: Optional[str] = None
    u2_port: Optional[int] = None
    myt_rpc_port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    secret_key: Optional[str] = None
    device_name: Optional[str] = None
    device_index: Optional[int] = None
    status: Optional[str] = None

    class Config:
        from_attributes = True

class DeviceCredentialsUpdateRequest(BaseModel):
    username: str
    password: str
    secret_key: Optional[str] = None

    class Config:
        from_attributes = True

# --- Login Models ---
class LoginRequest(BaseModel):
    deviceIp: str
    u2Port: str
    mytRpcPort: str
    username: str
    password: str
    secretKey: str

class LoginResponse(BaseModel):
    success: bool
    message: str
    status: str = ""
    progress: int = 0

class BatchLoginRequest(BaseModel):
    device_users: List[DeviceUser]

# --- Interaction Models ---
class InteractionParams(BaseModel):
    duration_seconds: int = Field(default=160, ge=10, le=7200)
    enable_liking: bool = True
    enable_commenting: bool = False
    comment_text: str = Field(default="Great tweet!", max_length=280)
    prob_interact_tweet: float = Field(default=0.3, ge=0.0, le=1.0)
    prob_like_opened: float = Field(default=0.6, ge=0.0, le=1.0)
    prob_comment_opened: float = Field(default=0.4, ge=0.0, le=1.0)

class InteractionRequest(BaseModel):
    device_ip: str
    u2_port: int
    myt_rpc_port: int
    params: InteractionParams

class BatchInteractionRequest(BaseModel):
    devices: List[DeviceUser]
    params: InteractionParams 

# --- Suspended Account Model ---
class SuspendedAccount(BaseModel):
    username: str
    device_ip: str
    device_name: Optional[str] = None
    suspended_at: Optional[str] = None
    details: Optional[str] = None
    
    class Config:
        from_attributes = True

# --- Box IP Models ---
class BoxIPBase(BaseModel):
    ip_address: str = Field(..., description="盒子IP地址")
    name: Optional[str] = Field(None, description="盒子名称/备注")
    description: Optional[str] = Field(None, description="盒子描述")
    status: Optional[str] = Field("active", description="状态：active-启用, inactive-禁用")

    class Config:
        from_attributes = True

class BoxIPCreate(BoxIPBase):
    pass

class BoxIPUpdate(BaseModel):
    ip_address: Optional[str] = Field(None, description="盒子IP地址")
    name: Optional[str] = Field(None, description="盒子名称/备注")
    description: Optional[str] = Field(None, description="盒子描述")
    status: Optional[str] = Field(None, description="状态")

    class Config:
        from_attributes = True

class BoxIP(BoxIPBase):
    id: str
    created_at: datetime
    updated_at: datetime