"""Labelling the catalogue on rows that predate the taxonomy (Alembic `d81c4b0f6a27`).

Two properties need a migration-level test rather than an ORM-level one, because both are about
what happens to data that already exists:

1. `distance_basis` stops being inferred from `distance_m is None` and becomes a stored column.
   The inference was only ever correct while exactly one basis existed, so the revision has to
   carry every existing row across to the stored form *without changing what any of them means* --
   otherwise the fix to a future lie is a lie today.
2. The three ontology columns and the two provenance columns arrive `NULL` on every pre-existing
   row and must stay that way. "Unlabelled" and `ActivityType.OTHER` are different facts, and a
   backfill that guessed a type from a title would put a fact into the catalogue that nobody
   asserted -- precisely what hand-authored fixture labels exist to prevent.

Steps through the real Alembic chain rather than building the schema from ORM metadata, for the
same reason `test_dimension_preference_run_scope_migration.py` does: the property under test is
what the migration's own SQL does to rows that are already there.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from silverloop.sql_repository import _sync_database_url

_PRE_ONTOLOGY_REVISION = "a1d5f3b87c46"
_REVISION = "d81c4b0f6a27"
_API_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    return config


def _backfill_sql() -> str:
    """The migration's own backfill statement, loaded from the versioned file by path rather than
    a dotted import -- `alembic/versions` is not a regular importable package -- so this test
    exercises the exact SQL the migration runs, not a copy that could drift from it."""
    path = (
        _API_ROOT / "alembic" / "versions" / f"{_REVISION}_add_activity_ontology_and_provenance.py"
    )
    spec = importlib.util.spec_from_file_location(f"_{_REVISION}_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._BACKFILL_DISTANCE_BASIS_SQL


def _insert_listing(connection, activity_id: str, distance_m: int | None) -> None:
    connection.execute(
        text(
            "insert into activity_candidates "
            "(activity_id, source, integration_status, title, provider, location_name, "
            "category, indoor_outdoor, availability, booking, retrieved_at, distance_m, "
            "accessibility_tags_json, language_tags_json) "
            "values (:a, 'aac_fixture', 'fixture', 'Legacy Listing', 'Legacy Centre', "
            "'Legacy Hall', 'Group class', 'indoor', 'available', 'drop_in', :now, :d, "
            "'[]', '[]')"
        ),
        {"a": activity_id, "now": datetime.now(UTC).isoformat(), "d": distance_m},
    )


@pytest.fixture
def pre_ontology_db(tmp_path: Path) -> str:
    """A SQLite database migrated to the revision immediately before the taxonomy, holding one
    listing with a distance and one without -- the two cases the old inference told apart."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pre-ontology.db'}"
    command.upgrade(_alembic_config(database_url), _PRE_ONTOLOGY_REVISION)

    engine = create_engine(_sync_database_url(database_url))
    with engine.begin() as connection:
        _insert_listing(connection, "activity-legacy-measured", 1200)
        _insert_listing(connection, "activity-legacy-unmeasured", None)
    engine.dispose()
    return database_url


def _rows(database_url: str) -> dict[str, dict[str, object]]:
    engine = create_engine(_sync_database_url(database_url))
    with engine.connect() as connection:
        rows = {
            row.activity_id: dict(row._mapping)
            for row in connection.execute(
                text(
                    "select activity_id, distance_m, distance_basis, activity_type, "
                    "activity_families_json, format, metadata_source, last_verified_at "
                    "from activity_candidates"
                )
            )
        }
    engine.dispose()
    return rows


def test_distance_basis_is_backfilled_to_exactly_what_the_reader_used_to_infer(
    pre_ontology_db: str,
) -> None:
    command.upgrade(_alembic_config(pre_ontology_db), _REVISION)

    rows = _rows(pre_ontology_db)
    assert rows["activity-legacy-measured"]["distance_basis"] == "listing_static"
    assert rows["activity-legacy-unmeasured"]["distance_basis"] == "unknown"


def test_the_taxonomy_and_provenance_columns_arrive_empty_rather_than_guessed(
    pre_ontology_db: str,
) -> None:
    """A title reading "Legacy Listing" names no activity, and even one that did must not be read
    into the catalogue by a migration: the hand-authored label is the authority, and an inferred
    one would be a fact nobody asserted."""
    command.upgrade(_alembic_config(pre_ontology_db), _REVISION)

    for row in _rows(pre_ontology_db).values():
        assert row["activity_type"] is None
        assert row["activity_families_json"] is None
        assert row["format"] is None
        assert row["metadata_source"] is None
        assert row["last_verified_at"] is None


def test_the_backfill_is_idempotent_on_a_second_pass(pre_ontology_db: str) -> None:
    """Alembic never re-runs a completed migration against the same database, but the mirror
    applies the same statement by hand against a database the API may already have upgraded. It
    only ever touches rows still `NULL`, so a second pass is a no-op."""
    command.upgrade(_alembic_config(pre_ontology_db), _REVISION)

    engine = create_engine(_sync_database_url(pre_ontology_db))
    with engine.begin() as connection:
        connection.execute(text("update activity_candidates set distance_m = null"))
        connection.execute(text(_backfill_sql()))
    engine.dispose()

    rows = _rows(pre_ontology_db)
    # Not re-derived from the (now cleared) distance: the stored basis is the record.
    assert rows["activity-legacy-measured"]["distance_basis"] == "listing_static"
    assert rows["activity-legacy-unmeasured"]["distance_basis"] == "unknown"


def test_downgrade_removes_every_column_the_revision_added(pre_ontology_db: str) -> None:
    config = _alembic_config(pre_ontology_db)
    command.upgrade(config, _REVISION)
    command.downgrade(config, _PRE_ONTOLOGY_REVISION)

    engine = create_engine(_sync_database_url(pre_ontology_db))
    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(text("pragma table_info(activity_candidates)"))
        }
        remaining = connection.execute(
            text("select count(*) from activity_candidates")
        ).scalar_one()
    engine.dispose()

    assert remaining == 2, "a downgrade must not take the catalogue with it"
    assert columns.isdisjoint(
        {
            "activity_type",
            "activity_families_json",
            "format",
            "metadata_source",
            "last_verified_at",
            "distance_basis",
        }
    )
