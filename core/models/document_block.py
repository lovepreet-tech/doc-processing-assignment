"""A parsed chunk of a PDF/scan: a heading, paragraph, table, etc.

Parsed once per file, not per batch.
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.config import get_settings
from core.db import Base
from core.models.mixins import TenantScopedMixin, UUIDPrimaryKeyMixin

settings = get_settings()


class DocumentBlock(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    __tablename__ = "document_blocks"

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )

    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_type: Mapped[str] = mapped_column(String, nullable=False)
    bbox: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [x0, y0, x1, y1]
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    table_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reading_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # pgvector embedding of `text`, filled in by ingestion/nodes/embed_chunks.py
    # (stays null without an OPENAI_API_KEY). Queried via cosine_distance in
    # extraction/nodes/retrieve.py.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.openai_embedding_dim), nullable=True)

    # null for native text, set when the block came from OCR
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_vlm_review: Mapped[bool] = mapped_column(Boolean, default=False)

    # breadcrumb like "Section 3 > Methodology", used to build narrative chunk context
    source_section_path: Mapped[str | None] = mapped_column(String, nullable=True)

    file = relationship("File", back_populates="blocks")
