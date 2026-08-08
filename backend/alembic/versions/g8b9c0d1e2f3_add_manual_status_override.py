"""add manual status override to control_overrides

Revision ID: g8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-03-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'g8b9c0d1e2f3'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('control_overrides', sa.Column('manual_status', sa.String(32), nullable=True))
    op.add_column('control_overrides', sa.Column('manual_status_rationale', sa.Text(), nullable=True))
    op.add_column('control_overrides', sa.Column('manual_status_set_by', sa.String(64), nullable=True))
    op.add_column('control_overrides', sa.Column('manual_status_set_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('control_overrides', 'manual_status_set_at')
    op.drop_column('control_overrides', 'manual_status_set_by')
    op.drop_column('control_overrides', 'manual_status_rationale')
    op.drop_column('control_overrides', 'manual_status')
