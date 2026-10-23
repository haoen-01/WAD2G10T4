"""The optional context-gap category on case reviews (Alembic `7c3e9a1f4b28`).

Steps through the real Alembic chain rather than building the schema from ORM metadata, because
the append-only triggers pinned here live only in migration DDL. Dropping the column makes SQLite's
batch mode rebuild `case_reviews`, and a rebuilt table carries none of its triggers, so the
downgrade must put them back (the bug `e3b7d5c18a42` fixed for its own downgrade).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from alembic import command
from silverloop.schema_revision import expected_database_revision
from silverloop.sql_repository import _sync_database_url

_PREVIOUS_REVISION = "485506d5a415"
_CONTEXT_GAP_REVISION = "7c3e9a1f4b28"
_API_ROOT = Path(__file__).resolve().parents[1]
_CASE_REVIEW_TRIGGERS = {"case_reviews_reject_update", "case_reviews_reject_delete"}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    return config


def _engine(database_url: str) -> Engine:
    return create_engine(_sync_database_url(database_url))


def _case_review_triggers(database_url: str) -> dict[str, str]:
    engine = _engine(database_url)
    try:
        with engine.connect() as connection:
            return {
                row[0]: row[1]
                for row in connection.execute(
                    text(
                        "select name, sql from sqlite_master "
                        "where type = 'trigger' and tbl_name = 'case_reviews'"
                    )
                )
            }
    finally:
        engine.dispose()


def _case_review_columns(database_url: str) -> set[str]:
    engine = _engine(database_url)
    try:
        return {column["name"] for column in inspect(engine).get_columns("case_reviews")}
    finally:
        engine.dispose()


@pytest.fixture
def previous_db(tmp_path: Path) -> str:
    """A SQLite database at the revision before the category, holding one known-context review."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pre-context-gap.db'}"
    command.upgrade(_alembic_config(database_url), _PREVIOUS_REVISION)
    engine = _engine(database_url)
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
                "values ('run-legacy', 'legacy-person', 1, 'v1', '2026-01-04', 1, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "insert into decision_evidence "
                "(evidence_id, run_id, person_id, observed_at, recorded_at, source, "
                "fixture_classification, confidence, policy_version, decision, reasons_json, "
                "input_event, quality_evidence_id) "
                "values ('ev-legacy', 'run-legacy', 'legacy-person', :now, :now, "
                "'synthetic', 'synthetic', 0.95, 'v1.2', 'coordinator_review', '[]', "
                "'activity_declines', 'dq-legacy')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "insert into review_cases "
                "(case_id, run_id, person_id, decision_evidence_id, title, status, priority, "
                "opened_at, summary, evidence_json, recommendation, opened_day, resolution) "
                "values ('case-legacy', 'run-legacy', 'legacy-person', 'ev-legacy', "
                "'Sustained activity decline requires human review', 'resolved', 4, :now, "
                "'Activity is 44% below the personal baseline across 3 days.', '[]', "
                "'Review context and consent.', '2026-01-04', 'coordinator_decision')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "insert into case_reviews "
                "(review_id, case_id, run_id, status, reviewer, note, recorded_at, "
                "human_action, override_reason, reached_too_late) "
                "values ('review-legacy', 'case-legacy', 'run-legacy', 'resolved', "
                "'coordinator', 'Away visiting family.', :now, 'override', 'known_context', 0)"
            ),
            {"now": now},
        )
    engine.dispose()
    return database_url


@pytest.fixture
def reference_triggers(tmp_path: Path) -> dict[str, str]:
    """`case_reviews` trigger DDL of a never-downgraded database built by the same chain."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'reference.db'}"
    command.upgrade(_alembic_config(database_url), _CONTEXT_GAP_REVISION)
    return _case_review_triggers(database_url)


def test_the_revision_is_in_the_repository_chain() -> None:
    # No longer the head: `a4f6c2e81d37` (family groups) follows it; see
    # `test_family_groups_migration.py`.
    assert expected_database_revision() != _CONTEXT_GAP_REVISION
    script = ScriptDirectory.from_config(_alembic_config("sqlite+pysqlite:///:memory:"))
    assert script.get_revision(_CONTEXT_GAP_REVISION) is not None


def test_the_upgrade_adds_the_column_without_inventing_a_category(previous_db: str) -> None:
    command.upgrade(_alembic_config(previous_db), _CONTEXT_GAP_REVISION)

    assert "context_gap_category" in _case_review_columns(previous_db)
    engine = _engine(previous_db)
    try:
        with engine.connect() as connection:
            review = connection.execute(
                text(
                    "select note, override_reason, context_gap_category from case_reviews "
                    "where review_id = 'review-legacy'"
                )
            ).one()
    finally:
        engine.dispose()
    assert review.note == "Away visiting family."
    assert review.override_reason == "known_context"
    # No past reviewer was asked what kind of context it was.
    assert review.context_gap_category is None


@pytest.mark.parametrize(
    "statement",
    [
        "update case_reviews set context_gap_category = 'away'",
        "delete from case_reviews",
    ],
)
def test_case_reviews_stay_append_only_after_the_upgrade(
    previous_db: str, reference_triggers: dict[str, str], statement: str
) -> None:
    command.upgrade(_alembic_config(previous_db), _CONTEXT_GAP_REVISION)
    assert set(reference_triggers) == _CASE_REVIEW_TRIGGERS
    assert _case_review_triggers(previous_db) == reference_triggers

    engine = _engine(previous_db)
    try:
        with engine.begin() as connection, pytest.raises(DatabaseError, match="append-only"):
            connection.execute(text(statement))
    finally:
        engine.dispose()


def test_the_downgrade_drops_the_column_and_keeps_case_reviews_append_only(
    previous_db: str, reference_triggers: dict[str, str]
) -> None:
    config = _alembic_config(previous_db)
    command.upgrade(config, _CONTEXT_GAP_REVISION)
    command.downgrade(config, _PREVIOUS_REVISION)

    assert "context_gap_category" not in _case_review_columns(previous_db)
    assert _case_review_triggers(previous_db) == reference_triggers
    engine = _engine(previous_db)
    try:
        # The review row survives the batch rebuild.
        with engine.connect() as connection:
            assert connection.execute(text("select review_id from case_reviews")).all() == [
                ("review-legacy",)
            ]
        # And the triggers fire, not merely exist.
        for statement in ("update case_reviews set note = 'rewritten'", "delete from case_reviews"):
            with engine.begin() as connection, pytest.raises(DatabaseError, match="append-only"):
                connection.execute(text(statement))
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_round_trips(
    previous_db: str, reference_triggers: dict[str, str]
) -> None:
    config = _alembic_config(previous_db)
    command.upgrade(config, _CONTEXT_GAP_REVISION)
    command.downgrade(config, _PREVIOUS_REVISION)
    command.upgrade(config, _CONTEXT_GAP_REVISION)

    assert "context_gap_category" in _case_review_columns(previous_db)
    assert _case_review_triggers(previous_db) == reference_triggers
