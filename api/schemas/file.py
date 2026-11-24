import uuid
from datetime import datetime

from pydantic import BaseModel


class FileOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    original_filename: str
    file_type: str
    size_bytes: int
    status: str
    parse_error: str | None
    created_at: datetime

    class Config:
        from_attributes = True
