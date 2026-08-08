"""add assessment policy system

Revision ID: u3v4w5x6y7z8
Revises: t2u3v4w5x6y7
Create Date: 2026-04-07 11:15:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "u3v4w5x6y7z8"
down_revision = "t2u3v4w5x6y7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assessment_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("default_thresholds_json", sa.JSON(), nullable=True),
        sa.Column("mapping_rules_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "assessment_policy_buckets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("bucket_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("objective_weight", sa.Float(), nullable=False),
        sa.Column("critical_by_default", sa.Boolean(), nullable=False),
        sa.Column("minimum_evidence_strength", sa.Float(), nullable=False),
        sa.Column("negative_evidence_penalty", sa.Float(), nullable=False),
        sa.Column("contradiction_penalty", sa.Float(), nullable=False),
        sa.Column("future_state_cap", sa.Float(), nullable=False),
        sa.Column("inheritance_allowed", sa.Boolean(), nullable=False),
        sa.Column("compensating_allowed", sa.Boolean(), nullable=False),
        sa.Column("confidence_cap_if_only_weak_evidence", sa.Float(), nullable=True),
        sa.Column("confidence_cap_if_compensating_only", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["assessment_policies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "bucket_key", name="uq_assessment_policy_bucket_key"),
    )

    op.create_index(op.f("ix_assessment_policy_buckets_bucket_key"), "assessment_policy_buckets", ["bucket_key"], unique=False)
    op.create_index(op.f("ix_assessment_policy_buckets_policy_id"), "assessment_policy_buckets", ["policy_id"], unique=False)

    op.add_column("assessments", sa.Column("policy_id", sa.Integer(), nullable=True))
    op.add_column("assessments", sa.Column("policy_version", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_assessments_policy_id"), "assessments", ["policy_id"], unique=False)
    op.create_foreign_key(
        "fk_assessments_policy_id_assessment_policies",
        "assessments",
        "assessment_policies",
        ["policy_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_assessments_policy_id_assessment_policies", "assessments", type_="foreignkey")
    op.drop_index(op.f("ix_assessments_policy_id"), table_name="assessments")
    op.drop_column("assessments", "policy_version")
    op.drop_column("assessments", "policy_id")

    op.drop_index(op.f("ix_assessment_policy_buckets_policy_id"), table_name="assessment_policy_buckets")
    op.drop_index(op.f("ix_assessment_policy_buckets_bucket_key"), table_name="assessment_policy_buckets")
    op.drop_table("assessment_policy_buckets")
    op.drop_table("assessment_policies")
