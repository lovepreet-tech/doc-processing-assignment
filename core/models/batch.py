"""A `batch` groups the files a user wants reconciled together within a session."""

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base
from core.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Batch(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "batches"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )

    # PENDING -> INGESTING -> READY, or FAILED/PARTIAL if some files errored
    status: Mapped[str] = mapped_column(String, default="PENDING", nullable=False)

    # free-form per-file progress snapshot, e.g. {"file_id": "parsing_blocks", ...}
    status_detail: Mapped[dict] = mapped_column(JSONB, default=dict)

    # bumped every time cross-document reconciliation reruns (new file added, etc.)
    reconciliation_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    session = relationship("Session", back_populates="batches")
    files = relationship("File", back_populates="batch", cascade="all, delete-orphan")
