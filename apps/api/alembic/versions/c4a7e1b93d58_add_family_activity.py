"""add the family activity feed

Revision ID: c4a7e1b93d58
Revises: b9d3e5f71a26
Create Date: 2026-10-24

`family_activity` (`silverloop.family_activity`) is append-only: one row per thing a family member
did in the group (a check-in, a helper joining, an appointment changing, ...). `appointment_id`
has no foreign key so an entry outlives the appointment it mentions; the title is a snapshot. The
table is new, so the downgrade drops it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4a7e1b93d58"
down_revision: str | None = "b9d3e5f71a26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "family_activity",
        sa.Column("activity_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("actor_member_id", sa.String(length=64), nullable=False),
        sa.Column("subject_member_id", sa.String(length=64), nullable=True),
        sa.Column("appointment_id", sa.String(length=64), nullable=True),
        sa.Column("appointment_title", sa.String(length=120), nullable=True),
        sa.Column("appointment_kind", sa.String(length=16), nullable=True),
        sa.Column("on_date", sa.Date(), nullable=True),
        sa.Column("check_in_kind", sa.String(length=16), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(kind = 'check_in') = (check_in_kind IS NOT NULL) "
            "AND (note IS NULL OR kind = 'check_in')",
            name="ck_family_activity_check_in_fields",
        ),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.ForeignKeyConstraint(["actor_member_id"], ["group_members.member_id"]),
        sa.ForeignKeyConstraint(["subject_member_id"], ["group_members.member_id"]),
        sa.PrimaryKeyConstraint("activity_id"),
    )
    op.create_index(
        "ix_family_activity_group_created",
        "family_activity",
        ["group_id", "created_at", "activity_id"],
    )
    op.create_index(
        op.f("ix_family_activity_actor_member_id"), "family_activity", ["actor_member_id"]
    )
    # RLS and the deny posture: infra/supabase/migrations/202610240023_family_activity.sql.


def downgrade() -> None:
    op.drop_table("family_activity")
