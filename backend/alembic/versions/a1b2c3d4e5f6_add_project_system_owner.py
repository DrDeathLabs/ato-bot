"""Add an explicit FISMA system owner assignment to projects.

The existing projects.owner_id remains the technical creator/owner used by
legacy access checks. This field records the accountable system owner role.
"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("system_owner_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_system_owner_id_users",
        "projects",
        "users",
        ["system_owner_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_projects_system_owner_id", "projects", ["system_owner_id"])


def downgrade() -> None:
    op.drop_index("ix_projects_system_owner_id", table_name="projects")
    op.drop_constraint("fk_projects_system_owner_id_users", "projects", type_="foreignkey")
    op.drop_column("projects", "system_owner_id")
