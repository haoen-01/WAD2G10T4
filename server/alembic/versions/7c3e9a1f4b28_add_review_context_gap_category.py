"""add the optional context-gap category to case reviews

Revision ID: 7c3e9a1f4b28
Revises: 485506d5a415
Create Date: 2026-09-16

Calibration trust (`docs/calibration-trust-spec.md`). What a review teaches SilverLoop is a pure
function of the stored review and is computed on read; the only new fact is what kind of known
context explained it, when a coordinator chose to say.

`case_reviews.context_gap_category`
    Nullable and not backfilled: no past reviewer was asked. Set only beside an override for
    `known_context`, tallied for the care team, and read by no decision, proposal or review
    setting.

The downgrade drops the column. Dropping a column makes SQLite's batch mode rebuild
`case_reviews`, which loses its append-only triggers, so the downgrade restores them exactly as
`485506d5a415` and `e3b7d5c18a42` do.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c3e9a1f4b28"
down_revision: str | None = "485506d5a415"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite adds a column in place, so the `case_reviews` triggers survive this direction; on
    # PostgreSQL batch mode emits a plain ALTER TABLE ADD COLUMN.
    with op.batch_alter_table("case_reviews") as batch:
        batch.add_column(sa.Column("context_gap_category", sa.String(length=40), nullable=True))
    # RLS and the deny posture for `case_reviews` already apply to the whole table; the
    # hand-applied mirror is infra/supabase/migrations/202609160020_review_context_gap.sql.


def downgrade() -> None:
    with op.batch_alter_table("case_reviews") as batch:
        batch.drop_column("context_gap_category")
    _restore_sqlite_append_only_triggers("case_reviews")


def _restore_sqlite_append_only_triggers(table: str) -> None:
    """Put back what a batch-mode table rebuild took away -- byte-for-byte `485506d5a415`'s helper,
    which is itself byte-for-byte the statements `3c430fbc9737` creates. `DROP ... IF EXISTS`
    first so this is safe whether or not batch mode actually rebuilt the table. A no-op on
    PostgreSQL, which never loses the triggers.
    """
    if op.get_bind().dialect.name != "sqlite":
        return
    for action in ("update", "delete"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_{action}")
        op.execute(
            f"CREATE TRIGGER {table}_reject_{action} BEFORE {action.upper()} ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'append-only evidence cannot be {action}d'); END"
        )
