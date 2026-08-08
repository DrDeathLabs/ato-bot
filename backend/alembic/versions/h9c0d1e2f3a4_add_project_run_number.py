"""add project_run_number to assessments

Revision ID: h9c0d1e2f3a4
Revises: g8b9c0d1e2f3
Create Date: 2026-03-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'h9c0d1e2f3a4'
down_revision = 'g8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column with a default so existing rows get 0; we'll backfill below
    op.add_column('assessments', sa.Column('project_run_number', sa.Integer(), nullable=False, server_default='0'))

    # Backfill existing rows: assign sequential run numbers per project ordered by id
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY id) AS rn
            FROM assessments
        )
        UPDATE assessments
        SET project_run_number = ranked.rn
        FROM ranked
        WHERE assessments.id = ranked.id
    """)

    # Remove the server default — new rows will have it set by application code
    op.alter_column('assessments', 'project_run_number', server_default=None)


def downgrade() -> None:
    op.drop_column('assessments', 'project_run_number')
