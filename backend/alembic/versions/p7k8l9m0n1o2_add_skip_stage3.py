"""add skip_stage3 to assessment

Revision ID: p7k8l9m0n1o2
Revises: o6j7k8l9m0n1
Create Date: 2026-03-21

"""
from alembic import op
import sqlalchemy as sa

revision = 'p7k8l9m0n1o2'
down_revision = 'o6j7k8l9m0n1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('assessments', sa.Column('skip_stage3', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('assessments', 'skip_stage3')
