"""add simulation event idempotency

Revision ID: b6f42a71e903
Revises: 9f1a6c02d4e8
Create Date: 2026-08-20 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6f42a71e903"
down_revision: str | None = "9f1a6c02d4e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "simulation_events",
        sa.Column("simulation_event_id", sa.String(length=64), nullable=False),
        sa.Column("client_event_id", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("event_name", sa.String(length=80), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["scenario_runs.run_id"]),
        sa.PrimaryKeyConstraint("simulation_event_id"),
        sa.UniqueConstraint("run_id", "client_event_id", name="uq_simulation_event_run_client"),
    )
    op.create_index("ix_simulation_events_run_id", "simulation_events", ["run_id"], unique=False)
    op.create_index(
        "ix_simulation_events_run_recorded",
        "simulation_events",
        ["run_id", "recorded_at"],
        unique=False,
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER simulation_events_reject_update BEFORE UPDATE ON simulation_events "
            "BEGIN SELECT RAISE(ABORT, 'append-only evidence cannot be updated'); END"
        )
        op.execute(
            "CREATE TRIGGER simulation_events_reject_delete BEFORE DELETE ON simulation_events "
            "BEGIN SELECT RAISE(ABORT, 'append-only evidence cannot be deleted'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE TRIGGER simulation_events_append_only "
            "BEFORE UPDATE OR DELETE ON simulation_events FOR EACH ROW "
            "EXECUTE FUNCTION reject_silverloop_evidence_mutation()"
        )


def downgrade() -> None:
    op.drop_index("ix_simulation_events_run_recorded", table_name="simulation_events")
    op.drop_index("ix_simulation_events_run_id", table_name="simulation_events")
    op.drop_table("simulation_events")
