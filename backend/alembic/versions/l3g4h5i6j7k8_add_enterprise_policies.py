"""add enterprise policy libraries

Revision ID: l3g4h5i6j7k8
Revises: k2f3a4b5c6d7
Create Date: 2026-03-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'm4h5i6j7k8l9'
down_revision = 'l3g4h5i6j7k8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'policy_libraries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(64), nullable=False, server_default='general'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_policy_libraries_id', 'policy_libraries', ['id'])

    op.add_column(
        'documents',
        sa.Column('policy_library_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_documents_policy_library_id',
        'documents', 'policy_libraries',
        ['policy_library_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_index('ix_documents_policy_library_id', 'documents', ['policy_library_id'])


def downgrade() -> None:
    op.drop_index('ix_documents_policy_library_id', 'documents')
    op.drop_constraint('fk_documents_policy_library_id', 'documents', type_='foreignkey')
    op.drop_column('documents', 'policy_library_id')
    op.drop_index('ix_policy_libraries_id', 'policy_libraries')
    op.drop_table('policy_libraries')
