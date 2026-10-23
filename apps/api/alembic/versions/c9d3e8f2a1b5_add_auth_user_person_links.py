"""add auth_user_person_links

Revision ID: c9d3e8f2a1b5
Revises: b6f42a71e903
Create Date: 2026-08-22 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9d3e8f2a1b5"
down_revision: str | None = "b6f42a71e903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_user_person_links",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("sub", sa.String(length=128), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sub"),
    )
    op.create_index(
        op.f("ix_auth_user_person_links_person_id"),
        "auth_user_person_links",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_user_person_links_sub"),
        "auth_user_person_links",
        ["sub"],
        unique=True,
    )
    # RLS enablement and the anon/authenticated deny posture for this table are
    # Supabase-platform-specific and live exclusively in the hand-applied SQL
    # mirror at infra/supabase/migrations/202609020005_auth_user_person_links.sql,
    # matching every other table in this repo (see infra/supabase/migrations/).


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_user_person_links_sub"), table_name="auth_user_person_links")
    op.drop_index(op.f("ix_auth_user_person_links_person_id"), table_name="auth_user_person_links")
    op.drop_table("auth_user_person_links")
