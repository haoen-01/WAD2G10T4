"""The replan offer store (Alembic `b6c1f4d92a37`).

Replanning used to be a read view: a notice was recomputed on every read, the person's answer was
never modelled server-side, and the plan that could no longer happen stayed on the week (audit F
finding 8, reproduced in `docs/audits/personalisation-v2/review-eval-sec.md` R7). `replan_offers`
is the row that makes the offer, and its answer, a fact -- and `week_plan_entries.replaced_by_plan_
id` is the link from the plan that was dropped to the one that took its place.

This module steps through the real Alembic chain rather than building the schema from ORM
metadata, because the property under test is what the migration does to a database that already
has plans in it: the new table and column have to arrive without disturbing them, and the
downgrade has to remove both.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import command
from silverloop.sql_repository import _sync_database_url

_PRE_OFFERS_REVISION = "d81c4b0f6a27"
_OFFERS_REVISION = "b6c1f4d92a37"
_API_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    return config


def _insert_offer(connection: Connection) -> None:
    connection.execute(
        text(
            "insert into replan_offers "
            "(offer_id, run_id, person_id, plan_id, reason, alternative_activity_id, "
            "offered_at, resolved_at, resolution) "
            "values ('offer-1', 'run-live', 'legacy-person', 'plan-live', 'full', "
            "'activity-1', :now, null, null)"
        ),
        {"now": datetime.now(UTC).isoformat()},
    )


@pytest.fixture
def pre_offers_db(tmp_path: Path) -> str:
    """A SQLite database migrated to the revision immediately before the offer store, with one
    person, one run, one listing and one plan already on it."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pre-offers.db'}"
    command.upgrade(_alembic_config(database_url), _PRE_OFFERS_REVISION)

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
        connection.execute(
            text(
                "insert into scenario_runs "
                "(run_id, person_id, seed, scenario_version, current_day, active, started_at) "
                "values ('run-live', 'legacy-person', 1, 'v1', '2026-01-01', 1, :now)"
            ),
            {"now": now},
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
        connection.execute(
            text(
                "insert into week_plan_entries "
                "(plan_id, run_id, person_id, day, activity_id, origin, created_at) "
                "values ('plan-live', 'run-live', 'legacy-person', '2026-01-02', 'activity-1', "
                "'chosen', :now)"
            ),
            {"now": now},
        )
    engine.dispose()
    return database_url


def test_an_offer_cannot_be_recorded_before_the_migration(pre_offers_db: str) -> None:
    """The gap the revision closes, pinned against the *old* schema so the test below is not
    proving something that was never missing."""
    engine = create_engine(_sync_database_url(pre_offers_db))
    try:
        with pytest.raises(OperationalError), engine.begin() as connection:
            _insert_offer(connection)
    finally:
        engine.dispose()


def test_the_migration_adds_the_offer_store_without_disturbing_existing_plans(
    pre_offers_db: str,
) -> None:
    command.upgrade(_alembic_config(pre_offers_db), _OFFERS_REVISION)

    engine = create_engine(_sync_database_url(pre_offers_db))
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("week_plan_entries")}
        assert "replaced_by_plan_id" in columns

        with engine.begin() as connection:
            # The plan that was there before the migration is still there, untouched, and its
            # new column is null rather than guessed at.
            assert (
                connection.execute(
                    text(
                        "select replaced_by_plan_id from week_plan_entries "
                        "where plan_id = 'plan-live'"
                    )
                ).scalar_one()
                is None
            )
            _insert_offer(connection)
            # An offer is resolved in place -- accepted, declined or expired -- so unlike the
            # evidence tables this one carries no append-only trigger and this update must work.
            connection.execute(
                text(
                    "update replan_offers set resolution = 'accepted', resolved_at = :now "
                    "where offer_id = 'offer-1'"
                ),
                {"now": datetime.now(UTC).isoformat()},
            )
            assert (
                connection.execute(
                    text("select resolution from replan_offers where offer_id = 'offer-1'")
                ).scalar_one()
                == "accepted"
            )
    finally:
        engine.dispose()


def test_the_downgrade_removes_the_offer_store_and_the_link(pre_offers_db: str) -> None:
    """A downgrade must leave the older schema genuinely back, not merely reachable."""
    config = _alembic_config(pre_offers_db)
    command.upgrade(config, _OFFERS_REVISION)
    command.downgrade(config, _PRE_OFFERS_REVISION)

    engine = create_engine(_sync_database_url(pre_offers_db))
    try:
        inspector = inspect(engine)
        assert "replan_offers" not in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("week_plan_entries")}
        assert "replaced_by_plan_id" not in columns
        # The plan itself survives the round trip.
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("select count(*) from week_plan_entries where plan_id = 'plan-live'")
                ).scalar_one()
                == 1
            )
    finally:
        engine.dispose()
