"""add assessment paused_at

Revision ID: a2f3b1c4d5e6
Revises: 71d0bd8e0961
Create Date: 2026-03-18

"""
from alembic import op
import sqlalchemy as sa

revision = 'a2f3b1c4d5e6'
down_revision = '71d0bd8e0961'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('assessments', sa.Column('paused_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('assessments', 'paused_at')
