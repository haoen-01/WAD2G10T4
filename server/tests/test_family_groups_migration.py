"""The family-group tables (Alembic `a4f6c2e81d37`), the family calendar (`b9d3e5f71a26`), the
family activity feed (`c4a7e1b93d58`), appointment notes (`d8e2b6a4c917`), groups with no senior
linked yet (`f3a9c1e7b254`), each member's last opened group (`c1e5a8f2d640`), tasks
(`a7d4c2e9f1b3`) and asks with their notifications (`e6b2d9a4c718`), stepped through the real
Alembic chain."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from silverloop.schema_revision import expected_database_revision
from silverloop.sql_repository import _sync_database_url

_PREVIOUS_REVISION = "7c3e9a1f4b28"
_FAMILY_REVISION = "a4f6c2e81d37"
_CALENDAR_REVISION = "b9d3e5f71a26"
_ACTIVITY_REVISION = "c4a7e1b93d58"
_NOTES_REVISION = "d8e2b6a4c917"
_UNLINKED_REVISION = "f3a9c1e7b254"
_LAST_OPENED_REVISION = "c1e5a8f2d640"
_TASKS_REVISION = "a7d4c2e9f1b3"
_ASKS_REVISION = "e6b2d9a4c718"
_API_ROOT = Path(__file__).resolve().parents[1]
_TABLES = {"accounts", "care_groups", "group_members", "family_pins", "pin_attempts"}
_CALENDAR_TABLES = {"appointments", "availability_entries", "helper_assignments"}
_ACTIVITY_TABLES = {"family_activity"}
_NOTES_TABLES = {"appointment_notes"}
_TASK_TABLES = {"tasks", "task_ticks"}
_ASK_TABLES = {"helper_asks", "notifications"}


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


def test_the_asks_revision_is_the_repository_head() -> None:
    assert expected_database_revision() == _ASKS_REVISION


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

    command.upgrade(config, _UNLINKED_REVISION)
    assert {"senior_name", "linked_at", "linked_by"} <= _care_group_columns(database_url)
    assert not _TASK_TABLES & _tables(database_url)

    command.upgrade(config, _TASKS_REVISION)
    assert _tables(database_url) >= _TASK_TABLES
    assert not _ASK_TABLES & _tables(database_url)

    command.upgrade(config, _ASKS_REVISION)
    assert _tables(database_url) >= _ASK_TABLES
    command.downgrade(config, _TASKS_REVISION)
    assert not _ASK_TABLES & _tables(database_url)
    assert _tables(database_url) >= _TASK_TABLES

    command.downgrade(config, _UNLINKED_REVISION)
    assert not _TASK_TABLES & _tables(database_url)

    command.downgrade(config, _NOTES_REVISION)
    assert not {"senior_name", "linked_at", "linked_by"} & _care_group_columns(database_url)

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


def _care_group_columns(database_url: str) -> set[str]:
    engine = create_engine(_sync_database_url(database_url))
    try:
        return {column["name"] for column in inspect(engine).get_columns("care_groups")}
    finally:
        engine.dispose()


_CREATED = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _seed_linked_group(database_url: str) -> None:
    """One senior with a long name and their family group, as the schema before `f3a9c1e7b254`
    held it."""
    engine = create_engine(_sync_database_url(database_url))
    try:
        with engine.begin() as connection:
            # A synthetic senior whose name is longer than `senior_name` holds.
            connection.execute(
                text(
                    "INSERT INTO people (person_id, display_name, preferred_language, created_at) "
                    "VALUES ('person-old', :name, 'en', :at)"
                ),
                {"name": "Mdm " + "Tan" * 40, "at": _CREATED},
            )
            connection.execute(
                text(
                    "INSERT INTO care_groups (group_id, person_id, linked_via, created_by, "
                    "created_at) VALUES ('grp_old', 'person-old', 'senior_link_pin', "
                    "'family-old', :at)"
                ),
                {"at": _CREATED},
            )
    finally:
        engine.dispose()


def test_upgrade_backfills_existing_groups_and_keeps_them_linked(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'backfill.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, _NOTES_REVISION)
    _seed_linked_group(database_url)

    command.upgrade(config, _UNLINKED_REVISION)
    engine = create_engine(_sync_database_url(database_url))
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT person_id, senior_name, linked_via, linked_at, linked_by "
                    "FROM care_groups WHERE group_id = 'grp_old'"
                )
            ).one()
        assert row.person_id == "person-old"
        assert row.senior_name == ("Mdm " + "Tan" * 40)[:80]
        assert row.linked_via == "senior_link_pin"
        assert row.linked_at is not None
        assert row.linked_by == "family-old"

        columns = {c["name"]: c for c in inspect(engine).get_columns("care_groups")}
        assert columns["person_id"]["nullable"] is True
        assert columns["senior_name"]["nullable"] is False
        assert columns["linked_via"]["nullable"] is True
        # The SQLite rebuild keeps the (unnamed) UNIQUE on person_id.
        uniques = inspect(engine).get_unique_constraints("care_groups")
        assert ["person_id"] in [u["column_names"] for u in uniques]
    finally:
        engine.dispose()


def test_after_the_upgrade_a_senior_still_has_one_group_but_many_groups_can_have_none(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'unique.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, _NOTES_REVISION)
    _seed_linked_group(database_url)
    command.upgrade(config, _UNLINKED_REVISION)
    engine = create_engine(_sync_database_url(database_url))
    insert = text(
        "INSERT INTO care_groups (group_id, person_id, senior_name, created_by, created_at) "
        "VALUES (:group_id, :person_id, 'Mdm Lee', 'family-new', :at)"
    )
    try:
        with engine.begin() as connection:
            for group_id in ("grp_a", "grp_b"):
                connection.execute(
                    insert, {"group_id": group_id, "person_id": None, "at": _CREATED}
                )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert, {"group_id": "grp_c", "person_id": "person-old", "at": _CREATED}
            )
    finally:
        engine.dispose()

    # The old schema cannot hold a group with no senior, so the downgrade says so.
    with pytest.raises(RuntimeError, match="no senior linked"):
        command.downgrade(config, _NOTES_REVISION)


def _group_member_columns(database_url: str) -> dict[str, dict]:
    engine = create_engine(_sync_database_url(database_url))
    try:
        return {c["name"]: c for c in inspect(engine).get_columns("group_members")}
    finally:
        engine.dispose()


def test_last_opened_upgrades_with_existing_members_empty_and_downgrades_keeping_them(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'last_opened.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, _NOTES_REVISION)
    _seed_linked_group(database_url)
    command.upgrade(config, _UNLINKED_REVISION)
    assert "last_opened_at" not in _group_member_columns(database_url)
    engine = create_engine(_sync_database_url(database_url))
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO group_members (member_id, group_id, sub, relationship, role, "
                    "status, created_at) VALUES ('mem_old', 'grp_old', 'family-old', 'Son', "
                    "'owner', 'active', :at)"
                ),
                {"at": _CREATED},
            )

        command.upgrade(config, _LAST_OPENED_REVISION)
        column = _group_member_columns(database_url)["last_opened_at"]
        assert column["nullable"] is True
        with engine.connect() as connection:
            opened = connection.execute(
                text("SELECT last_opened_at FROM group_members WHERE member_id = 'mem_old'")
            ).scalar_one()
        assert opened is None

        command.downgrade(config, _UNLINKED_REVISION)
        assert "last_opened_at" not in _group_member_columns(database_url)
        with engine.connect() as connection:
            members = connection.execute(text("SELECT member_id FROM group_members")).scalars()
            assert list(members) == ["mem_old"]
    finally:
        engine.dispose()


def test_the_asks_revision_allows_one_open_ask_per_appointment_day(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'asks.db'}"
    config = _alembic_config(database_url)
    command.upgrade(config, _NOTES_REVISION)
    _seed_linked_group(database_url)
    command.upgrade(config, _ASKS_REVISION)
    engine = create_engine(_sync_database_url(database_url))
    insert = text(
        "INSERT INTO helper_asks (ask_id, group_id, appointment_id, appointment_title, on_date, "
        "asker_member_id, asked_member_id, state, created_at) VALUES (:ask_id, 'grp_old', "
        "'appt_1', 'Physio', '2026-11-12', 'mem_a', 'mem_b', :state, :at)"
    )
    try:
        with engine.begin() as connection:
            for member_id in ("mem_a", "mem_b"):
                connection.execute(
                    text(
                        "INSERT INTO group_members (member_id, group_id, sub, relationship, "
                        "role, status, created_at) VALUES (:member_id, 'grp_old', :member_id, "
                        "'Son', 'member', 'active', :at)"
                    ),
                    {"member_id": member_id, "at": _CREATED},
                )
            # Ended asks for the same day do not count.
            for ask_id, state in (("ask_1", "declined"), ("ask_2", "lapsed"), ("ask_3", "open")):
                connection.execute(insert, {"ask_id": ask_id, "state": state, "at": _CREATED})
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(insert, {"ask_id": "ask_4", "state": "open", "at": _CREATED})
    finally:
        engine.dispose()
