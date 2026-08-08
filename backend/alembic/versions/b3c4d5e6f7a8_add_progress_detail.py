"""add progress_detail to assessments

Revision ID: b3c4d5e6f7a8
Revises: a2f3b1c4d5e6
Create Date: 2026-03-18

"""
from alembic import op
import sqlalchemy as sa

revision = 'b3c4d5e6f7a8'
down_revision = 'a2f3b1c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('assessments', sa.Column('progress_detail', sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column('assessments', 'progress_detail')
