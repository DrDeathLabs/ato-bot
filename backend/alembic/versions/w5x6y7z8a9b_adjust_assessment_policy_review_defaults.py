"""adjust assessment policy review defaults

Revision ID: w5x6y7z8a9b
Revises: v4w5x6y7z8a9
Create Date: 2026-04-08 16:45:00.000000
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "w5x6y7z8a9b"
down_revision = "v4w5x6y7z8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE assessment_policies
        SET default_thresholds_json =
            jsonb_set(
                jsonb_set(
                    COALESCE(default_thresholds_json::jsonb, '{}'::jsonb),
                    '{manual_review_weak_evidence_threshold}',
                    '0.35'::jsonb,
                    true
                ),
                '{manual_review_inheritance_without_authority}',
                'false'::jsonb,
                true
            )::json
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE assessment_policies
        SET default_thresholds_json =
            jsonb_set(
                jsonb_set(
                    COALESCE(default_thresholds_json::jsonb, '{}'::jsonb),
                    '{manual_review_weak_evidence_threshold}',
                    '0.45'::jsonb,
                    true
                ),
                '{manual_review_inheritance_without_authority}',
                'true'::jsonb,
                true
            )::json
        """
    )
