"""add enjoyment, proposed memory, context questions, goals and the week plan

Revision ID: f7c2a9d4e6b3
Revises: e5b8d2a4f7c1
Create Date: 2026-09-06 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7c2a9d4e6b3"
down_revision: str | None = "e5b8d2a4f7c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Whether one piece of outreach was any good, once the person has said. One row per
    # intervention, enforced here just like `intervention_follow_through` -- a second row would
    # double-count one intervention's evidence.
    op.create_table(
        "intervention_enjoyment",
        sa.Column("enjoyment_id", sa.String(length=64), nullable=False),
        sa.Column("intervention_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("enjoyment", sa.String(length=40), nullable=False),
        sa.Column("liked_json", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["intervention_id"], ["interventions.intervention_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("enjoyment_id"),
        sa.UniqueConstraint("intervention_id", name="uq_enjoyment_intervention"),
    )
    op.create_index(
        op.f("ix_intervention_enjoyment_intervention_id"),
        "intervention_enjoyment",
        ["intervention_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intervention_enjoyment_run_id"),
        "intervention_enjoyment",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_intervention_enjoyment_person_id"),
        "intervention_enjoyment",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_enjoyment_run_recorded",
        "intervention_enjoyment",
        ["run_id", "recorded_at"],
        unique=False,
    )

    # Something SilverLoop believes it has learned, held back until the person agrees to it.
    # `status` starts `pending` and becomes `remember` / `just_today` / `no` once decided.
    op.create_table(
        "proposed_memories",
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=160), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("proposal_id"),
    )
    op.create_index(
        op.f("ix_proposed_memories_run_id"), "proposed_memories", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_proposed_memories_person_id"), "proposed_memories", ["person_id"], unique=False
    )
    op.create_index(
        "ix_proposed_memories_person_status",
        "proposed_memories",
        ["person_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_proposed_memories_person_dimension_value",
        "proposed_memories",
        ["person_id", "dimension", "value"],
        unique=False,
    )

    # A record that one context question was asked and answered, so `question_for` knows which
    # questions have already been put to this person this run. The question itself is never
    # stored ahead of time -- it is computed fresh from `PersonState` every time.
    op.create_table(
        "context_question_answers",
        sa.Column("answer_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=160), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("answer_id"),
    )
    op.create_index(
        op.f("ix_context_question_answers_run_id"),
        "context_question_answers",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_context_question_answers_person_id"),
        "context_question_answers",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_context_question_answers_run",
        "context_question_answers",
        ["run_id", "question_id"],
        unique=False,
    )

    # A lifestyle goal the person has chosen -- never a health target, never scored.
    # `(person_id, kind)` is unique: the current goal of a given kind is one row, replaced in
    # place, matching `activity_dimension_preferences`.
    op.create_table(
        "activity_goals",
        sa.Column("goal_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("target_per_week", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("goal_id"),
        sa.UniqueConstraint("person_id", "kind", name="uq_activity_goal_person_kind"),
    )
    op.create_index(
        op.f("ix_activity_goals_person_id"), "activity_goals", ["person_id"], unique=False
    )

    # One activity a person has put on their own week -- chosen, not suggested.
    # `(person_id, day, activity_id)` is unique so re-submitting the same choice is a no-op.
    op.create_table(
        "week_plan_entries",
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("activity_id", sa.String(length=80), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("replaced_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.ForeignKeyConstraint(["activity_id"], ["activity_candidates.activity_id"]),
        sa.PrimaryKeyConstraint("plan_id"),
        sa.UniqueConstraint(
            "person_id", "day", "activity_id", name="uq_week_plan_person_day_activity"
        ),
    )
    op.create_index(
        op.f("ix_week_plan_entries_run_id"), "week_plan_entries", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_week_plan_entries_person_id"), "week_plan_entries", ["person_id"], unique=False
    )
    op.create_index(
        "ix_week_plan_entries_person_day",
        "week_plan_entries",
        ["person_id", "day"],
        unique=False,
    )
    # RLS enablement and the anon/authenticated deny posture for these tables are
    # Supabase-platform-specific and live exclusively in the hand-applied SQL mirror at
    # infra/supabase/migrations/202609060008_enjoyment_memory_goals_week_plan.sql, matching
    # every other table in this repo (see infra/supabase/migrations/).


def downgrade() -> None:
    op.drop_index("ix_week_plan_entries_person_day", table_name="week_plan_entries")
    op.drop_index(op.f("ix_week_plan_entries_person_id"), table_name="week_plan_entries")
    op.drop_index(op.f("ix_week_plan_entries_run_id"), table_name="week_plan_entries")
    op.drop_table("week_plan_entries")

    op.drop_index(op.f("ix_activity_goals_person_id"), table_name="activity_goals")
    op.drop_table("activity_goals")

    op.drop_index("ix_context_question_answers_run", table_name="context_question_answers")
    op.drop_index(
        op.f("ix_context_question_answers_person_id"), table_name="context_question_answers"
    )
    op.drop_index(op.f("ix_context_question_answers_run_id"), table_name="context_question_answers")
    op.drop_table("context_question_answers")

    op.drop_index("ix_proposed_memories_person_dimension_value", table_name="proposed_memories")
    op.drop_index("ix_proposed_memories_person_status", table_name="proposed_memories")
    op.drop_index(op.f("ix_proposed_memories_person_id"), table_name="proposed_memories")
    op.drop_index(op.f("ix_proposed_memories_run_id"), table_name="proposed_memories")
    op.drop_table("proposed_memories")

    op.drop_index("ix_enjoyment_run_recorded", table_name="intervention_enjoyment")
    op.drop_index(op.f("ix_intervention_enjoyment_person_id"), table_name="intervention_enjoyment")
    op.drop_index(op.f("ix_intervention_enjoyment_run_id"), table_name="intervention_enjoyment")
    op.drop_index(
        op.f("ix_intervention_enjoyment_intervention_id"), table_name="intervention_enjoyment"
    )
    op.drop_table("intervention_enjoyment")
