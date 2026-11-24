"""A single extracted field (or logic trace) produced by an extraction run for a batch."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base
from core.models.mixins import TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Extraction(UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin, Base):
    __tablename__ = "extractions"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )

    field_name: Mapped[str] = mapped_column(String, nullable=False)  # normalized key
    field_category: Mapped[str] = mapped_column(String, nullable=False)  # client_info/property_detail/valuation_info/logic
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_normalized: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # explicit | inferred | undetermined - see extraction/nodes/tag_epistemic_status.py
    epistemic_status: Mapped[str] = mapped_column(String, nullable=False)
    # formula_trace | narrative_rule | supporting_input | conflict
    evidence_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reasoning_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # matches batches.reconciliation_version at the time this row was produced
    reconciliation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # old rows are kept (not deleted) for audit when a batch is re-reconciled
    superseded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    citations = relationship("Citation", back_populates="extraction", cascade="all, delete-orphan")
