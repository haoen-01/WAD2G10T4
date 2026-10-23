"""add run scoping to inferred activity dimension preferences

Revision ID: c2725d7de5df
Revises: c2f4a8d1e6b7
Create Date: 2026-09-13

A demo reset used to delete every `activity_dimension_preferences` row outright, the only place
the repository destroyed derived domain state -- a person's own stated preference vanished on
reset while their outreach mutes (`candidate_preferences`) stayed. It did this because the table
carried no notion of which run's story a row's evidence came from, and the reset rewinds the
simulated calendar to the fixture's anchor day.

One nullable column replaces the delete: `run_id`, a foreign key to `scenario_runs.run_id`.
`SqlAlchemyRepository.reset` no longer touches this table. A *standing* `senior_statement` row
(the person's own words, with no `expires_at`) keeps `run_id = None` and is never run-scoped --
it is a standing instruction, like a mute, and survives a reset exactly the way one does. Every
other row -- a *time-boxed* `senior_statement` (`expires_at` set) or a `decline_reason`/`inferred`
row -- is stamped with the run that produced it; every reader that asks "what does this person
currently hold" (`SqlAlchemyRepository._dimension_rows`) treats a row whose `run_id` is not the
active run's as absent, the same way it already treats a calendar-expired row, and reuses it in
place -- observations restarted at one -- rather than resurrecting a belief from a story that no
longer exists. See `db_models.ActivityDimensionPreferenceRow`'s own docstring. Crucially,
"standing" is decided from the row's own `source`/`expires_at`, never from `run_id is None` --
every row this table already held before this revision also has `run_id = None`, and misreading
that as "standing" would make every existing inferred belief permanent and let every existing
time-boxed statement keep resurrecting after a reset instead of lapsing. This revision backfills
those existing rows below so they read correctly (run-scoped, and inactive against whichever run
is active once this migration runs) from the moment it completes, not only once new evidence
happens to touch them.

RLS and the deny-browser-access posture for `activity_dimension_preferences` are already in the
Supabase mirror (`infra/supabase/migrations/202609060007_activity_catalogue.sql`) and apply to
the whole table regardless of columns, so the mirror for this revision only needs the guarded
column/index add, the backfill and the `alembic_version` bump.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2725d7de5df"
down_revision: str | None = "c2f4a8d1e6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Any row already in this table before this revision, where the fact it carries is not a
# standing statement -- i.e. `source <> 'senior_statement'` (a decline/enjoyment belief) or
# `expires_at is not null` (a time-boxed statement) -- needs a `run_id`, or it reads as standing
# by accident (see `_preference_inactive` in `sql_repository.py`). Backfilled to the row's
# person's currently *active* scenario run, since that is the only run any reader could mean by
# "the active run" at the moment this migration runs. A person with no active run (should not
# happen in practice: every reset provisions one) is left `run_id = null` on purpose -- the read
# path already treats a non-standing row with no matching `run_id` as run-scoped-and-inactive, so
# guessing a run for it would be no safer than leaving it null, and would be a fabricated fact.
# Idempotent by construction: re-running only ever touches rows that are still `run_id is null`,
# which a prior run of this statement would already have resolved for every row it could reach.
# `order by ... limit 1`: nothing in the schema enforces one active run per person (only
# `reset()` does), so a stray second active run must not abort the whole migration.
_BACKFILL_RUN_ID_SQL = (
    "update activity_dimension_preferences "
    "set run_id = ("
    "    select sr.run_id from scenario_runs as sr "
    "    where sr.person_id = activity_dimension_preferences.person_id and sr.active = true"
    "    order by sr.started_at desc limit 1"
    ") "
    "where run_id is null "
    "and (source <> 'senior_statement' or expires_at is not null) "
    "and exists ("
    "    select 1 from scenario_runs as sr2 "
    "    where sr2.person_id = activity_dimension_preferences.person_id and sr2.active = true"
    ")"
)


def upgrade() -> None:
    # Batch mode so SQLite (which cannot add a foreign key in place) recreates the table; on
    # PostgreSQL the same calls emit plain ALTER TABLE statements.
    with op.batch_alter_table("activity_dimension_preferences") as batch:
        batch.add_column(sa.Column("run_id", sa.String(length=64), nullable=True))
        batch.create_foreign_key(
            "fk_activity_dimension_preferences_run_id",
            "scenario_runs",
            ["run_id"],
            ["run_id"],
        )
    op.create_index(
        op.f("ix_activity_dimension_preferences_run_id"),
        "activity_dimension_preferences",
        ["run_id"],
        unique=False,
    )
    op.execute(_BACKFILL_RUN_ID_SQL)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_activity_dimension_preferences_run_id"),
        table_name="activity_dimension_preferences",
    )
    with op.batch_alter_table("activity_dimension_preferences") as batch:
        batch.drop_constraint("fk_activity_dimension_preferences_run_id", type_="foreignkey")
        batch.drop_column("run_id")
