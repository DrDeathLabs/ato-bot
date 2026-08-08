"""add enterprise procedure libraries

Revision ID: n5i6j7k8l9m0
Revises: m4h5i6j7k8l9
Create Date: 2026-03-21
"""
from alembic import op
import sqlalchemy as sa

revision = 'n5i6j7k8l9m0'
down_revision = 'm4h5i6j7k8l9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'procedure_libraries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(64), nullable=False, server_default='general'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_procedure_libraries_id', 'procedure_libraries', ['id'])

    op.add_column(
        'documents',
        sa.Column('procedure_library_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_documents_procedure_library_id',
        'documents', 'procedure_libraries',
        ['procedure_library_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_index('ix_documents_procedure_library_id', 'documents', ['procedure_library_id'])


def downgrade() -> None:
    op.drop_index('ix_documents_procedure_library_id', 'documents')
    op.drop_constraint('fk_documents_procedure_library_id', 'documents', type_='foreignkey')
    op.drop_column('documents', 'procedure_library_id')
    op.drop_index('ix_procedure_libraries_id', 'procedure_libraries')
    op.drop_table('procedure_libraries')
