"""The family-group tables (Alembic `a4f6c2e81d37`), the family calendar (`b9d3e5f71a26`), the
family activity feed (`c4a7e1b93d58`) and appointment notes (`d8e2b6a4c917`), stepped through the
real Alembic chain."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from silverloop.schema_revision import expected_database_revision
from silverloop.sql_repository import _sync_database_url

_PREVIOUS_REVISION = "7c3e9a1f4b28"
_FAMILY_REVISION = "a4f6c2e81d37"
_CALENDAR_REVISION = "b9d3e5f71a26"
_ACTIVITY_REVISION = "c4a7e1b93d58"
_NOTES_REVISION = "d8e2b6a4c917"
_API_ROOT = Path(__file__).resolve().parents[1]
_TABLES = {"accounts", "care_groups", "group_members", "family_pins", "pin_attempts"}
_CALENDAR_TABLES = {"appointments", "availability_entries", "helper_assignments"}
_ACTIVITY_TABLES = {"family_activity"}
_NOTES_TABLES = {"appointment_notes"}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    return config


def _tables(database_url: str) -> set[str]:
    engine = create_engine(_sync_database_url(database_url))
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_the_notes_revision_is_the_repository_head() -> None:
    assert expected_database_revision() == _NOTES_REVISION


def test_upgrade_creates_the_family_tables_and_downgrade_removes_them(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'family.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, _PREVIOUS_REVISION)
    assert not _TABLES & _tables(database_url)

    command.upgrade(config, _FAMILY_REVISION)
    assert _tables(database_url) >= _TABLES

    command.upgrade(config, _CALENDAR_REVISION)
    assert _tables(database_url) >= _CALENDAR_TABLES
    assert not _ACTIVITY_TABLES & _tables(database_url)

    command.upgrade(config, _ACTIVITY_REVISION)
    assert _tables(database_url) >= _ACTIVITY_TABLES
    assert not _NOTES_TABLES & _tables(database_url)

    command.upgrade(config, _NOTES_REVISION)
    assert _tables(database_url) >= _NOTES_TABLES | _ACTIVITY_TABLES

    command.downgrade(config, _ACTIVITY_REVISION)
    assert not _NOTES_TABLES & _tables(database_url)
    assert _tables(database_url) >= _ACTIVITY_TABLES

    command.downgrade(config, _CALENDAR_REVISION)
    assert not _ACTIVITY_TABLES & _tables(database_url)
    assert _tables(database_url) >= _CALENDAR_TABLES

    command.downgrade(config, _FAMILY_REVISION)
    assert not _CALENDAR_TABLES & _tables(database_url)
    command.downgrade(config, _PREVIOUS_REVISION)
    assert not _TABLES & _tables(database_url)
