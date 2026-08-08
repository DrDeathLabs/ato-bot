"""add control closure workflow tables

Revision ID: x6y7z8a9b0c
Revises: w5x6y7z8a9b
Create Date: 2026-04-12 13:20:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "x6y7z8a9b0c"
down_revision = "w5x6y7z8a9b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "control_closure_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("control_id", sa.String(length=32), nullable=False),
        sa.Column("control_family", sa.String(length=8), nullable=False),
        sa.Column("control_title", sa.String(length=255), nullable=False),
        sa.Column("current_status", sa.String(length=32), nullable=False),
        sa.Column("session_status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("implementation_summary", sa.Text(), nullable=True),
        sa.Column("recommended_artifacts", sa.JSON(), nullable=True),
        sa.Column("generated_artifact_ids", sa.JSON(), nullable=True),
        sa.Column("closure_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_control_closure_sessions_project_id",
        "control_closure_sessions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_control_closure_sessions_assessment_id",
        "control_closure_sessions",
        ["assessment_id"],
        unique=False,
    )
    op.create_index(
        "ix_control_closure_sessions_control_id",
        "control_closure_sessions",
        ["control_id"],
        unique=False,
    )

    op.create_table(
        "artifact_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("control_closure_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("control_id", sa.String(length=32), nullable=False),
        sa.Column("artifact_title", sa.String(length=255), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False, server_default="policy_procedure"),
        sa.Column("approval_chain", sa.JSON(), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overall_status", sa.String(length=32), nullable=False, server_default="pending_review"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_artifact_approvals_session_id",
        "artifact_approvals",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_artifact_approvals_session_id", table_name="artifact_approvals")
    op.drop_table("artifact_approvals")

    op.drop_index("ix_control_closure_sessions_control_id", table_name="control_closure_sessions")
    op.drop_index("ix_control_closure_sessions_assessment_id", table_name="control_closure_sessions")
    op.drop_index("ix_control_closure_sessions_project_id", table_name="control_closure_sessions")
    op.drop_table("control_closure_sessions")
