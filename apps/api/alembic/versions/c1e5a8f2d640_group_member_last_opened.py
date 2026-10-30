"""each member's last opened family group

Revision ID: c1e5a8f2d640
Revises: f3a9c1e7b254
Create Date: 2026-10-30

`group_members.last_opened_at` is when this member last opened this family group (issue #17): the
latest one among their active memberships is their current group. Existing rows stay NULL, meaning
never opened; nothing is backfilled.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1e5a8f2d640"
down_revision: str | None = "f3a9c1e7b254"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("group_members") as batch:
        batch.add_column(sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("group_members") as batch:
        batch.drop_column("last_opened_at")
