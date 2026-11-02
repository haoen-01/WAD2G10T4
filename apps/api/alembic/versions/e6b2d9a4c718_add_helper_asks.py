"""add helper asks and notifications

Revision ID: e6b2d9a4c718
Revises: a7d4c2e9f1b3
Create Date: 2026-11-02

`helper_asks` and `notifications` (`silverloop.family_asks`, issue #16): one family member asking
another to take one day of an appointment, and the in-app notifications about it. At most one ask
per appointment day is open, enforced by a partial unique index on SQLite and PostgreSQL alike. Like
the feed, `helper_asks.appointment_id` has no foreign key and the title is a snapshot, so an ask
outlives its appointment. Both tables are new, so the downgrade drops them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6b2d9a4c718"
down_revision: str | None = "a7d4c2e9f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "helper_asks",
        sa.Column("ask_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("appointment_id", sa.String(length=64), nullable=False),
        sa.Column("appointment_title", sa.String(length=120), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("asker_member_id", sa.String(length=64), nullable=False),
        sa.Column("asked_member_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by_member_id", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "asker_member_id <> asked_member_id", name="ck_helper_asks_not_self"
        ),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.ForeignKeyConstraint(["asker_member_id"], ["group_members.member_id"]),
        sa.ForeignKeyConstraint(["asked_member_id"], ["group_members.member_id"]),
        sa.ForeignKeyConstraint(["ended_by_member_id"], ["group_members.member_id"]),
        sa.PrimaryKeyConstraint("ask_id"),
    )
    op.create_index(
        "uq_helper_asks_open_day",
        "helper_asks",
        ["appointment_id", "on_date"],
        unique=True,
        sqlite_where=sa.text("state = 'open'"),
        postgresql_where=sa.text("state = 'open'"),
    )
    op.create_index("ix_helper_asks_group_state", "helper_asks", ["group_id", "state"])
    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("recipient_member_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("ask_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.ForeignKeyConstraint(["recipient_member_id"], ["group_members.member_id"]),
        sa.ForeignKeyConstraint(["ask_id"], ["helper_asks.ask_id"]),
        sa.PrimaryKeyConstraint("notification_id"),
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_member_id", "created_at", "notification_id"],
    )
    op.create_index(op.f("ix_notifications_ask_id"), "notifications", ["ask_id"])
    # RLS and the deny posture: infra/supabase/migrations/202611020028_helper_asks.sql.


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("helper_asks")
