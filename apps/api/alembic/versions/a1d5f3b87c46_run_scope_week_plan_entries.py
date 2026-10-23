"""run-scope the week plan uniqueness key

Revision ID: a1d5f3b87c46
Revises: c2725d7de5df
Create Date: 2026-09-13

`week_plan_entries` always carried `run_id`, but `(person_id, day, activity_id)` was unique across
every run and the repository's readers never filtered on the column. A demo reset rewinds the
simulated calendar to the fixture's anchor day, so a plan an earlier run made lands inside the
live week again: the senior saw a dead run's outings on their week, could report "went" and
"enjoyed" on them, and those reports wrote inferred dimension preferences into the *new* run
(audit I finding 1, reproduced). `SqlAlchemyRepository` now filters every plan reader and writer
on the active run -- see `db_models.WeekPlanEntryRow`'s own docstring and ADR 0004.

The constraint has to move with them. Person-scoped uniqueness does not merely fail to help: it
makes a live re-plan impossible. Once a dead run holds `(person, day, activity)`, the new run's
insert of the same choice is rejected by the database, and the senior's "add to my week" fails
for a week that shows nothing. `(run_id, person_id, day, activity_id)` keeps the within-run no-op
this key exists for and lets the same choice be made again in a later story.

No data step: the new key is strictly weaker than the old one, so every existing row already
satisfies it. The downgrade is the honest reverse and will raise if the table has since collected
the cross-run duplicates the new key permits -- a downgrade must not quietly delete a person's
plan to fit an older schema.

RLS and the deny-browser-access posture for `week_plan_entries` are already in the Supabase mirror
(`infra/supabase/migrations/202609060008_enjoyment_memory_goals_week_plan.sql`) and apply to the
whole table regardless of its constraints, so the mirror for this revision only needs the guarded
constraint swap and the `alembic_version` bump.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a1d5f3b87c46"
down_revision: str | None = "c2725d7de5df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CONSTRAINT = "uq_week_plan_person_day_activity"
_NEW_CONSTRAINT = "uq_week_plan_run_person_day_activity"


def upgrade() -> None:
    # Batch mode so SQLite (which cannot alter a constraint in place) recreates the table; on
    # PostgreSQL the same two calls emit plain ALTER TABLE statements.
    with op.batch_alter_table("week_plan_entries") as batch:
        batch.drop_constraint(_OLD_CONSTRAINT, type_="unique")
        batch.create_unique_constraint(
            _NEW_CONSTRAINT, ["run_id", "person_id", "day", "activity_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("week_plan_entries") as batch:
        batch.drop_constraint(_NEW_CONSTRAINT, type_="unique")
        batch.create_unique_constraint(_OLD_CONSTRAINT, ["person_id", "day", "activity_id"])
