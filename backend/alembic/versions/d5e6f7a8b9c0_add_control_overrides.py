"""add control overrides and finding carry-forward fields

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-03-18

"""
from alembic import op
import sqlalchemy as sa

revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # New columns on control_findings
    op.add_column('control_findings', sa.Column('carried_forward', sa.Boolean, nullable=False, server_default='false'))
    op.add_column('control_findings', sa.Column('applicability_changed', sa.Boolean, nullable=False, server_default='false'))
    op.add_column('control_findings', sa.Column('prev_status', sa.String(32), nullable=True))
    op.add_column('control_findings', sa.Column('override_applied', sa.String(32), nullable=True))

    # New control_overrides table
    op.create_table(
        'control_overrides',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('project_id', sa.Integer, sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('control_id', sa.String(32), nullable=False),
        sa.Column('applicability', sa.String(32), nullable=True),
        sa.Column('applicability_rationale', sa.Text, nullable=True),
        sa.Column('applicability_set_by', sa.String(64), nullable=True),
        sa.Column('applicability_set_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('satisfied', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('satisfied_rationale', sa.Text, nullable=True),
        sa.Column('satisfied_set_by', sa.String(64), nullable=True),
        sa.Column('satisfied_set_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('satisfied_finding_snapshot', sa.JSON, nullable=True),
        sa.Column('risk_accepted', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('risk_acceptance_rationale', sa.Text, nullable=True),
        sa.Column('risk_accepted_by', sa.String(64), nullable=True),
        sa.Column('risk_accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('risk_acceptance_expiry', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_control_overrides_project_id', 'control_overrides', ['project_id'])
    op.create_index('ix_control_overrides_control_id', 'control_overrides', ['control_id'])
    op.create_unique_constraint('uq_override_project_control', 'control_overrides', ['project_id', 'control_id'])


def downgrade() -> None:
    op.drop_table('control_overrides')
    op.drop_column('control_findings', 'override_applied')
    op.drop_column('control_findings', 'prev_status')
    op.drop_column('control_findings', 'applicability_changed')
    op.drop_column('control_findings', 'carried_forward')
