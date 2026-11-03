"""split preference evidence for and against, give the ordinal axes a pivot, and record scope

Revision ID: e1c9a5d70b42
Revises: d81c4b0f6a27
Create Date: 2026-09-13

`activity_dimension_preferences.strength` was one signed scalar carrying three different facts at
once: which way a belief leans, how much evidence is behind it, and how confident that makes it.
Three consequences followed, all of them observable:

* `0.0` could not be told apart from "nothing known", so a like on one axis exactly cancelled an
  avoid on another and the card then read "Nothing learned applies to this listing."
* folding "it was fine" into "I loved it" overwrote the running magnitude, so what was learned
  depended on the order the two reports arrived in.
* a "too far" at 1.2 km was stored as the *bucket the listing fell in* (`near`), which taught the
  system to avoid activities near home -- the opposite of what was said.

`positive_evidence` / `negative_evidence` separate sentiment from confidence:
`strength = (pos - neg) / (pos + neg + 2)` and `confidence = (pos + neg) / (pos + neg + 2)`, both
derived, both order-independent. `pivot` / `direction` give DISTANCE and INTENSITY the ordinal
shape they always needed ("closer than 1200 m", "gentler than moderate"). `origin_id` makes one
origin one observation. `superseded_by` is what `forget` now stamps instead of deleting a row, and
what a statement stamps on the inferred row it ratifies. `scope` records how far a clarification
chip said a decline reaches.

`strength` and `observations` are deliberately **kept**: `world_model.py` and the Privacy screen
both read them, and a revision that removed them would be a contract change in the same breath as
a storage one. They are recomputed from the split from here on.

The backfill reads each pre-existing row's evidence back out of its own numbers, which takes
three cases rather than one. Pre-split, `strength` was always `cap * n / (n + 2)` for
`n = observations`:

* `cap = 1.0` -- a decline, or an enjoyed outing. `positive_evidence`/`negative_evidence` = `n`
  reproduces `(pos - neg) / (pos + neg + 2)` **exactly**: the row resolves to the strength it
  already had, which is the guarantee this revision is written to keep.
* `cap = 0.15` (`preferences._LEGACY_MAGNITUDE_CAP`, the old `_NEUTRAL_EVIDENCE_CAP`) -- "it was
  fine" (`Enjoyment.OKAY`) and "I'd prefer something else". These rows must be scaled by that
  cap: `0.15 * n`. Splitting `n` whole treated "it was fine" three times as three genuinely
  enjoyed outings and resolved `0.090` to `0.600`, a 6.7x amplification of a belief the person
  expressed as "fine". `0.15 * 3` resolves to `0.184`, which is exactly what a database this
  code writes from the same three reports holds -- so a migrated and a freshly-written database
  agree about identical history. The number moves because the split changed what "it was fine"
  *is* (a fraction of an observation rather than a capped magnitude), not because the backfill
  re-weighted it, and it stays inside the same barely-there band.
* `senior_statement` -- `strength` is `+/-1.0`, so there is nothing to invert, and a statement is
  one origin however many times it was made. Pre-split `observations` counted repeats on those
  rows rather than evidence, so `1.0` on the side the statement leans is both the honest reading
  and exactly what `_confirm_dimension_preference` writes today.

Which cap a row was written under is decidable from the row itself rather than guessed: the two
bands are disjoint, because with even one observation the uncapped shape is already `1/3` while
the capped one can never reach `0.15`. `preferences.evidence_split` applies the identical rule to
a row (or a hand-built `DimensionPreference`) that reaches it without the columns, so a belief
means the same thing however it got there.

A row with `strength == 0` contributes to neither side, which is the honest reading of "no lean".

`activity_offer_responses.clarification` and `intervention_outcomes.clarification` arrive with
them: both tables are append-only, so an added nullable column is compatible, and both are the
write path a decline chip has to reach.

Every column is nullable, so the revision is additive and the offline SQLite path is unaffected.
RLS and the deny-browser-access posture for all three tables already exist in their own mirrors
and apply to the whole table regardless of columns, so no new policy is needed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e1c9a5d70b42"
down_revision: str | None = "e3b7d5c18a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREFERENCE_COLUMNS = (
    sa.Column("positive_evidence", sa.Float(), nullable=True),
    sa.Column("negative_evidence", sa.Float(), nullable=True),
    sa.Column("pivot", sa.Float(), nullable=True),
    sa.Column("direction", sa.String(length=10), nullable=True),
    sa.Column("origin_id", sa.String(length=80), nullable=True),
    sa.Column("superseded_by", sa.String(length=80), nullable=True),
    sa.Column("scope", sa.String(length=20), nullable=True),
)

# How much evidence one pre-existing row stands for -- see the module docstring for the
# derivation. `preferences._legacy_evidence` is the same three cases in Python, and the two must
# not drift: a row read through the ORM before this revision runs and the same row read after it
# have to mean the same thing.
#
# `abs` and `case` are the only constructs here, so this is one statement on both SQLite and
# PostgreSQL (`greatest` is not SQLite's, and `max` is an aggregate on PostgreSQL).
_LEGACY_EVIDENCE_SQL = (
    "case "
    "when source = 'senior_statement' then 1.0 "
    "when abs(strength) <= 0.15 "
    "     then 0.15 * (case when observations > 0 then observations else 1 end) "
    "else (case when observations > 0 then observations else 1 end) "
    "end"
)

# Idempotent: only touches rows where both sides are still null, which a prior pass would already
# have resolved.
_BACKFILL_EVIDENCE_SQL = (
    "update activity_dimension_preferences "
    f"set positive_evidence = case when strength > 0 then {_LEGACY_EVIDENCE_SQL} else 0 end, "
    f"    negative_evidence = case when strength < 0 then {_LEGACY_EVIDENCE_SQL} else 0 end "
    "where positive_evidence is null and negative_evidence is null"
)


def upgrade() -> None:
    for column in _PREFERENCE_COLUMNS:
        op.add_column("activity_dimension_preferences", column)
    op.execute(_BACKFILL_EVIDENCE_SQL)
    op.add_column(
        "activity_offer_responses",
        sa.Column("clarification", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "intervention_outcomes",
        sa.Column("clarification", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("intervention_outcomes", "clarification")
    op.drop_column("activity_offer_responses", "clarification")
    for column in reversed(_PREFERENCE_COLUMNS):
        op.drop_column("activity_dimension_preferences", column.name)
