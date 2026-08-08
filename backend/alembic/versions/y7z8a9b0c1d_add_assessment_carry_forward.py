"""add carry-forward flag to assessments

Revision ID: y7z8a9b0c1d
Revises: x6y7z8a9b0c
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "y7z8a9b0c1d"
down_revision = "x6y7z8a9b0c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_columns = {column["name"] for column in inspect(bind).get_columns("assessments")}
    if "carry_forward_compliant" in existing_columns:
        return

    op.add_column(
        "assessments",
        sa.Column(
            "carry_forward_compliant",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.alter_column("assessments", "carry_forward_compliant", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {column["name"] for column in inspect(bind).get_columns("assessments")}
    if "carry_forward_compliant" in existing_columns:
        op.drop_column("assessments", "carry_forward_compliant")
