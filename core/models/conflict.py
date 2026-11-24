"""A detected disagreement between two or more extractions of the same field in a batch."""

import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base
from core.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Conflict(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "conflicts"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    field_name: Mapped[str] = mapped_column(String, nullable=False)
    conflicting_extraction_ids: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    conflict_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String, default="OPEN")  # OPEN | ACKNOWLEDGED | RESOLVED
    resolved_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
