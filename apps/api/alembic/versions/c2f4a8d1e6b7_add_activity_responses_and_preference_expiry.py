"""add activity responses, plan follow-through/enjoyment, and preference expiry

Revision ID: c2f4a8d1e6b7
Revises: b8e4f6c1a205
Create Date: 2026-09-12

Closes the user-initiated loop. Until now a "Not for me" on a search card lived and died in the
browser, a search result could not be chosen, and so nothing a person found for themselves ever
reached follow-through, enjoyment or the dimensional learner. Three new append-only evidence
tables carry those three beats -- `activity_offer_responses` (many per person and listing),
`plan_follow_through` and `plan_enjoyment` (one per plan entry, like their intervention twins) --
with the same reject-update/reject-delete triggers the other evidence tables have, on BOTH
dialects, so the offline SQLite demo keeps the guarantee and not only Postgres.

Two changes to `activity_dimension_preferences`: `source` joins the unique key, because the
decline and enjoyment learners keep their evidence on separate tiers and the old
`(person_id, dimension, value)` key let a decline overwrite what an enjoyed activity taught; and
three nullable columns -- `expires_at` (a temporary preference such as "no walks this week"),
`stated_text` (the person's own words, when they said it) and `first_observed_at` (never
backfilled: a guessed first date is a fabricated one).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2f4a8d1e6b7"
down_revision: str | None = "b8e4f6c1a205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY = ("activity_offer_responses", "plan_follow_through", "plan_enjoyment")


def _append_only_triggers(dialect: str) -> None:
    """Same DDL `3c430fbc9737` and `b6f42a71e903` install for the other evidence tables."""
    for table in _APPEND_ONLY:
        if dialect == "sqlite":
            op.execute(
                f"CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only evidence cannot be updated'); END"
            )
            op.execute(
                f"CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only evidence cannot be deleted'); END"
            )
        elif dialect == "postgresql":
            op.execute(
                f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_silverloop_evidence_mutation()"
            )


def upgrade() -> None:
    # Batch mode so SQLite (which cannot alter constraints in place) recreates the table; on
    # PostgreSQL the same calls emit plain ALTER TABLE statements.
    with op.batch_alter_table("activity_dimension_preferences") as batch:
        batch.drop_constraint("uq_activity_dimension_person_value", type_="unique")
        batch.create_unique_constraint(
            "uq_activity_dimension_person_value_source",
            ["person_id", "dimension", "value", "source"],
        )
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("stated_text", sa.String(length=280), nullable=True))
        batch.add_column(sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "activity_offer_responses",
        sa.Column("response_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("activity_id", sa.String(length=80), nullable=False),
        sa.Column("query_id", sa.String(length=64), nullable=True),
        sa.Column("response", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=True),
        sa.Column("rank_shown", sa.Integer(), nullable=True),
        sa.Column("plan_id", sa.String(length=64), nullable=True),
        sa.Column("recorded_on_day", sa.Date(), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.ForeignKeyConstraint(["activity_id"], ["activity_candidates.activity_id"]),
        sa.PrimaryKeyConstraint("response_id"),
    )
    op.create_index(
        op.f("ix_activity_offer_responses_run_id"),
        "activity_offer_responses",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_activity_offer_responses_person_id"),
        "activity_offer_responses",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_activity_offer_responses_person_activity",
        "activity_offer_responses",
        ["person_id", "activity_id"],
        unique=False,
    )
    op.create_index(
        "ix_activity_offer_responses_run_recorded",
        "activity_offer_responses",
        ["run_id", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "plan_follow_through",
        sa.Column("follow_through_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("follow_through", sa.String(length=40), nullable=False),
        sa.Column("note", sa.String(length=280), nullable=True),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["week_plan_entries.plan_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("follow_through_id"),
        sa.UniqueConstraint("plan_id", name="uq_plan_follow_through_plan"),
    )
    op.create_index(
        op.f("ix_plan_follow_through_plan_id"), "plan_follow_through", ["plan_id"], unique=False
    )
    op.create_index(
        op.f("ix_plan_follow_through_run_id"), "plan_follow_through", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_plan_follow_through_person_id"),
        "plan_follow_through",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_plan_follow_through_run_recorded",
        "plan_follow_through",
        ["run_id", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "plan_enjoyment",
        sa.Column("enjoyment_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("enjoyment", sa.String(length=40), nullable=False),
        sa.Column("liked_json", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["week_plan_entries.plan_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("enjoyment_id"),
        sa.UniqueConstraint("plan_id", name="uq_plan_enjoyment_plan"),
    )
    op.create_index(op.f("ix_plan_enjoyment_plan_id"), "plan_enjoyment", ["plan_id"], unique=False)
    op.create_index(op.f("ix_plan_enjoyment_run_id"), "plan_enjoyment", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_plan_enjoyment_person_id"), "plan_enjoyment", ["person_id"], unique=False
    )
    op.create_index(
        "ix_plan_enjoyment_run_recorded", "plan_enjoyment", ["run_id", "recorded_at"], unique=False
    )

    _append_only_triggers(op.get_bind().dialect.name)
    # RLS enablement and the anon/authenticated deny posture for these tables are
    # Supabase-platform-specific and live exclusively in the hand-applied SQL mirror at
    # infra/supabase/migrations/202609120011_activity_responses.sql.


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for table in _APPEND_ONLY:
        if dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete")
        elif dialect == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.drop_index("ix_plan_enjoyment_run_recorded", table_name="plan_enjoyment")
    op.drop_index(op.f("ix_plan_enjoyment_person_id"), table_name="plan_enjoyment")
    op.drop_index(op.f("ix_plan_enjoyment_run_id"), table_name="plan_enjoyment")
    op.drop_index(op.f("ix_plan_enjoyment_plan_id"), table_name="plan_enjoyment")
    op.drop_table("plan_enjoyment")
    op.drop_index("ix_plan_follow_through_run_recorded", table_name="plan_follow_through")
    op.drop_index(op.f("ix_plan_follow_through_person_id"), table_name="plan_follow_through")
    op.drop_index(op.f("ix_plan_follow_through_run_id"), table_name="plan_follow_through")
    op.drop_index(op.f("ix_plan_follow_through_plan_id"), table_name="plan_follow_through")
    op.drop_table("plan_follow_through")
    op.drop_index("ix_activity_offer_responses_run_recorded", table_name="activity_offer_responses")
    op.drop_index(
        "ix_activity_offer_responses_person_activity", table_name="activity_offer_responses"
    )
    op.drop_index(
        op.f("ix_activity_offer_responses_person_id"), table_name="activity_offer_responses"
    )
    op.drop_index(op.f("ix_activity_offer_responses_run_id"), table_name="activity_offer_responses")
    op.drop_table("activity_offer_responses")
    with op.batch_alter_table("activity_dimension_preferences") as batch:
        batch.drop_column("first_observed_at")
        batch.drop_column("stated_text")
        batch.drop_column("expires_at")
        batch.drop_constraint("uq_activity_dimension_person_value_source", type_="unique")
        batch.create_unique_constraint(
            "uq_activity_dimension_person_value", ["person_id", "dimension", "value"]
        )
