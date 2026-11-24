"""Move semantic search off Qdrant onto pgvector: enable the vector extension and
add an `embedding` column directly on document_blocks. Searched with a plain SQL
ORDER BY cosine_distance per file (see extraction/nodes/retrieve.py) - no ANN
index yet, since this app's per-batch document volume is small enough that a
sequential scan is fine; add an ivfflat/HNSW index later if that stops being true.

Spreadsheet cells are intentionally not embedded - retrieve.py's structural
header-text fuzzy match already covers them more precisely than semantic search
would for short label/value pairs.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-24
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1536  # must match Settings.openai_embedding_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("document_blocks", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True))


def downgrade() -> None:
    op.drop_column("document_blocks", "embedding")
    # deliberately not dropping the vector extension - other objects/data may
    # depend on it by the time anyone downgrades this far
