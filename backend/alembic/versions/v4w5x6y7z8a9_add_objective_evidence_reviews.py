"""add objective evidence reviews

Revision ID: v4w5x6y7z8a9
Revises: u3v4w5x6y7z8
Create Date: 2026-04-08 13:20:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "v4w5x6y7z8a9"
down_revision = "u3v4w5x6y7z8"
branch_labels = None
depends_on = None


def _ensure_evidence_unit_prerequisites() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("ingestion_runs"):
        op.create_table(
            "ingestion_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("config_snapshot", sa.JSON(), nullable=True),
            sa.Column("corpus_version", sa.String(length=128), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("current_stage", sa.String(length=32), nullable=True),
            sa.Column("stage_parse", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("stage_screen", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("stage_expand", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("stage_classify", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("stage_embed", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("lines_parsed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lines_screened", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("evidence_units_created", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("units_classified", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("units_embedded", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("error_stage", sa.String(length=32), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("triggered_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("ix_ingestion_runs_document_id", "ingestion_runs", ["document_id"])
        op.create_index("ix_ingestion_runs_status", "ingestion_runs", ["status"])

    if not inspector.has_table("parsed_lines"):
        op.create_table(
            "parsed_lines",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("line_number", sa.Integer(), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("section_path", sa.Text(), nullable=True),
            sa.Column("block_id", sa.String(length=128), nullable=True),
            sa.Column("block_type", sa.String(length=64), nullable=True),
            sa.Column("table_id", sa.String(length=128), nullable=True),
            sa.Column("row_index", sa.Integer(), nullable=True),
            sa.Column("col_index", sa.Integer(), nullable=True),
            sa.Column("cell_label", sa.String(length=255), nullable=True),
            sa.Column("content_type", sa.String(length=32), nullable=False, server_default="text"),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        )
        op.create_index("ix_parsed_lines_run_id", "parsed_lines", ["run_id"])
        op.create_index("ix_parsed_lines_document_id", "parsed_lines", ["document_id"])

    if not inspector.has_table("evidence_units"):
        op.create_table(
            "evidence_units",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.Integer(), sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("trigger_line_id", sa.Integer(), sa.ForeignKey("parsed_lines.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_line_ids", sa.JSON(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("page_numbers", sa.JSON(), nullable=True),
            sa.Column("section_path", sa.Text(), nullable=True),
            sa.Column("table_coordinates", sa.JSON(), nullable=True),
            sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        )
        op.create_index("ix_evidence_units_run_id", "evidence_units", ["run_id"])
        op.create_index("ix_evidence_units_document_id", "evidence_units", ["document_id"])
        op.create_index("ix_evidence_units_trigger_line_id", "evidence_units", ["trigger_line_id"])


def upgrade() -> None:
    _ensure_evidence_unit_prerequisites()

    op.create_table(
        "objective_evidence_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.Integer(), nullable=False),
        sa.Column("control_id", sa.String(length=32), nullable=False),
        sa.Column("objective_id", sa.String(length=128), nullable=False),
        sa.Column("objective_text", sa.Text(), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("artifact_type", sa.String(length=64), nullable=True),
        sa.Column("evidence_strength", sa.String(length=32), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("document_intent", sa.String(length=64), nullable=True),
        sa.Column("review_role", sa.String(length=32), nullable=False),
        sa.Column("used_in_prompt", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("objective_relevance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("keyword_hits", sa.JSON(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assessment_id"], ["assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unit_id"], ["evidence_units.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assessment_id", "control_id", "objective_id", "unit_id", name="uq_objective_evidence_review"),
    )
    op.create_index(op.f("ix_objective_evidence_reviews_assessment_id"), "objective_evidence_reviews", ["assessment_id"], unique=False)
    op.create_index(op.f("ix_objective_evidence_reviews_control_id"), "objective_evidence_reviews", ["control_id"], unique=False)
    op.create_index(op.f("ix_objective_evidence_reviews_objective_id"), "objective_evidence_reviews", ["objective_id"], unique=False)
    op.create_index(op.f("ix_objective_evidence_reviews_unit_id"), "objective_evidence_reviews", ["unit_id"], unique=False)
    op.create_index(op.f("ix_objective_evidence_reviews_document_id"), "objective_evidence_reviews", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_objective_evidence_reviews_document_id"), table_name="objective_evidence_reviews")
    op.drop_index(op.f("ix_objective_evidence_reviews_unit_id"), table_name="objective_evidence_reviews")
    op.drop_index(op.f("ix_objective_evidence_reviews_objective_id"), table_name="objective_evidence_reviews")
    op.drop_index(op.f("ix_objective_evidence_reviews_control_id"), table_name="objective_evidence_reviews")
    op.drop_index(op.f("ix_objective_evidence_reviews_assessment_id"), table_name="objective_evidence_reviews")
    op.drop_table("objective_evidence_reviews")
