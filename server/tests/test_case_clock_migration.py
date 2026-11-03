"""Adding the case clock and override columns to a database that already holds cases
(Alembic `e3b7d5c18a42`).

The property under test is what the migration's own DDL does to data that already exists, so this
steps through the real Alembic chain rather than building the schema from ORM metadata. Two things
matter and neither is visible from `db_models.py`:

- a case that predates the revision keeps every fact it had, and reports the new ones as "not
  recorded" rather than acquiring a backfilled opening day the simulation never ran;
- the downgrade is real. It is the only way back off a revision applied to a shared database, and
  a migration whose reverse raises is a one-way door nobody tested.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from silverloop.sql_repository import _sync_database_url

_PRE_CASE_CLOCK_REVISION = "b6c1f4d92a37"
_CASE_CLOCK_REVISION = "e3b7d5c18a42"
_API_ROOT = Path(__file__).resolve().parents[1]

_NEW_CASE_COLUMNS = {"opened_day", "resolution"}
_NEW_REVIEW_COLUMNS = {"agent_recommendation", "human_action", "override_reason"}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    return config


@pytest.fixture
def pre_case_clock_db(tmp_path: Path) -> str:
    """A SQLite database at the revision immediately before the case clock, holding one open case
    and one review against it -- the shape a real shared database would be in."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pre-case-clock.db'}"
    command.upgrade(_alembic_config(database_url), _PRE_CASE_CLOCK_REVISION)

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
                "values ('ev-legacy', 'run-legacy', 'legacy-person', :observed, :now, "
                "'synthetic', 'synthetic', 0.95, 'v1.2', 'coordinator_review', '[]', "
                "'activity_declines', 'dq-legacy')"
            ),
            {"observed": "2026-01-04T12:00:00+00:00", "now": now},
        )
        connection.execute(
            text(
                "insert into review_cases "
                "(case_id, run_id, person_id, decision_evidence_id, title, status, priority, "
                "opened_at, summary, evidence_json, recommendation) "
                "values ('case-legacy', 'run-legacy', 'legacy-person', 'ev-legacy', "
                "'Sustained activity decline requires human review', 'open', 4, :now, "
                "'Activity is 56% below the personal baseline across 3 days.', '[]', "
                "'Review context and consent.')"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "insert into case_reviews "
                "(review_id, case_id, run_id, status, reviewer, note, recorded_at) "
                "values ('review-legacy', 'case-legacy', 'run-legacy', 'acknowledged', "
                "'coordinator', 'Picked this up.', :now)"
            ),
            {"now": now},
        )
    engine.dispose()
    return database_url


def test_the_migration_adds_the_columns_without_inventing_values_for_existing_rows(
    pre_case_clock_db: str,
) -> None:
    command.upgrade(_alembic_config(pre_case_clock_db), _CASE_CLOCK_REVISION)

    engine = create_engine(_sync_database_url(pre_case_clock_db))
    inspector = inspect(engine)
    case_columns = {column["name"] for column in inspector.get_columns("review_cases")}
    review_columns = {column["name"] for column in inspector.get_columns("case_reviews")}

    with engine.connect() as connection:
        case = connection.execute(
            text(
                "select status, summary, opened_day, resolution from review_cases "
                "where case_id = 'case-legacy'"
            )
        ).one()
        review = connection.execute(
            text(
                "select status, note, agent_recommendation, human_action, override_reason "
                "from case_reviews where review_id = 'review-legacy'"
            )
        ).one()
    engine.dispose()

    assert case_columns >= _NEW_CASE_COLUMNS
    assert review_columns >= _NEW_REVIEW_COLUMNS
    # Everything the rows already held survives the batch-mode table rebuild SQLite performs.
    assert case.status == "open"
    assert case.summary.startswith("Activity is 56% below")
    assert review.status == "acknowledged"
    assert review.note == "Picked this up."
    # Nothing is guessed. A refresh overwrites `decision_evidence_id`, so the surviving evidence
    # points at the latest day a case saw, not the day it opened -- backfilling `opened_day` from
    # it would state a fact nobody recorded. Likewise no past reviewer chose from an enum that did
    # not exist when they reviewed.
    assert case.opened_day is None
    assert case.resolution is None
    assert (review.agent_recommendation, review.human_action, review.override_reason) == (
        None,
        None,
        None,
    )


_APPEND_ONLY_TRIGGERS = {"case_reviews_reject_update", "case_reviews_reject_delete"}


