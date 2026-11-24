import uuid
from datetime import datetime

from pydantic import BaseModel


class BatchOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    status: str
    status_detail: dict
    reconciliation_version: int
    created_at: datetime

    class Config:
        from_attributes = True
