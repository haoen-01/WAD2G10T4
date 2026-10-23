"""add ingestion confidence

Revision ID: 9f1a6c02d4e8
Revises: 3c430fbc9737
Create Date: 2026-08-20 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9f1a6c02d4e8"
down_revision: str | None = "3c430fbc9737"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_metrics",
        sa.Column(
            "ingestion_confidence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("1.0"),
        ),
    )


def downgrade() -> None:
    with op.batch_alter_table("daily_metrics") as batch_op:
        batch_op.drop_column("ingestion_confidence")