def _triggers_on(database_url: str, table: str) -> dict[str, str]:
    """`{name: the DDL SQLite stored}` for every trigger on `table`.

    The SQL is compared, not only the name: a trigger that exists under the right name but
    raises a different error -- or none -- would pass a name-only check and protect nothing.
    """
    engine = create_engine(_sync_database_url(database_url))
    with engine.connect() as connection:
        found = {
            row[0]: row[1]
            for row in connection.execute(
                text(
                    "select name, sql from sqlite_master where type = 'trigger' and tbl_name = :t"
                ),
                {"t": table},
            )
        }
    engine.dispose()
    return found


@pytest.fixture
def reference_triggers(tmp_path: Path) -> dict[str, str]:
    """The trigger DDL a database that has never been downgraded carries, built by the same
    Alembic chain -- so the assertion is "identical to the real thing", never a copy of the
    statements that could drift from `3c430fbc9737`'s."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'reference.db'}"
    command.upgrade(_alembic_config(database_url), _CASE_CLOCK_REVISION)
    return _triggers_on(database_url, "case_reviews")


def test_a_downgrade_keeps_the_append_only_triggers_on_case_reviews(
    pre_case_clock_db: str, reference_triggers: dict[str, str]
) -> None:
    """SQLite cannot drop a column in place, so Alembic's batch mode rebuilds the table --
    create, copy, drop, rename -- and a rebuilt table has none of the old one's triggers.
    Nothing else in the chain re-creates them, so a downgrade used to delete the append-only
    guarantee on `case_reviews` permanently: re-upgrading never brought it back, the database
    still reported itself at head, `/ready` still passed, and coordinator-review evidence could
    be UPDATEd and DELETEd in silence.

    The upgrade direction is unaffected (SQLite adds a column in place), which is exactly why
    this went unnoticed. PostgreSQL is unaffected too -- batch mode emits a plain
    `ALTER TABLE ... DROP COLUMN` there -- so this is the offline profile only.
    """
    assert set(reference_triggers) == _APPEND_ONLY_TRIGGERS
    config = _alembic_config(pre_case_clock_db)

    command.upgrade(config, _CASE_CLOCK_REVISION)
    assert _triggers_on(pre_case_clock_db, "case_reviews") == reference_triggers

    command.downgrade(config, _PRE_CASE_CLOCK_REVISION)
    assert _triggers_on(pre_case_clock_db, "case_reviews") == reference_triggers

    # And a round trip back up leaves them in place rather than double-creating them.
    command.upgrade(config, _CASE_CLOCK_REVISION)
    assert _triggers_on(pre_case_clock_db, "case_reviews") == reference_triggers


@pytest.mark.parametrize(
    "statement",
    [
        "update case_reviews set note = 'rewritten' where review_id = 'review-legacy'",
        "delete from case_reviews where review_id = 'review-legacy'",
    ],
)
def test_review_evidence_is_still_append_only_after_a_downgrade(
    pre_case_clock_db: str, statement: str
) -> None:
    """The property the triggers exist for, asserted on the data rather than on `sqlite_master`.
    A trigger that exists but does not fire would pass the test above and fail this one."""
    config = _alembic_config(pre_case_clock_db)
    command.upgrade(config, _CASE_CLOCK_REVISION)
    command.downgrade(config, _PRE_CASE_CLOCK_REVISION)

    engine = create_engine(_sync_database_url(pre_case_clock_db))
    try:
        with engine.begin() as connection, pytest.raises(Exception, match="append-only"):
            connection.execute(text(statement))
        with engine.connect() as connection:
            assert connection.execute(text("select count(*) from case_reviews")).scalar() == 1
    finally:
        engine.dispose()


def test_the_downgrade_removes_exactly_the_five_columns_it_added(pre_case_clock_db: str) -> None:
    config = _alembic_config(pre_case_clock_db)
    command.upgrade(config, _CASE_CLOCK_REVISION)
    command.downgrade(config, _PRE_CASE_CLOCK_REVISION)

    engine = create_engine(_sync_database_url(pre_case_clock_db))
    inspector = inspect(engine)
    case_columns = {column["name"] for column in inspector.get_columns("review_cases")}
    review_columns = {column["name"] for column in inspector.get_columns("case_reviews")}
    with engine.connect() as connection:
        surviving = connection.execute(text("select case_id, status from review_cases")).all()
    engine.dispose()

    assert not (_NEW_CASE_COLUMNS & case_columns)
    assert not (_NEW_REVIEW_COLUMNS & review_columns)
    # The rows themselves are untouched: only the columns go.
    assert surviving == [("case-legacy", "open")]
