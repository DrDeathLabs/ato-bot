"""add prompt_overrides table

Revision ID: i0d1e2f3a4b5
Revises: h9c0d1e2f3a4
Create Date: 2026-03-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'i0d1e2f3a4b5'
down_revision = 'h9c0d1e2f3a4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'prompt_overrides',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_by', sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('prompt_overrides')
