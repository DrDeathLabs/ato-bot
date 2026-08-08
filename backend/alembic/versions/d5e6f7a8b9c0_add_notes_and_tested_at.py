"""add notes and tested_at fields

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-03-18
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Assessment: name and notes
    op.add_column('assessments', sa.Column('name', sa.String(200), nullable=True))
    op.add_column('assessments', sa.Column('notes', sa.Text(), nullable=True))
    # ControlFinding: analyst notes and tested_at timestamp
    op.add_column('control_findings', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('control_findings', sa.Column('tested_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('control_findings', 'tested_at')
    op.drop_column('control_findings', 'notes')
    op.drop_column('assessments', 'notes')
    op.drop_column('assessments', 'name')
