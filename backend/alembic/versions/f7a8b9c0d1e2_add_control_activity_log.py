"""add control activity log

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-03-18

"""
from alembic import op
import sqlalchemy as sa

revision = 'f7a8b9c0d1e2'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'control_activity_logs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('project_id', sa.Integer, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assessment_id', sa.Integer, sa.ForeignKey('assessments.id', ondelete='SET NULL'), nullable=True),
        sa.Column('control_id', sa.String(32), nullable=False),
        sa.Column('control_family', sa.String(8), nullable=False),
        sa.Column('control_title', sa.String(512), nullable=False),
        sa.Column('action_type', sa.String(64), nullable=False),
        sa.Column('action_summary', sa.String(512), nullable=False),
        sa.Column('details', sa.JSON, nullable=True),
        sa.Column('performed_by', sa.String(64), nullable=False),
        sa.Column('performed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_cal_project_id', 'control_activity_logs', ['project_id'])
    op.create_index('ix_cal_control_id', 'control_activity_logs', ['control_id'])
    op.create_index('ix_cal_action_type', 'control_activity_logs', ['action_type'])
    op.create_index('ix_cal_performed_at', 'control_activity_logs', ['performed_at'])


def downgrade() -> None:
    op.drop_table('control_activity_logs')
