"""add objective adjudication debug fields

Revision ID: z8a9b0c1d2e3
Revises: y7z8a9b0c1d
Create Date: 2026-04-20 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "z8a9b0c1d2e3"
down_revision = "y7z8a9b0c1d"
branch_labels = None
depends_on = None


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    if column.name not in existing:
        op.add_column(table_name, column)


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    if column_name in existing:
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    _add_column_if_missing(
        "objective_evidence_reviews",
        sa.Column("packet_id", sa.String(length=128), nullable=True),
    )
    _add_column_if_missing(
        "objective_determinations",
        sa.Column("raw_llm_result", sa.JSON(), nullable=True),
    )
    _add_column_if_missing(
        "objective_determinations",
        sa.Column("adjudication_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    _drop_column_if_present("objective_determinations", "adjudication_json")
    _drop_column_if_present("objective_determinations", "raw_llm_result")
    _drop_column_if_present("objective_evidence_reviews", "packet_id")
