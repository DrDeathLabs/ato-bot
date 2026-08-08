"""Add assessment planning, activities, approvals, tailoring, and evidence governance.

Revision ID: c2d3e4f5a6b7
Revises: 7e9c6e129313
"""
from alembic import op
import sqlalchemy as sa

revision = "c2d3e4f5a6b7"
down_revision = "7e9c6e129313"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reuse of prior findings must be an explicit operator choice.
    op.execute("ALTER TABLE assessments ALTER COLUMN carry_forward_compliant SET DEFAULT FALSE")
    op.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS finalization_status VARCHAR(32) NOT NULL DEFAULT 'not_ready'")
    op.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS finalized_by INTEGER REFERENCES users(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ")

    op.execute("ALTER TABLE ingestion_runs ADD COLUMN IF NOT EXISTS quality_status VARCHAR(32) NOT NULL DEFAULT 'passed'")
    op.execute("ALTER TABLE ingestion_runs ADD COLUMN IF NOT EXISTS fallback_stages JSON NOT NULL DEFAULT '[]'::json")
    op.execute("ALTER TABLE ingestion_runs ADD COLUMN IF NOT EXISTS readiness_eligible BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("""
        UPDATE ingestion_runs AS ir
        SET quality_status = 'degraded',
            fallback_stages = '["legacy_fallback_detected"]'::json,
            readiness_eligible = FALSE
        WHERE EXISTS (
            SELECT 1 FROM screening_results AS sr
            WHERE sr.run_id = ir.id
              AND sr.rationale ILIKE '%fallback%'
        ) OR EXISTS (
            SELECT 1 FROM evidence_classifications AS ec
            WHERE ec.run_id = ir.id
              AND ec.explanation ILIKE '%fallback%'
        )
    """)

    op.create_table(
        "assessment_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("control_selection_json", sa.JSON(), nullable=False),
        sa.Column("methods_json", sa.JSON(), nullable=False),
        sa.Column("objects_json", sa.JSON(), nullable=False),
        sa.Column("depth", sa.String(32), nullable=False),
        sa.Column("coverage", sa.String(32), nullable=False),
        sa.Column("assessor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approval_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assessment_plans_assessment_id", "assessment_plans", ["assessment_id"], unique=True)

    op.create_table(
        "assessment_activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("assessment_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("control_id", sa.String(32), nullable=False),
        sa.Column("objective_id", sa.String(128)),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("assessment_objects", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        sa.Column("result", sa.Text()),
        sa.Column("evidence_refs", sa.JSON()),
        sa.Column("performed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("performed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in ("assessment_id", "plan_id", "control_id", "objective_id", "method"):
        op.create_index(f"ix_assessment_activities_{column}", "assessment_activities", [column])

    op.create_table(
        "assessment_tailoring_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("control_id", sa.String(32), nullable=False),
        sa.Column("decision_type", sa.String(32), nullable=False),
        sa.Column("parameter_id", sa.String(128)),
        sa.Column("value_json", sa.JSON()),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON()),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for column in ("assessment_id", "control_id", "decision_type"):
        op.create_index(f"ix_assessment_tailoring_decisions_{column}", "assessment_tailoring_decisions", [column])

    op.create_table(
        "assessment_approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approval_type", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assessment_approvals_assessment_id", "assessment_approvals", ["assessment_id"])
    op.create_index("ix_assessment_approvals_approval_type", "assessment_approvals", ["approval_type"])

    op.create_table(
        "assessment_retry_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("control_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_assessment_retry_jobs_assessment_id", "assessment_retry_jobs", ["assessment_id"])
    op.create_index("ix_assessment_retry_jobs_status", "assessment_retry_jobs", ["status"])

    op.execute("ALTER TABLE assessment_challenges ADD COLUMN IF NOT EXISTS resolution_status VARCHAR(32) NOT NULL DEFAULT 'not_required'")
    op.execute("ALTER TABLE assessment_challenges ADD COLUMN IF NOT EXISTS resolution_note TEXT")
    op.execute("ALTER TABLE assessment_challenges ADD COLUMN IF NOT EXISTS resolved_by INTEGER REFERENCES users(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE assessment_challenges ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ")
    op.execute("UPDATE assessment_challenges SET resolution_status = 'unresolved' WHERE concur = FALSE")

    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS artifact_status VARCHAR(32)")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS evidence_eligible BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS artifact_approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS artifact_approved_at TIMESTAMPTZ")
    op.execute("UPDATE documents SET artifact_status = 'draft', evidence_eligible = FALSE WHERE autogenerated = TRUE")

    op.execute("ALTER TABLE artifact_approvals ADD COLUMN IF NOT EXISTS evidence_eligibility VARCHAR(32) NOT NULL DEFAULT 'draft'")
    op.execute("ALTER TABLE artifact_approvals ADD COLUMN IF NOT EXISTS eligibility_rationale TEXT")
    op.execute("ALTER TABLE artifact_approvals ADD COLUMN IF NOT EXISTS eligibility_decided_by INTEGER REFERENCES users(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE artifact_approvals ADD COLUMN IF NOT EXISTS eligibility_decided_at TIMESTAMPTZ")

    op.execute("ALTER TABLE poam_entries ADD COLUMN IF NOT EXISTS owner_role VARCHAR(128)")
    op.execute("ALTER TABLE poam_entries ADD COLUMN IF NOT EXISTS scheduled_completion_date TIMESTAMPTZ")
    op.execute("ALTER TABLE poam_entries ADD COLUMN IF NOT EXISTS likelihood VARCHAR(16)")
    op.execute("ALTER TABLE poam_entries ADD COLUMN IF NOT EXISTS impact VARCHAR(16)")
    op.execute("ALTER TABLE poam_entries ADD COLUMN IF NOT EXISTS residual_risk VARCHAR(16)")
    op.execute("ALTER TABLE poam_entries ADD COLUMN IF NOT EXISTS response_strategy VARCHAR(32)")
    op.execute("ALTER TABLE poam_entries ADD COLUMN IF NOT EXISTS acceptance_rationale TEXT")
    op.execute("ALTER TABLE poam_entries ADD COLUMN IF NOT EXISTS accepted_by INTEGER REFERENCES users(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE poam_entries ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ")
    op.execute("UPDATE poam_entries SET status = 'accepted_risk' WHERE status = 'risk_accepted'")


def downgrade() -> None:
    op.execute("UPDATE poam_entries SET status = 'risk_accepted' WHERE status = 'accepted_risk'")
    for column in (
        "accepted_at", "accepted_by", "acceptance_rationale", "response_strategy",
        "residual_risk", "impact", "likelihood", "scheduled_completion_date", "owner_role",
    ):
        op.execute(f"ALTER TABLE poam_entries DROP COLUMN IF EXISTS {column}")

    for column in (
        "eligibility_decided_at", "eligibility_decided_by", "eligibility_rationale", "evidence_eligibility",
    ):
        op.execute(f"ALTER TABLE artifact_approvals DROP COLUMN IF EXISTS {column}")
    for column in ("artifact_approved_at", "artifact_approved_by", "evidence_eligible", "artifact_status"):
        op.execute(f"ALTER TABLE documents DROP COLUMN IF EXISTS {column}")
    for column in ("resolved_at", "resolved_by", "resolution_note", "resolution_status"):
        op.execute(f"ALTER TABLE assessment_challenges DROP COLUMN IF EXISTS {column}")

    op.drop_table("assessment_retry_jobs")
    op.drop_table("assessment_approvals")
    op.drop_table("assessment_tailoring_decisions")
    op.drop_table("assessment_activities")
    op.drop_table("assessment_plans")

    for column in ("readiness_eligible", "fallback_stages", "quality_status"):
        op.execute(f"ALTER TABLE ingestion_runs DROP COLUMN IF EXISTS {column}")
    for column in ("finalized_at", "finalized_by", "finalization_status"):
        op.execute(f"ALTER TABLE assessments DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE assessments ALTER COLUMN carry_forward_compliant SET DEFAULT TRUE")
