import uuid
from datetime import datetime

from pydantic import BaseModel

from api.schemas.extraction import CitationOut


class ConflictingValueOut(BaseModel):
    extraction_id: uuid.UUID
    value: str | None
    epistemic_status: str
    # every corroborating source for this one conflicting value, not just the
    # first - a value several files agree on (and therefore merged into one
    # Extraction row) still needs each of those files to show up here
    citations: list[CitationOut] = []


class ConflictOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    field_name: str
    conflicting_extraction_ids: list[uuid.UUID]
    conflicting_values: list[ConflictingValueOut] = []
    conflict_summary: str | None
    status: str
    resolved_value: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


class ConflictResolveRequest(BaseModel):
    resolved_value: dict | None = None
