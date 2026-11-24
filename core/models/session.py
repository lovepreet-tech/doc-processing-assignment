"""A `session` is the top-level container a client works in - roughly one engagement/case."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base
from core.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Session(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)

    # ACTIVE -> CLOSED, or ACTIVE -> EXPIRED once retention_ttl_days passes
    status: Mapped[str] = mapped_column(String, default="ACTIVE", nullable=False)
    retention_ttl_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    batches = relationship("Batch", back_populates="session", cascade="all, delete-orphan")
