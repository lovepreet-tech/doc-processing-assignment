import uuid
from datetime import datetime

from pydantic import BaseModel


class SessionCreate(BaseModel):
    name: str | None = None
    retention_ttl_days: int = 90


class SessionOut(BaseModel):
    id: uuid.UUID
    name: str | None
    status: str
    retention_ttl_days: int
    created_at: datetime

    class Config:
        from_attributes = True
