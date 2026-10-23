"""label the catalogue with what each listing is, how it is run, and where its facts came from

Revision ID: d81c4b0f6a27
Revises: c2725d7de5df
Create Date: 2026-09-13

`activity_candidates.category` was one free-text column doing three jobs -- the card badge, the
learner's content axis and the diversity key -- and the strings in it ("Group class", "Social
group") describe *format*, not content. A single "not for me" on a morning walk therefore taught
a dislike of nine unrelated programmes, tai chi and gardening among them.

Three columns separate the facts that column conflated: `activity_type` (what the thing is, one
value from `ontology.ActivityType`), `activity_families_json` (the broad kinds it belongs to,
multi-label) and `format` (how it is run). `category` is kept and stays the badge, now written
from `ontology.FORMAT_LABEL`.

Two provenance columns come with them -- `metadata_source` and `last_verified_at` -- because a
catalogue that cannot say where a listing's facts came from cannot say how much to trust them.
Both are nullable and a fixture listing leaves `last_verified_at` null on purpose: nobody has
checked these against a real centre, and a date here would claim they had.

`distance_basis` becomes a stored column rather than something the reader infers from
`distance_m is None`. That inference is only correct while exactly one basis exists; the moment a
routing adapter measures a real walk, every row it wrote would still read "a fixed figure typed
into the listing". Existing rows are backfilled from the same rule the reader used, so nothing
changes meaning at the moment this runs, and the reader keeps the fallback for any row written
before this revision.

Every column is nullable, so the revision is additive and the offline SQLite path is unaffected.
RLS and the deny-browser-access posture for `activity_candidates` are already in the Supabase
mirror (`202609060007_activity_catalogue.sql`) and apply to the whole table regardless of
columns, so the mirror for this revision only needs the guarded column adds, the backfill and the
`alembic_version` bump.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d81c4b0f6a27"
down_revision: str | None = "a1d5f3b87c46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    sa.Column("activity_type", sa.String(length=40), nullable=True),
    sa.Column("activity_families_json", sa.JSON(), nullable=True),
    sa.Column("format", sa.String(length=40), nullable=True),
    sa.Column("metadata_source", sa.String(length=120), nullable=True),
    sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("distance_basis", sa.String(length=40), nullable=True),
)

# Exactly the rule `sql_repository._to_activity_candidate` applied before the column existed, so
# no row's meaning changes as this runs. Idempotent: only touches rows still null, which a prior
# pass would already have resolved.
_BACKFILL_DISTANCE_BASIS_SQL = (
    "update activity_candidates "
    "set distance_basis = case when distance_m is null then 'unknown' else 'listing_static' end "
    "where distance_basis is null"
)


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("activity_candidates", column)
    op.execute(_BACKFILL_DISTANCE_BASIS_SQL)


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_column("activity_candidates", column.name)
