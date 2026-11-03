"""a family group can exist before its senior is linked

Revision ID: f3a9c1e7b254
Revises: d8e2b6a4c917
Create Date: 2026-10-29

ADR 0010: a family member creates the family group with the senior's name, and the senior is linked
later with their senior-link PIN. `care_groups.person_id` becomes nullable (NULL: no senior linked
yet) and stays unique; Postgres and SQLite both allow any number of NULLs under UNIQUE.
`senior_name` holds the name the creator typed (responses show the senior's own account name once
linked), `linked_via` becomes nullable, and `linked_at` / `linked_by` record when and by whom the
senior was linked.

Existing groups are all linked: `senior_name` is backfilled from `people.display_name` (cut to 80),
`linked_at` / `linked_by` from `created_at` / `created_by`. The downgrade refuses while any group
has no senior, since the old schema cannot hold one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a9c1e7b254"
down_revision: str | None = "d8e2b6a4c917"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("care_groups") as batch:
        batch.add_column(sa.Column("senior_name", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("linked_by", sa.String(length=128), nullable=True))
    # Portable correlated subquery: every existing group has a senior.
    op.execute(
        "UPDATE care_groups SET "
        "senior_name = coalesce((SELECT substr(people.display_name, 1, 80) FROM people "
        "WHERE people.person_id = care_groups.person_id), ''), "
        "linked_at = created_at, "
        "linked_by = created_by "
        "WHERE senior_name IS NULL"
    )
    # On SQLite this rebuilds the table; the reflected UNIQUE on `person_id` is carried over
    # (`test_family_groups_migration.py` checks it).
    with op.batch_alter_table("care_groups") as batch:
        batch.alter_column("senior_name", existing_type=sa.String(length=80), nullable=False)
        batch.alter_column("person_id", existing_type=sa.String(length=64), nullable=True)
        batch.alter_column("linked_via", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    unlinked = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM care_groups WHERE person_id IS NULL"))
        .scalar()
    )
    if unlinked:
        raise RuntimeError(
            f"{unlinked} family group(s) have no senior linked; the previous schema needs one. "
            "Link or remove them before downgrading below f3a9c1e7b254."
        )
    op.execute("UPDATE care_groups SET linked_via = 'senior_link_pin' WHERE linked_via IS NULL")
    with op.batch_alter_table("care_groups") as batch:
        batch.alter_column("linked_via", existing_type=sa.String(length=32), nullable=False)
        batch.alter_column("person_id", existing_type=sa.String(length=64), nullable=False)
        batch.drop_column("linked_by")
        batch.drop_column("linked_at")
        batch.drop_column("senior_name")
