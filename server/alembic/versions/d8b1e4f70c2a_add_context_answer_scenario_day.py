"""record the scenario day a context question was answered on

Revision ID: d8b1e4f70c2a
Revises: e1c9a5d70b42
Create Date: 2026-09-13

`context_question_answers` carried only `answered_at`, a wall-clock timestamp. That was enough
while the answer's *content* was never read: the row existed so `question_for` could be told the
question had already been put to this person (`asked_recently`), and nothing reasoned over time
about what the person had said.

`context_explanation.py` now does reason over time -- an answer explains a quieter reading for a
bounded number of days -- and a window measured from `answered_at` would reproduce the
`_weekly_contact_count` bug exactly: a demo advancing ten simulated days in one wall-clock minute
would see every answer as given "today", so an explanation would never expire. This revision adds
`answered_on_day`, the scenario day (`PersonState.current_day`), which is the same split and the
same justification as `BaselineConfirmationRow.decided_on_day`.

Nullable, and deliberately not backfilled. An existing row's scenario day cannot be recovered from
its wall-clock timestamp -- the simulated calendar does not advance in step with real time, which
is the whole reason this column exists -- so any value written here would be a fabricated fact in
an evidence table. `context_explanation.active_explanation` skips a row whose `answered_on_day` is
null, which makes a pre-existing answer behave exactly as it did before this revision: recorded,
displayed, counted for `asked_recently`, and explaining nothing.

RLS and the deny-browser-access posture for `context_question_answers` are already in the Supabase
mirror (`infra/supabase/migrations/202609060008_enjoyment_memory_goals_week_plan.sql`) and apply to
the whole table regardless of columns, so the mirror for this revision only needs the guarded
column add and the `alembic_version` bump.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8b1e4f70c2a"
down_revision: str | None = "e1c9a5d70b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Batch mode for SQLite parity with every other revision in this chain; on PostgreSQL it emits
    # a plain ALTER TABLE ADD COLUMN.
    with op.batch_alter_table("context_question_answers") as batch:
        batch.add_column(sa.Column("answered_on_day", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("context_question_answers") as batch:
        batch.drop_column("answered_on_day")
