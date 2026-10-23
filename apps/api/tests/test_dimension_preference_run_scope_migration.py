"""Backfilling `run_id` on rows that predate it (Alembic `c2725d7de5df`).

ADR 0004 (`docs/adr/0004-run-scope-activity-dimension-preferences.md`) replaced a demo reset's
blanket delete of `activity_dimension_preferences` with run-scoping: a row's `run_id = NULL` means
"standing" (survives every reset) only when it is also a `senior_statement` with no `expires_at`.
Every row already in the table before this revision has `run_id = NULL` regardless of what kind of
fact it is, purely because the column did not exist yet -- adding the column with no data step
would silently make every existing inferred belief permanent and let every existing time-boxed
statement keep resurrecting after a reset, which is the exact pair of bugs run-scoping exists to
close. This module pins that the migration itself backfills those rows, stepping through the real
Alembic chain rather than building the schema from ORM metadata, because the property under test is
what the migration's own SQL does to data that already exists.
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

_PRE_BACKFILL_REVISION = "c2f4a8d1e6b7"
_API_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    return config


def _backfill_sql() -> str:
    """The migration's own backfill statement, loaded from the versioned file by path rather
    than a dotted import -- `alembic/versions` is not a regular importable package -- so this
    test exercises the exact SQL the migration runs, not a copy that could drift from it."""
    path = _API_ROOT / "alembic" / "versions" / "c2725d7de5df_add_dimension_preference_run_scope.py"
    spec = importlib.util.spec_from_file_location("_c2725d7de5df_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._BACKFILL_RUN_ID_SQL


@pytest.fixture
def pre_backfill_db(tmp_path: Path) -> str:
    """A SQLite database migrated to the revision immediately before the `run_id` backfill, with
    one row of each shape the backfill has to tell apart already inserted."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pre-backfill.db'}"
    command.upgrade(_alembic_config(database_url), _PRE_BACKFILL_REVISION)

    engine = create_engine(_sync_database_url(database_url))
    now = datetime.now(UTC).isoformat()
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into people (person_id, display_name, preferred_language, created_at) "
                "values (:p, 'Legacy', 'en', :now)"
            ),
            {"p": "legacy-person", "now": now},
        )
        connection.execute(
            text(
                "insert into people (person_id, display_name, preferred_language, created_at) "
                "values (:p, 'No Run', 'en', :now)"
            ),
            {"p": "no-run-person", "now": now},
        )
        connection.execute(
            text(
                "insert into scenario_runs "
                "(run_id, person_id, seed, scenario_version, current_day, active, started_at) "
                "values (:r, :p, 1, 'v1', '2026-01-01', 1, :now)"
            ),
            {"r": "run-active", "p": "legacy-person", "now": now},
        )
        connection.execute(
            text(
                "insert into scenario_runs "
                "(run_id, person_id, seed, scenario_version, current_day, active, started_at) "
                "values (:r, :p, 1, 'v1', '2026-01-01', 0, :now)"
            ),
            {"r": "run-inactive", "p": "legacy-person", "now": now},
        )
        connection.execute(
            text(
                "insert into activity_dimension_preferences "
                "(preference_id, person_id, dimension, value, strength, source, confirmed, "
                "observations, updated_at) "
                "values ('pref-inferred', 'legacy-person', 'distance', 'far', -0.3, "
                "'decline_reason', 0, 1, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "insert into activity_dimension_preferences "
                "(preference_id, person_id, dimension, value, strength, source, confirmed, "
                "observations, updated_at, expires_at) "
                "values ('pref-timeboxed', 'legacy-person', 'category', 'Group class', -1.0, "
                "'senior_statement', 1, 1, :now, '2026-01-05T23:59:00+00:00')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "insert into activity_dimension_preferences "
                "(preference_id, person_id, dimension, value, strength, source, confirmed, "
                "observations, updated_at) "
                "values ('pref-standing', 'legacy-person', 'environment', 'outdoor', -1.0, "
                "'senior_statement', 1, 1, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "insert into activity_dimension_preferences "
                "(preference_id, person_id, dimension, value, strength, source, confirmed, "
                "observations, updated_at) "
                "values ('pref-no-run', 'no-run-person', 'distance', 'far', -0.3, "
                "'decline_reason', 0, 1, :now)"
            ),
            {"now": now},
        )
    engine.dispose()
    return database_url


def test_the_migration_backfills_run_id_on_every_row_the_rule_requires(
    pre_backfill_db: str,
) -> None:
    command.upgrade(_alembic_config(pre_backfill_db), "head")

    engine = create_engine(_sync_database_url(pre_backfill_db))
    with engine.connect() as connection:
        rows = {
            row.preference_id: row.run_id
            for row in connection.execute(
                text("select preference_id, run_id from activity_dimension_preferences")
            )
        }
    engine.dispose()

    # A decline_reason row is never standing: backfilled to the person's active run.
    assert rows["pref-inferred"] == "run-active"
    # A time-boxed senior_statement row (expires_at set) is run-scoped too, for the same reason.
    assert rows["pref-timeboxed"] == "run-active"
    # A standing senior_statement row (no expires_at) is never run-scoped and stays null.
    assert rows["pref-standing"] is None
    # A person with no active scenario run is left null rather than guessing one -- the read
    # path (`_preference_inactive`) already treats a non-standing null row as inactive.
    assert rows["pref-no-run"] is None


def test_the_backfill_is_idempotent_on_a_second_upgrade_attempt(pre_backfill_db: str) -> None:
    """Alembic never re-runs a completed migration against the same database, but the backfill
    statement itself must not corrupt anything if it were ever replayed by hand -- it only
    touches rows still `run_id is null`, so a second pass is a no-op."""
    config = _alembic_config(pre_backfill_db)
    command.upgrade(config, "head")

    engine = create_engine(_sync_database_url(pre_backfill_db))
    with engine.begin() as connection:
        connection.execute(text(_backfill_sql()))
        rows = {
            row.preference_id: row.run_id
            for row in connection.execute(
                text("select preference_id, run_id from activity_dimension_preferences")
            )
        }
    engine.dispose()

    assert rows["pref-inferred"] == "run-active"
    assert rows["pref-timeboxed"] == "run-active"
    assert rows["pref-standing"] is None
    assert rows["pref-no-run"] is None


def test_a_stray_second_active_run_backfills_to_the_newest_one(pre_backfill_db: str) -> None:
    """Nothing in the schema enforces one active run per person; only `reset()` does. On
    PostgreSQL a second active run would make an unordered scalar subquery raise and abort the
    whole migration, so the backfill picks the most recently started active run instead."""
    engine = create_engine(_sync_database_url(pre_backfill_db))
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into scenario_runs "
                "(run_id, person_id, seed, scenario_version, current_day, active, started_at) "
                "values ('run-newer', 'legacy-person', 1, 'v1', '2026-01-01', 1, :later)"
            ),
            {"later": "2099-01-01T00:00:00+00:00"},
        )
    engine.dispose()

    command.upgrade(_alembic_config(pre_backfill_db), "head")

    engine = create_engine(_sync_database_url(pre_backfill_db))
    with engine.connect() as connection:
        run_id = connection.execute(
            text("select run_id from activity_dimension_preferences where preference_id = :p"),
            {"p": "pref-inferred"},
        ).scalar_one()
    engine.dispose()

    assert run_id == "run-newer"
