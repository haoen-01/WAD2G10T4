"""add family tasks

Revision ID: a7d4c2e9f1b3
Revises: f3a9c1e7b254
Create Date: 2026-10-29

`tasks` and `task_ticks` (`silverloop.family_tasks`) move the senior's shared reminder list out of
the browser and into the family group. A repeating task is one row; a tick is one day of it ticked
done, unique per task and day. Tasks the browser kept are not migrated. Both tables are new, so the
downgrade drops them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7d4c2e9f1b3"
down_revision: str | None = "f3a9c1e7b254"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("time", sa.String(length=5), nullable=False),
        sa.Column("repeat", sa.String(length=8), nullable=False),
        sa.Column("repeat_until", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index(op.f("ix_tasks_group_id"), "tasks", ["group_id"])
    op.create_table(
        "task_ticks",
        sa.Column("tick_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("done_by", sa.String(length=128), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.task_id"]),
        sa.PrimaryKeyConstraint("tick_id"),
        sa.UniqueConstraint("task_id", "day", name="uq_task_ticks_task_day"),
    )
    op.create_index(op.f("ix_task_ticks_group_id"), "task_ticks", ["group_id"])
    op.create_index(op.f("ix_task_ticks_task_id"), "task_ticks", ["task_id"])
    # RLS and the deny posture: infra/supabase/migrations/202610290026_family_tasks.sql.


def downgrade() -> None:
    op.drop_table("task_ticks")
    op.drop_table("tasks")
