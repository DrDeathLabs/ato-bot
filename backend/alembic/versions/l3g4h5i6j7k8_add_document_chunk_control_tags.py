"""Add document_chunk_control_tags table.

Revision ID: l3g4h5i6j7k8
Revises: k2f3a4b5c6d7
Create Date: 2026-03-20
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "l3g4h5i6j7k8"
down_revision = "k2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_chunk_control_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("control_id", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("relevance_notes", sa.Text(), nullable=True),
        sa.Column("tagged_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_chunk_control_tags_chunk_id", "document_chunk_control_tags", ["chunk_id"])
    op.create_index("ix_document_chunk_control_tags_control_id", "document_chunk_control_tags", ["control_id"])


def downgrade() -> None:
    op.drop_index("ix_document_chunk_control_tags_control_id", table_name="document_chunk_control_tags")
    op.drop_index("ix_document_chunk_control_tags_chunk_id", table_name="document_chunk_control_tags")
    op.drop_table("document_chunk_control_tags")
