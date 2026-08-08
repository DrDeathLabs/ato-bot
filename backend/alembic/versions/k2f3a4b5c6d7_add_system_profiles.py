"""add system_profiles table

Revision ID: k2f3a4b5c6d7
Revises: j1e2f3a4b5c6
Create Date: 2026-03-20

"""
from alembic import op
import sqlalchemy as sa

revision = 'k2f3a4b5c6d7'
down_revision = 'j1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'system_profiles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('deployment_model', sa.String(32), nullable=False),
        sa.Column('infrastructure_ownership', sa.String(32), nullable=False, server_default='org_owned'),
        sa.Column('has_wireless_networking', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('has_external_connections', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('has_physical_facilities', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('has_mobile_devices', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('has_removable_media', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('user_population', sa.String(32), nullable=False, server_default='mixed'),
        sa.Column('publicly_accessible', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_by', sa.String(64), nullable=False, server_default='system'),
    )


def downgrade() -> None:
    op.drop_table('system_profiles')
