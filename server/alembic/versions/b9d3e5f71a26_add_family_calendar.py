"""add the family calendar: appointments, availability entries and helper assignments

Revision ID: b9d3e5f71a26
Revises: a4f6c2e81d37
Create Date: 2026-10-14

The family calendar moves from the browser to the API (`silverloop.family_calendar`). A repeating
appointment is one row; answers and helpers point at one day of it. All three tables are new, so
the downgrade drops them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9d3e5f71a26"
down_revision: str | None = "a4f6c2e81d37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("appointment_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("end_time", sa.String(length=5), nullable=False),
        sa.Column("location", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("repeat", sa.String(length=8), nullable=False),
        sa.Column("repeat_until", sa.Date(), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.PrimaryKeyConstraint("appointment_id"),
    )
    op.create_index(op.f("ix_appointments_group_id"), "appointments", ["group_id"])
    op.create_table(
        "availability_entries",
        sa.Column("entry_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("end_time", sa.String(length=5), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("appointment_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.ForeignKeyConstraint(["member_id"], ["group_members.member_id"]),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.appointment_id"]),
        sa.PrimaryKeyConstraint("entry_id"),
    )
    for column in ("group_id", "member_id", "appointment_id"):
        op.create_index(op.f(f"ix_availability_entries_{column}"), "availability_entries", [column])
    op.create_table(
        "helper_assignments",
        sa.Column("assignment_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("appointment_id", sa.String(length=64), nullable=False),
        sa.Column("on_date", sa.Date(), nullable=False),
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.appointment_id"]),
        sa.ForeignKeyConstraint(["member_id"], ["group_members.member_id"]),
        sa.PrimaryKeyConstraint("assignment_id"),
        sa.UniqueConstraint(
            "appointment_id", "on_date", "member_id", name="uq_helper_assignments_day_member"
        ),
    )
    for column in ("group_id", "appointment_id", "member_id"):
        op.create_index(op.f(f"ix_helper_assignments_{column}"), "helper_assignments", [column])
    # RLS and the deny posture: infra/supabase/migrations/202610140022_family_calendar.sql.


def downgrade() -> None:
    op.drop_table("helper_assignments")
    op.drop_table("availability_entries")
    op.drop_table("appointments")
