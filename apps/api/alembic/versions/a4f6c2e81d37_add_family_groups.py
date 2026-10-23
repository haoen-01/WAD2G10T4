"""add family groups: accounts, care groups, members, PINs and PIN attempts

Revision ID: a4f6c2e81d37
Revises: 7c3e9a1f4b28
Create Date: 2026-10-14

Care+ now serves family members caring for a senior. A family member creates a group for a
senior with the PIN the senior shows on their own screen, or joins one with the group's join PIN
and waits for an existing member's approval. See `silverloop.family_groups`.

All five tables are new, so the downgrade simply drops them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4f6c2e81d37"
down_revision: str | None = "7c3e9a1f4b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("sub", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("sub"),
    )
    op.create_table(
        "care_groups",
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("linked_via", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("group_id"),
        sa.UniqueConstraint("person_id"),
    )
    op.create_table(
        "group_members",
        sa.Column("member_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("sub", sa.String(length=128), nullable=False),
        sa.Column("relationship", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.PrimaryKeyConstraint("member_id"),
        sa.UniqueConstraint("group_id", "sub", name="uq_group_members_group_sub"),
    )
    op.create_index(op.f("ix_group_members_group_id"), "group_members", ["group_id"])
    op.create_index(op.f("ix_group_members_sub"), "group_members", ["sub"])
    op.create_table(
        "family_pins",
        sa.Column("pin_id", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("pin_hash", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=True),
        sa.Column("group_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.ForeignKeyConstraint(["group_id"], ["care_groups.group_id"]),
        sa.PrimaryKeyConstraint("pin_id"),
        sa.UniqueConstraint("purpose", "pin_hash", name="uq_family_pins_purpose_hash"),
    )
    op.create_index(op.f("ix_family_pins_person_id"), "family_pins", ["person_id"])
    op.create_index(op.f("ix_family_pins_group_id"), "family_pins", ["group_id"])
    op.create_table(
        "pin_attempts",
        sa.Column("attempt_id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("sub", sa.String(length=128), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("attempt_id"),
    )
    op.create_index("ix_pin_attempts_sub_at", "pin_attempts", ["sub", "attempted_at"])
    # RLS and the anon/authenticated deny posture live in the hand-applied mirror
    # infra/supabase/migrations/202610140021_family_groups.sql, like every other table.


def downgrade() -> None:
    op.drop_index("ix_pin_attempts_sub_at", table_name="pin_attempts")
    op.drop_table("pin_attempts")
    op.drop_index(op.f("ix_family_pins_group_id"), table_name="family_pins")
    op.drop_index(op.f("ix_family_pins_person_id"), table_name="family_pins")
    op.drop_table("family_pins")
    op.drop_index(op.f("ix_group_members_sub"), table_name="group_members")
    op.drop_index(op.f("ix_group_members_group_id"), table_name="group_members")
    op.drop_table("group_members")
    op.drop_table("care_groups")
    op.drop_table("accounts")
