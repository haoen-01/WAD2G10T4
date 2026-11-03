"""give a review case a clock, a typed ending and a record of what the human decided

Revision ID: e3b7d5c18a42
Revises: a1d5f3b87c46
Create Date: 2026-09-13

Five nullable columns across the two case tables, for two closely related gaps (audit-H findings
3 and 4). They ship as one revision because they describe one object -- what happened to a review
case -- and splitting them would mean two migrations, two hand-applied Supabase mirrors and two
chances for a coordinator surface to half-exist.

`review_cases.opened_day`
    The simulated day the case opened. `opened_at` was the only timestamp a case had, and it is a
    wall clock: nothing in this product advances time except `POST /v1/simulation/advance`, so it
    cannot answer "how long has this been waiting?". `days_in_review` and `review_by_day` are
    derived from this column rather than stored beside it -- both are functions of it plus a
    constant, and a second stored copy could disagree with the first.

`review_cases.resolution`
    Why the case closed, as a `CaseResolution`. A case has exactly three endings (the person's
    activity came back, they withdrew consent, a coordinator answered) and the reason previously
    existed only inside the English prose of a system-authored review note, so anything wanting to
    act on it had to string-match a sentence.

`case_reviews.agent_recommendation` / `.human_action` / `.override_reason`
    What SilverLoop suggested, what the human chose, and -- when those differ -- the reason they
    gave. Review was built as an audit checkbox (a status and a note), which made "does a human
    agree with this system?" unanswerable. `agent_recommendation` is a frozen copy rather than a
    foreign key because a later refresh must not retroactively change what the human was reading.
    None of it is a learning signal: nothing in the ranking path reads this table.

No data step, and every column is nullable. Backfilling would mean inventing facts nobody
recorded: there is no honest way to know which simulated day a pre-existing case opened (a refresh
overwrites `decision_evidence_id`, so the surviving evidence points at the latest day, not the
first), and no way at all to know what a past reviewer would have chosen from an enum that did not
exist. A case that predates this revision reports "not recorded", which is true.

The downgrade drops the five columns and, with them, every clock and override fact recorded while
they existed -- unavoidable, and the reason the upgrade is the additive direction.

It also re-creates the two append-only triggers on `case_reviews`. SQLite cannot drop a column in
place, so Alembic's batch mode rebuilds the table (create, copy, drop, rename) and a rebuilt table
carries none of the original's triggers. Nothing later in the chain re-creates them, so without
this the downgrade silently and permanently removed the append-only guarantee from
coordinator-review evidence: re-upgrading never restored it, the database still reported itself at
head and `/ready` still passed. The upgrade direction needs no such step, because SQLite adds a
column in place; PostgreSQL needs none in either direction, because batch mode emits a plain
`ALTER TABLE ... DROP COLUMN` there and the triggers are never disturbed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3b7d5c18a42"
down_revision: str | None = "b6c1f4d92a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("review_cases") as batch:
        batch.add_column(sa.Column("opened_day", sa.Date(), nullable=True))
        batch.add_column(sa.Column("resolution", sa.String(length=40), nullable=True))
    with op.batch_alter_table("case_reviews") as batch:
        batch.add_column(sa.Column("agent_recommendation", sa.Text(), nullable=True))
        batch.add_column(sa.Column("human_action", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("override_reason", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("case_reviews") as batch:
        batch.drop_column("override_reason")
        batch.drop_column("human_action")
        batch.drop_column("agent_recommendation")
    _restore_sqlite_append_only_triggers("case_reviews")
    with op.batch_alter_table("review_cases") as batch:
        batch.drop_column("resolution")
        batch.drop_column("opened_day")


def _restore_sqlite_append_only_triggers(table: str) -> None:
    """Put back what a batch-mode table rebuild took away.

    Byte-for-byte the statements `3c430fbc9737` creates, so the rebuilt table is left in exactly
    the state the base revision leaves it in -- not an approximation of it. `DROP ... IF EXISTS`
    first so this is safe to run whether or not the rebuild actually happened: Alembic's batch
    mode chooses between an in-place ALTER and a rebuild, and a migration must not depend on
    which it picked.

    PostgreSQL never loses the triggers (batch mode issues a plain `ALTER TABLE ... DROP COLUMN`
    there), so this is a no-op on it rather than a second, divergent definition.
    """
    if op.get_bind().dialect.name != "sqlite":
        return
    for action in ("update", "delete"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_{action}")
        op.execute(
            f"CREATE TRIGGER {table}_reject_{action} BEFORE {action.upper()} ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'append-only evidence cannot be {action}d'); END"
        )
