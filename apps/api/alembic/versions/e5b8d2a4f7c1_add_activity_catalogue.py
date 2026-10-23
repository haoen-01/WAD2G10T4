"""add the user-initiated activity catalogue and dimension preferences

Revision ID: e5b8d2a4f7c1
Revises: d4a7c1f9e2b3
Create Date: 2026-09-06 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5b8d2a4f7c1"
down_revision: str | None = "d4a7c1f9e2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A catalogue, not evidence: no run_id/person_id, and nothing here is append-only. Every
    # column mirrors a field on `ActivityCandidate` -- see `db_models.ActivityCandidateRow`.
    op.create_table(
        "activity_candidates",
        sa.Column("activity_id", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("integration_status", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("provider", sa.String(length=160), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location_name", sa.String(length=200), nullable=False),
        sa.Column("location_address", sa.String(length=300), nullable=True),
        sa.Column("location_latitude", sa.Float(), nullable=True),
        sa.Column("location_longitude", sa.Float(), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("indoor_outdoor", sa.String(length=20), nullable=False),
        sa.Column("social_shape", sa.String(length=20), nullable=True),
        sa.Column("intensity", sa.String(length=20), nullable=True),
        sa.Column("accessibility_tags_json", sa.JSON(), nullable=False),
        sa.Column("language_tags_json", sa.JSON(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("availability", sa.String(length=20), nullable=False),
        sa.Column("price", sa.String(length=80), nullable=True),
        sa.Column("source_url", sa.String(length=300), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("activity_id"),
    )

    # Person-scoped and, like `candidate_preferences`, deliberately not append-only: this is a
    # live belief about a *kind* of activity that is expected to move as more declines arrive,
    # not a record of something that happened. `(person_id, dimension, value)` is unique -- the
    # current belief about "outdoor" is one row, replaced in place.
    op.create_table(
        "activity_dimension_preferences",
        sa.Column("preference_id", sa.String(length=64), nullable=False),
        sa.Column("person_id", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=160), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("observations", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["people.person_id"]),
        sa.PrimaryKeyConstraint("preference_id"),
        sa.UniqueConstraint(
            "person_id", "dimension", "value", name="uq_activity_dimension_person_value"
        ),
    )
    op.create_index(
        op.f("ix_activity_dimension_preferences_person_id"),
        "activity_dimension_preferences",
        ["person_id"],
        unique=False,
    )
    # RLS enablement and the anon/authenticated deny posture for these tables are
    # Supabase-platform-specific and live exclusively in the hand-applied SQL mirror at
    # infra/supabase/migrations/202609060007_activity_catalogue.sql, matching every other
    # table in this repo (see infra/supabase/migrations/).


def downgrade() -> None:
    op.drop_index(
        op.f("ix_activity_dimension_preferences_person_id"),
        table_name="activity_dimension_preferences",
    )
    op.drop_table("activity_dimension_preferences")
    op.drop_table("activity_candidates")
