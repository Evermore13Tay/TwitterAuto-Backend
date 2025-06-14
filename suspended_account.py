from sqlalchemy import Column, String, DateTime, Text
from db.database import Base
import uuid
from datetime import datetime

class SuspendedAccount(Base):
    __tablename__ = "suspended_accounts"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), nullable=False, index=True)
    device_ip = Column(String(15), nullable=False)
    device_name = Column(String(100), nullable=True)
    suspended_at = Column(DateTime, default=datetime.utcnow)
    details = Column(Text, nullable=True)
    
    def __init__(self, **kwargs):
        if 'id' not in kwargs:
            kwargs['id'] = str(uuid.uuid4())
        if 'suspended_at' not in kwargs:
            kwargs['suspended_at'] = datetime.utcnow()
        super().__init__(**kwargs)
