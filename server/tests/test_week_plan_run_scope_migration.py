"""Moving the week-plan uniqueness key onto the run (Alembic `a1d5f3b87c46`).

`week_plan_entries` always carried `run_id`, but `(person_id, day, activity_id)` was unique across
every run. A demo reset rewinds the simulated calendar to the fixture's anchor day, so once a dead
run held a person's choice for a day, the live run could not record the same choice at all -- the
database rejected the insert and "add to my week" failed for a week that showed nothing (audit I
finding 1). This module steps through the real Alembic chain rather than building the schema from
ORM metadata, because the property under test is what the migration does to a table that already
has rows in it: the key has to widen without disturbing them, and the downgrade has to narrow
again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from silverloop.sql_repository import _sync_database_url

_PRE_SWAP_REVISION = "c2725d7de5df"
_SWAP_REVISION = "a1d5f3b87c46"
_API_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    return config


def _insert_plan(connection: Connection, plan_id: str, run_id: str) -> None:
    """One week-plan row for the shared `(person, day, activity)` the two runs both chose."""
    connection.execute(
        text(
            "insert into week_plan_entries "
            "(plan_id, run_id, person_id, day, activity_id, origin, created_at) "
            "values (:plan_id, :run_id, 'legacy-person', '2026-01-02', 'activity-1', "
            "'chosen', :now)"
        ),
        {"plan_id": plan_id, "run_id": run_id, "now": datetime.now(UTC).isoformat()},
    )


@pytest.fixture
def pre_swap_db(tmp_path: Path) -> str:
    """A SQLite database migrated to the revision immediately before the key swap, with one
    person, two runs (one dead, one live), one listing and one plan already on the dead run."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pre-swap.db'}"
    command.upgrade(_alembic_config(database_url), _PRE_SWAP_REVISION)

    engine = create_engine(_sync_database_url(database_url))
    now = datetime.now(UTC).isoformat()
    with engine.begin() as connection:
        connection.execute(
            text(
                "insert into people (person_id, display_name, preferred_language, created_at) "
                "values ('legacy-person', 'Legacy', 'en', :now)"
            ),
            {"now": now},
        )
        for run_id, active in (("run-dead", 0), ("run-live", 1)):
            connection.execute(
                text(
                    "insert into scenario_runs "
                    "(run_id, person_id, seed, scenario_version, current_day, active, started_at) "
                    "values (:run_id, 'legacy-person', 1, 'v1', '2026-01-01', :active, :now)"
                ),
                {"run_id": run_id, "active": active, "now": now},
            )
        connection.execute(
            text(
                "insert into activity_candidates "
                "(activity_id, source, integration_status, title, provider, location_name, "
                "indoor_outdoor, availability, retrieved_at, accessibility_tags_json, "
                "language_tags_json) "
                "values ('activity-1', 'synthetic_fixture', 'fixture', 'Morning walk', 'AAC', "
                "'Park', 'outdoor', 'available', :now, '[]', '[]')"
            ),
            {"now": now},
        )
        _insert_plan(connection, "plan-dead", "run-dead")
    engine.dispose()
    return database_url


def test_the_old_key_makes_the_same_choice_unrepeatable_in_a_later_run(pre_swap_db: str) -> None:
    """The bug the swap exists to close, pinned against the *old* schema so the fix below is not
    proving something that was never broken."""
    engine = create_engine(_sync_database_url(pre_swap_db))
    try:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_plan(connection, "plan-live", "run-live")
    finally:
        engine.dispose()


def test_the_migration_widens_the_key_to_the_run_without_disturbing_existing_rows(
    pre_swap_db: str,
) -> None:
    command.upgrade(_alembic_config(pre_swap_db), _SWAP_REVISION)

    engine = create_engine(_sync_database_url(pre_swap_db))
    try:
        with engine.begin() as connection:
            # The row that was there before the migration is still there, unchanged.
            assert (
                connection.execute(
                    text("select run_id from week_plan_entries where plan_id = 'plan-dead'")
                ).scalar_one()
                == "run-dead"
            )
            # The live run may now record the same choice...
            _insert_plan(connection, "plan-live", "run-live")

        # ...but a second copy of it *within one run* is still a database error, which is what
        # the key is for (`_plan_activity_in_session` returns the existing row instead).
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_plan(connection, "plan-live-again", "run-live")
    finally:
        engine.dispose()


def test_the_downgrade_narrows_the_key_back(pre_swap_db: str) -> None:
    """A downgrade must leave the older schema genuinely enforced again, not merely reachable."""
    config = _alembic_config(pre_swap_db)
    command.upgrade(config, _SWAP_REVISION)
    command.downgrade(config, _PRE_SWAP_REVISION)

    engine = create_engine(_sync_database_url(pre_swap_db))
    try:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_plan(connection, "plan-live", "run-live")
    finally:
        engine.dispose()
