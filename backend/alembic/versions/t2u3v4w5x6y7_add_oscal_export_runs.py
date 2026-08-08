"""add oscal export runs

Revision ID: t2u3v4w5x6y7
Revises: s1t2u3v4w5x6
Create Date: 2026-04-03 08:20:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "t2u3v4w5x6y7"
down_revision = "s1t2u3v4w5x6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oscal_export_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("export_kind", sa.String(length=64), nullable=False),
        sa.Column("oscal_version", sa.String(length=32), nullable=False),
        sa.Column("schema_source", sa.String(length=1024), nullable=True),
        sa.Column("output_path", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_oscal_export_runs_assessment_id"), "oscal_export_runs", ["assessment_id"], unique=False)
    op.create_index(op.f("ix_oscal_export_runs_export_kind"), "oscal_export_runs", ["export_kind"], unique=False)
    op.create_index(op.f("ix_oscal_export_runs_project_id"), "oscal_export_runs", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_oscal_export_runs_project_id"), table_name="oscal_export_runs")
    op.drop_index(op.f("ix_oscal_export_runs_export_kind"), table_name="oscal_export_runs")
    op.drop_index(op.f("ix_oscal_export_runs_assessment_id"), table_name="oscal_export_runs")
    op.drop_table("oscal_export_runs")
