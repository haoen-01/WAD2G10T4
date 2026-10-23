"""add baseline confirmations: the senior's own release for the drift clamp

Revision ID: b8e4f6c1a205
Revises: a3f8c72d1e94
Create Date: 2026-09-09

`analytics.BASELINE_DRIFT_FLOOR` stops a declining person's own rolling median from erasing them,
but nothing released it: a person who genuinely and permanently changed their life kept reading as
below their reference forever. This table is the release -- an append-only record of the senior
being asked "is this your new normal?" and answering, confirm or decline. The most recent
`confirm` row for a run is the reference `calculate_reference` uses going forward; see
`baseline_confirmation.py` and `ConfirmedReference`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8e4f6c1a205"
down_revision: str | None = "a3f8c72d1e94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "baseline_confirmations",
        sa.Column("confirmation_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("streak_days", sa.Integer(), nullable=False),
        sa.Column("previous_reference_steps", sa.Float(), nullable=False),
        sa.Column("new_reference_steps", sa.Float(), nullable=True),
        sa.Column("decided_on_day", sa.Date(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("confirmation_id"),
    )
    op.create_index(
        op.f("ix_baseline_confirmations_run_id"),
        "baseline_confirmations",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_baseline_confirmations_person_id"),
        "baseline_confirmations",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_baseline_confirmations_run_decided",
        "baseline_confirmations",
        ["run_id", "decided_on_day"],
        unique=False,
    )
    # RLS enablement and the anon/authenticated deny posture are Supabase-platform-specific and
    # live exclusively in the hand-applied SQL mirror at
    # infra/supabase/migrations/202609090010_baseline_confirmations.sql, matching every other
    # table in this repo (see infra/supabase/migrations/).


def downgrade() -> None:
    op.drop_index("ix_baseline_confirmations_run_decided", table_name="baseline_confirmations")
    op.drop_index(op.f("ix_baseline_confirmations_person_id"), table_name="baseline_confirmations")
    op.drop_index(op.f("ix_baseline_confirmations_run_id"), table_name="baseline_confirmations")
    op.drop_table("baseline_confirmations")
