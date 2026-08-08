"""add finding retry fields

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-03-18

"""
from alembic import op
import sqlalchemy as sa

revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('control_findings', sa.Column('raw_llm_response', sa.Text, nullable=True))
    op.add_column('control_findings', sa.Column('needs_manual_review', sa.Boolean, nullable=False, server_default='false'))
    op.add_column('control_findings', sa.Column('retry_count', sa.Integer, nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('control_findings', 'retry_count')
    op.drop_column('control_findings', 'needs_manual_review')
    op.drop_column('control_findings', 'raw_llm_response')
