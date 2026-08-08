"""add verification checks and results

Revision ID: s1t2u3v4w5x6
Revises: r9m0n1o2p3q4
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "s1t2u3v4w5x6"
down_revision = "r9m0n1o2p3q4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("security_assets"):
        op.create_table(
            "security_assets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("asset_type", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("external_id", sa.String(length=255), nullable=True),
            sa.Column("criticality", sa.String(length=32), nullable=False, server_default="medium"),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
            sa.UniqueConstraint("project_id", "asset_type", "name", name="uq_security_asset_name"),
        )
        op.create_index("ix_security_assets_project_id", "security_assets", ["project_id"])
        op.create_index("ix_security_assets_asset_type", "security_assets", ["asset_type"])
        op.create_index("ix_security_assets_external_id", "security_assets", ["external_id"])
        op.create_index("ix_security_assets_last_seen_at", "security_assets", ["last_seen_at"])

    op.create_table(
        "verification_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("check_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("control_id", sa.String(length=32), nullable=True),
        sa.Column("source_scope", sa.String(length=32), nullable=False, server_default="live"),
        sa.Column("verifier_type", sa.String(length=32), nullable=False, server_default="deterministic"),
        sa.Column("freshness_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.func.now()),
        sa.UniqueConstraint("check_key", name="uq_verification_check_key"),
    )
    op.create_index("ix_verification_checks_check_key", "verification_checks", ["check_key"])
    op.create_index("ix_verification_checks_domain", "verification_checks", ["domain"])
    op.create_index("ix_verification_checks_control_id", "verification_checks", ["control_id"])
    op.create_index("ix_verification_checks_source_scope", "verification_checks", ["source_scope"])

    op.create_table(
        "verification_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("check_id", sa.Integer(), sa.ForeignKey("verification_checks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("security_assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default="high"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_verification_results_check_id", "verification_results", ["check_id"])
    op.create_index("ix_verification_results_project_id", "verification_results", ["project_id"])
    op.create_index("ix_verification_results_asset_id", "verification_results", ["asset_id"])
    op.create_index("ix_verification_results_result", "verification_results", ["result"])
    op.create_index("ix_verification_results_verified_at", "verification_results", ["verified_at"])
    op.create_index("ix_verification_results_expires_at", "verification_results", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_verification_results_expires_at", table_name="verification_results")
    op.drop_index("ix_verification_results_verified_at", table_name="verification_results")
    op.drop_index("ix_verification_results_result", table_name="verification_results")
    op.drop_index("ix_verification_results_asset_id", table_name="verification_results")
    op.drop_index("ix_verification_results_project_id", table_name="verification_results")
    op.drop_index("ix_verification_results_check_id", table_name="verification_results")
    op.drop_table("verification_results")

    op.drop_index("ix_verification_checks_source_scope", table_name="verification_checks")
    op.drop_index("ix_verification_checks_control_id", table_name="verification_checks")
    op.drop_index("ix_verification_checks_domain", table_name="verification_checks")
    op.drop_index("ix_verification_checks_check_key", table_name="verification_checks")
    op.drop_table("verification_checks")

    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table("security_assets"):
        op.drop_index("ix_security_assets_last_seen_at", table_name="security_assets")
        op.drop_index("ix_security_assets_external_id", table_name="security_assets")
        op.drop_index("ix_security_assets_asset_type", table_name="security_assets")
        op.drop_index("ix_security_assets_project_id", table_name="security_assets")
        op.drop_table("security_assets")
