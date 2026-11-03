"""add appointment notes

Revision ID: d8e2b6a4c917
Revises: c4a7e1b93d58
Create Date: 2026-10-24

`appointment_notes` (`silverloop.family_calendar`) holds a family member's note on one day of an
appointment. Group-only text, deletable by its author, so unlike `family_activity` it is not
append-only. It points at its appointment by foreign key and is deleted with it. The table is new,
so the downgrade drops it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8e2b6a4c917"
down_revision: str | None = "c4a7e1b93d58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "appointment_notes",
        sa.Column("note_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("appointment_id", sa.String(length=64), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.appointment_id"]),
        sa.ForeignKeyConstraint(["member_id"], ["group_members.member_id"]),
        sa.PrimaryKeyConstraint("note_id"),
    )
    op.create_index(op.f("ix_appointment_notes_group_id"), "appointment_notes", ["group_id"])
    op.create_index(
        op.f("ix_appointment_notes_appointment_id"), "appointment_notes", ["appointment_id"]
    )
    op.create_index(op.f("ix_appointment_notes_member_id"), "appointment_notes", ["member_id"])
    op.create_index(
        "ix_appointment_notes_day_created",
        "appointment_notes",
        ["appointment_id", "on_date", "created_at"],
    )
    # RLS and the deny posture: infra/supabase/migrations/202610240024_appointment_notes.sql.


def downgrade() -> None:
    op.drop_table("appointment_notes")
