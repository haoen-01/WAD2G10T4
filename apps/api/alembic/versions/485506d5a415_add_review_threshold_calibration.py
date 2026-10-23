"""add the review-threshold calibrator's append-only stores and the reached-too-late mark

Revision ID: 485506d5a415
Revises: d8b1e4f70c2a
Create Date: 2026-09-15

A coordinator's structured false-alarm judgement may now tune, per person and inside fixed bounds,
the point at which SilverLoop asks a human (ADR 0008,
`docs/adr/0008-coordinator-calibrated-review-threshold.md`). Nothing here stores a "current
threshold": the live value is a pure fold over decision rows, so the only schema is two
append-only evidence tables and one nullable column.

`review_threshold_proposals`
    One row per calibrator output -- a proposed change, a considered no-change, or a write-up of a
    revert. `write_up_for_decision_id` is unique (one write-up per revert) and deliberately not a
    foreign key, because `review_threshold_decisions` already references this table.

`review_threshold_decisions`
    Approvals, rejections, reverts, expiries, reconfirmations and checking-period results.
    `proposal_id` and `ends_approval_id` are unique so a proposal is decided once and an approval
    ended once, whichever concurrent writer wins.

`case_reviews.reached_too_late`
    "This should have reached me sooner." Nullable and not backfilled: no past reviewer was asked.

Both tables get the same reject-update/reject-delete triggers as every other evidence table, on
BOTH dialects (`c2f4a8d1e6b7`'s DDL), so the offline SQLite demo keeps the guarantee.

The downgrade drops both tables and the column, and with them every threshold fact recorded while
they existed. Dropping the column makes SQLite's batch mode rebuild `case_reviews`, which loses its
append-only triggers, so the downgrade restores them exactly as `e3b7d5c18a42` does.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "485506d5a415"
down_revision: str | None = "d8b1e4f70c2a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPEND_ONLY = ("review_threshold_proposals", "review_threshold_decisions")


def _append_only_triggers(dialect: str) -> None:
    """Same DDL `3c430fbc9737` and `c2f4a8d1e6b7` install for the other evidence tables."""
    for table in _APPEND_ONLY:
        if dialect == "sqlite":
            op.execute(
                f"CREATE TRIGGER {table}_reject_update BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only evidence cannot be updated'); END"
            )
            op.execute(
                f"CREATE TRIGGER {table}_reject_delete BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'append-only evidence cannot be deleted'); END"
            )
        elif dialect == "postgresql":
            op.execute(
                f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_silverloop_evidence_mutation()"
            )


def upgrade() -> None:
    # SQLite adds a column in place, so the `case_reviews` triggers survive this direction; on
    # PostgreSQL batch mode emits a plain ALTER TABLE ADD COLUMN.
    with op.batch_alter_table("case_reviews") as batch:
        batch.add_column(sa.Column("reached_too_late", sa.Boolean(), nullable=True))

    op.create_table(
        "review_threshold_proposals",
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("output_kind", sa.String(length=20), nullable=False),
        sa.Column("proposer", sa.String(length=20), nullable=False),
        sa.Column("round_id", sa.String(length=64), nullable=True),
        sa.Column("round_index", sa.Integer(), nullable=True),
        sa.Column("previous_severity_pct", sa.Integer(), nullable=False),
        sa.Column("previous_persistence_days", sa.Integer(), nullable=False),
        sa.Column("proposed_severity_pct", sa.Integer(), nullable=True),
        sa.Column("proposed_persistence_days", sa.Integer(), nullable=True),
        sa.Column("cause", sa.String(length=40), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("cited_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("trigger_case_id", sa.String(length=64), nullable=True),
        sa.Column("trigger_review_ids", sa.JSON(), nullable=False),
        sa.Column("reported_by", sa.String(length=120), nullable=True),
        sa.Column("coordinator_reason", sa.String(length=40), nullable=True),
        sa.Column("write_up_for_decision_id", sa.String(length=64), nullable=True),
        sa.Column("agent_run_json", sa.JSON(), nullable=True),
        sa.Column("proposed_on_day", sa.Date(), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.ForeignKeyConstraint(["trigger_case_id"], ["review_cases.case_id"]),
        sa.PrimaryKeyConstraint("proposal_id"),
        sa.UniqueConstraint(
            "write_up_for_decision_id", name="uq_review_threshold_proposals_write_up_for"
        ),
    )
    op.create_index(
        op.f("ix_review_threshold_proposals_run_id"),
        "review_threshold_proposals",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_threshold_proposals_person_id"),
        "review_threshold_proposals",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_threshold_proposals_run_day",
        "review_threshold_proposals",
        ["run_id", "proposed_on_day"],
        unique=False,
    )
    op.create_index(
        "ix_review_threshold_proposals_reporter_at",
        "review_threshold_proposals",
        ["reported_by", "proposed_at"],
        unique=False,
    )

    op.create_table(
        "review_threshold_decisions",
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("proposal_id", sa.String(length=64), nullable=True),
        sa.Column("ends_approval_id", sa.String(length=64), nullable=True),
        sa.Column("affects_decision_id", sa.String(length=64), nullable=True),
        sa.Column("revert_trigger", sa.String(length=30), nullable=True),
        sa.Column("previous_severity_pct", sa.Integer(), nullable=False),
        sa.Column("previous_persistence_days", sa.Integer(), nullable=False),
        sa.Column("severity_pct", sa.Integer(), nullable=True),
        sa.Column("persistence_days", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.String(length=120), nullable=False),
        sa.Column("rejection_reason", sa.String(length=40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("cause_confirmed", sa.Boolean(), nullable=True),
        sa.Column("replay_json", sa.JSON(), nullable=True),
        sa.Column("trigger_case_id", sa.String(length=64), nullable=True),
        sa.Column("trigger_review_id", sa.String(length=64), nullable=True),
        sa.Column("decided_on_day", sa.Date(), nullable=False),
        sa.Column("effective_from_day", sa.Date(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.ForeignKeyConstraint(["proposal_id"], ["review_threshold_proposals.proposal_id"]),
        sa.ForeignKeyConstraint(["ends_approval_id"], ["review_threshold_decisions.decision_id"]),
        sa.ForeignKeyConstraint(
            ["affects_decision_id"], ["review_threshold_decisions.decision_id"]
        ),
        sa.ForeignKeyConstraint(["trigger_case_id"], ["review_cases.case_id"]),
        sa.ForeignKeyConstraint(["trigger_review_id"], ["case_reviews.review_id"]),
        sa.PrimaryKeyConstraint("decision_id"),
        sa.UniqueConstraint("proposal_id", name="uq_review_threshold_decisions_proposal"),
        sa.UniqueConstraint("ends_approval_id", name="uq_review_threshold_decisions_ends_approval"),
    )
    op.create_index(
        op.f("ix_review_threshold_decisions_run_id"),
        "review_threshold_decisions",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_threshold_decisions_person_id"),
        "review_threshold_decisions",
        ["person_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_threshold_decisions_run_effective",
        "review_threshold_decisions",
        ["run_id", "effective_from_day"],
        unique=False,
    )

    _append_only_triggers(op.get_bind().dialect.name)
    # RLS enablement and the anon/authenticated deny posture for these tables are
    # Supabase-platform-specific and live exclusively in the hand-applied SQL mirror at
    # infra/supabase/migrations/202609150019_review_threshold_calibration.sql.


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for table in _APPEND_ONLY:
        if dialect == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_reject_delete")
        elif dialect == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.drop_index(
        "ix_review_threshold_decisions_run_effective", table_name="review_threshold_decisions"
    )
    op.drop_index(
        op.f("ix_review_threshold_decisions_person_id"), table_name="review_threshold_decisions"
    )
    op.drop_index(
        op.f("ix_review_threshold_decisions_run_id"), table_name="review_threshold_decisions"
    )
    op.drop_table("review_threshold_decisions")
    op.drop_index(
        "ix_review_threshold_proposals_reporter_at", table_name="review_threshold_proposals"
    )
    op.drop_index("ix_review_threshold_proposals_run_day", table_name="review_threshold_proposals")
    op.drop_index(
        op.f("ix_review_threshold_proposals_person_id"), table_name="review_threshold_proposals"
    )
    op.drop_index(
        op.f("ix_review_threshold_proposals_run_id"), table_name="review_threshold_proposals"
    )
    op.drop_table("review_threshold_proposals")
    with op.batch_alter_table("case_reviews") as batch:
        batch.drop_column("reached_too_late")
    _restore_sqlite_append_only_triggers("case_reviews")


def _restore_sqlite_append_only_triggers(table: str) -> None:
    """Put back what a batch-mode table rebuild took away -- byte-for-byte `e3b7d5c18a42`'s helper,
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
