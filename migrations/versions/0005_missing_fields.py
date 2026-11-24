"""extraction jobs: missing_fields - DATA fields the query asked about that no
uploaded file had evidence for, reported explicitly by the LLM (see
extraction/llm_client.py) instead of being silently omitted.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("extraction_jobs", sa.Column("missing_fields", pg.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("extraction_jobs", "missing_fields")
