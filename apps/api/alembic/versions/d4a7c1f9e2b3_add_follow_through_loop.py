"""add the follow-through loop: outcome reasons, follow-through, preferences, day disputes

Revision ID: d4a7c1f9e2b3
Revises: c9d3e8f2a1b5
Create Date: 2026-09-06 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4a7c1f9e2b3"
down_revision: str | None = "c9d3e8f2a1b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable and never backfilled. An outcome recorded before this column existed genuinely
    # carries no reason, and inventing one would be worse than the gap.
    op.add_column(
        "intervention_outcomes",
        sa.Column("reason", sa.String(length=40), nullable=True),
    )

    op.create_table(
        "intervention_follow_through",
        sa.Column("follow_through_id", sa.String(length=64), nullable=False),
        sa.Column("intervention_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("follow_through", sa.String(length=40), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["intervention_id"], ["interventions.intervention_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("follow_through_id"),
        # One report per intervention, enforced here rather than only in the repository: a second
        # row would double-count one intervention's evidence in the preference posterior.
        sa.UniqueConstraint("intervention_id", name="uq_follow_through_intervention"),
    )
    op.create_index(
        op.f("ix_intervention_follow_through_intervention_id"),
        "intervention_follow_through",
        ["intervention_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intervention_follow_through_run_id"),
        "intervention_follow_through",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intervention_follow_through_person_id"),
        "intervention_follow_through",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_follow_through_run_recorded",
        "intervention_follow_through",
        ["run_id", "recorded_at"],
        unique=False,
    )

    # Person-scoped, not run-scoped: "stop offering me this" is a statement about someone's life,
    # and a demo reset must not quietly start offering it again.
    op.create_table(
        "candidate_preferences",
        sa.Column("preference_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_key", sa.String(length=120), nullable=False),
        sa.Column("suppressed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("preference_id"),
        sa.UniqueConstraint(
            "person_id", "candidate_key", name="uq_candidate_preference_person_key"
        ),
    )
    op.create_index(
        op.f("ix_candidate_preferences_person_id"),
        "candidate_preferences",
        ["person_id"],
        unique=False,
    )

    op.create_table(
        "day_disputes",
        sa.Column("dispute_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("accurate", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("dispute_id"),
    )
    op.create_index(op.f("ix_day_disputes_run_id"), "day_disputes", ["run_id"], unique=False)
    op.create_index(op.f("ix_day_disputes_person_id"), "day_disputes", ["person_id"], unique=False)
    op.create_index(
        "ix_day_disputes_person_day", "day_disputes", ["person_id", "day"], unique=False
    )
    # RLS enablement and the anon/authenticated deny posture for these tables are
    # Supabase-platform-specific and live exclusively in the hand-applied SQL mirror at
    # infra/supabase/migrations/202609060006_follow_through_loop.sql, matching every other
    # table in this repo (see infra/supabase/migrations/).


def downgrade() -> None:
    op.drop_index("ix_day_disputes_person_day", table_name="day_disputes")
    op.drop_index(op.f("ix_day_disputes_person_id"), table_name="day_disputes")
    op.drop_index(op.f("ix_day_disputes_run_id"), table_name="day_disputes")
    op.drop_table("day_disputes")

    op.drop_index(op.f("ix_candidate_preferences_person_id"), table_name="candidate_preferences")
    op.drop_table("candidate_preferences")

    op.drop_index("ix_follow_through_run_recorded", table_name="intervention_follow_through")
    op.drop_index(
        op.f("ix_intervention_follow_through_person_id"),
        table_name="intervention_follow_through",
    )
    op.drop_index(
        op.f("ix_intervention_follow_through_run_id"),
        table_name="intervention_follow_through",
    )
    op.drop_index(
        op.f("ix_intervention_follow_through_intervention_id"),
        table_name="intervention_follow_through",
    )
    op.drop_table("intervention_follow_through")

    op.drop_column("intervention_outcomes", "reason")
