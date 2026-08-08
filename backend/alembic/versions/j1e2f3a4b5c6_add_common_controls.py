"""add common control providers

Revision ID: j1e2f3a4b5c6
Revises: i0d1e2f3a4b5
Create Date: 2026-03-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'j1e2f3a4b5c6'
down_revision = 'i0d1e2f3a4b5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Common control providers
    op.create_table(
        'common_control_providers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('org_level', sa.String(64), nullable=False, server_default='enterprise'),
        sa.Column('control_families', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('created_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
    )

    # Project ↔ Provider association
    op.create_table(
        'project_common_providers',
        sa.Column('project_id', sa.Integer(),
                  sa.ForeignKey('projects.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('provider_id', sa.Integer(),
                  sa.ForeignKey('common_control_providers.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('linked_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('linked_by', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
    )

    # Make documents.project_id nullable and add provider_id
    op.alter_column('documents', 'project_id', nullable=True)
    op.add_column('documents', sa.Column(
        'provider_id', sa.Integer(),
        sa.ForeignKey('common_control_providers.id', ondelete='CASCADE'),
        nullable=True,
    ))
    op.create_index('ix_documents_provider_id', 'documents', ['provider_id'])


def downgrade() -> None:
    op.drop_index('ix_documents_provider_id', table_name='documents')
    op.drop_column('documents', 'provider_id')
    op.alter_column('documents', 'project_id', nullable=False)
    op.drop_table('project_common_providers')
    op.drop_table('common_control_providers')
