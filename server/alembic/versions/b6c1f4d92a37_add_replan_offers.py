"""add the replan offer store and the replaced-by link

Revision ID: b6c1f4d92a37
Revises: a1d5f3b87c46
Create Date: 2026-09-13

Replanning was a read view. `notices_for` recomputed a notice on every request, the person's
answer to it lived only in browser state, the plan that could no longer happen stayed on the week
-- so the senior was later asked "did you get a chance to go?" about a session that had been
cancelled under them -- and nothing anywhere recorded that an offer had been made at all.

`replan_offers` is the row that makes the offer, and its answer, a fact: written by `advance()` in
the same transaction as the change that invalidated the plan, resolved by the person's own
`replace` or `decline`, and counted in `/v1/metrics`. `week_plan_entries.replaced_by_plan_id`
completes the pair `replaced_reason` (already on the table, and until now only ever written as
`None`) was always meant to be half of: why the plan was dropped, and which plan took its place.

Additive in both directions: no existing row is read or rewritten, and every pre-existing plan
keeps `replaced_by_plan_id = NULL`, which is exactly what "never replaced" means. The downgrade
drops the column and the table -- an offer has no older home to be preserved in, and saying so is
more honest than silently keeping orphaned rows around.

Deliberately NOT an append-only evidence table: an offer is resolved in place (accepted, declined,
expired), so the `reject_silverloop_evidence_mutation` trigger the evidence tables carry is not
installed on it. The Supabase mirror
(`infra/supabase/migrations/202609130015_replan_offers.sql`) says the same and adds the RLS deny
posture every new table needs; `infra/supabase/rls_posture_apply.sql` gains `replan_offers` in its
guarded-table array.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6c1f4d92a37"
down_revision: str | None = "d81c4b0f6a27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "replan_offers",
        sa.Column("offer_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("alternative_activity_id", sa.String(length=80), nullable=True),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["week_plan_entries.plan_id"]),
        sa.ForeignKeyConstraint(["alternative_activity_id"], ["activity_candidates.activity_id"]),
        sa.PrimaryKeyConstraint("offer_id"),
    )
    op.create_index("ix_replan_offers_run_id", "replan_offers", ["run_id"])
    op.create_index("ix_replan_offers_person_id", "replan_offers", ["person_id"])
    op.create_index("ix_replan_offers_run_person", "replan_offers", ["run_id", "person_id"])
    op.create_index("ix_replan_offers_plan", "replan_offers", ["plan_id"])

    with op.batch_alter_table("week_plan_entries") as batch:
        batch.add_column(sa.Column("replaced_by_plan_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("week_plan_entries") as batch:
        batch.drop_column("replaced_by_plan_id")

    op.drop_index("ix_replan_offers_plan", table_name="replan_offers")
    op.drop_index("ix_replan_offers_run_person", table_name="replan_offers")
    op.drop_index("ix_replan_offers_person_id", table_name="replan_offers")
    op.drop_index("ix_replan_offers_run_id", table_name="replan_offers")
    op.drop_table("replan_offers")
