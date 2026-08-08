"""make procedure_libraries.created_by nullable for system-created libraries

Revision ID: o6j7k8l9m0n1
Revises: n5i6j7k8l9m0
Create Date: 2026-03-21
"""
from alembic import op

revision = 'o6j7k8l9m0n1'
down_revision = 'n5i6j7k8l9m0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Allow system-created procedure libraries (LLM auto-categorization)
    op.alter_column('procedure_libraries', 'created_by', nullable=True)

    # Add categorizing to allowed parse statuses (informational — stored as VARCHAR)
    # No DDL needed; just documenting the new value: "categorizing"


def downgrade() -> None:
    op.alter_column('procedure_libraries', 'created_by', nullable=False)
