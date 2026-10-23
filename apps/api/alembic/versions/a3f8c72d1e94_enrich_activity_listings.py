"""enrich activity listings so a senior can attend without cross-checking

Revision ID: a3f8c72d1e94
Revises: f7c2a9d4e6b3
Create Date: 2026-09-06

A listing that gives a venue name and a distance still leaves a person ringing round to find the
address, the bus, whether to book, and what to bring. That chasing is what stops someone
attending, and it falls hardest on the people least able to do it. These columns carry the whole
answer on the listing itself.

Every one is nullable or defaulted: "not listed" is a real answer here and must survive to the
screen as one, rather than being backfilled with something plausible.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a3f8c72d1e94"
down_revision: str | None = "f7c2a9d4e6b3"
branch_labels: str | None = None
depends_on: str | None = None

_COLUMNS = (
    sa.Column("location_postal_code", sa.String(length=20), nullable=True),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("duration_minutes", sa.Integer(), nullable=True),
    sa.Column("what_to_bring_json", sa.JSON(), nullable=True),
    sa.Column("booking", sa.String(length=20), nullable=False, server_default="unknown"),
    sa.Column("booking_note", sa.String(length=300), nullable=True),
    sa.Column("contact_phone", sa.String(length=40), nullable=True),
    sa.Column("contact_note", sa.String(length=200), nullable=True),
    sa.Column("getting_there_json", sa.JSON(), nullable=True),
    sa.Column("good_to_know_json", sa.JSON(), nullable=True),
)


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("activity_candidates", column)


def downgrade() -> None:
    for column in reversed(_COLUMNS):
        op.drop_column("activity_candidates", column.name)
