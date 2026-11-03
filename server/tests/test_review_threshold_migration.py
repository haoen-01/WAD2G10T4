"""The review-threshold calibrator's stores (Alembic `485506d5a415`, ADR 0008).

Steps through the real Alembic chain rather than building the schema from ORM metadata, because
every property pinned here lives only in the migration's DDL and is invisible to
`Base.metadata.create_all`, which the rest of the suite uses:

- both new tables are append-only on SQLite, so the offline demo cannot rewrite a threshold
  approval or revert after the fact;
- the uniqueness that makes "a proposal is decided once" and "an approval is ended once" hold
  under concurrent writers is enforced by the database, not only by code;
- the downgrade is real, and it leaves `case_reviews` append-only. Dropping `reached_too_late`
  makes SQLite's batch mode rebuild that table, and a rebuilt table carries none of its triggers
  (the bug `e3b7d5c18a42` fixed for its own downgrade).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from alembic import command
from silverloop.sql_repository import _sync_database_url

_PRE_THRESHOLD_REVISION = "d8b1e4f70c2a"
_THRESHOLD_REVISION = "485506d5a415"
_API_ROOT = Path(__file__).resolve().parents[1]

_NEW_TABLES = ("review_threshold_proposals", "review_threshold_decisions")
_CASE_REVIEW_TRIGGERS = {"case_reviews_reject_update", "case_reviews_reject_delete"}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(_API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", _sync_database_url(database_url).replace("%", "%%"))
    config.attributes["database_url_configured"] = True
    return config


def _engine(database_url: str) -> Engine:
    return create_engine(_sync_database_url(database_url))


def _triggers_on(database_url: str, table: str) -> dict[str, str]:
    """`{name: stored DDL}` for every trigger on `table` -- compared by SQL, not only by name, so
    a trigger that exists but raises nothing cannot pass."""
    engine = _engine(database_url)
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
def pre_threshold_db(tmp_path: Path) -> str:
    """A SQLite database at the revision before the calibrator, holding one case and one review
    against it -- the shape a shared database already in use would be in."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'pre-threshold.db'}"
    command.upgrade(_alembic_config(database_url), _PRE_THRESHOLD_REVISION)

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
                "human_action, override_reason) "
                "values ('review-legacy', 'case-legacy', 'run-legacy', 'resolved', "
                "'coordinator', 'Usual for her.', :now, 'override', 'known_context')"
            ),
            {"now": now},
        )
    engine.dispose()
    return database_url


def _insert_proposal(
    connection: Connection, proposal_id: str, *, write_up_for: str | None = None
) -> None:
    connection.execute(
        text(
            "insert into review_threshold_proposals "
            "(proposal_id, run_id, person_id, output_kind, proposer, previous_severity_pct, "
            "previous_persistence_days, proposed_severity_pct, proposed_persistence_days, cause, "
            "reasoning, cited_evidence_ids, trigger_case_id, trigger_review_ids, reported_by, "
            "coordinator_reason, write_up_for_decision_id, proposed_on_day, proposed_at) "
            "values (:proposal_id, 'run-legacy', 'legacy-person', 'proposal', 'fixed_rule', "
            "40, 3, 40, 4, 'too_tight_for_person', 'Two false alarms in 30 days.', "
            "'[\"review-legacy\"]', 'case-legacy', '[\"review-legacy\"]', 'coordinator', "
            "'not_a_concern', :write_up_for, '2026-01-05', :now)"
        ),
        {
            "proposal_id": proposal_id,
            "write_up_for": write_up_for,
            "now": datetime.now(UTC).isoformat(),
        },
    )


def _insert_decision(
    connection: Connection,
    decision_id: str,
    *,
    kind: str = "approved",
    proposal_id: str | None = None,
    ends_approval_id: str | None = None,
) -> None:
    connection.execute(
        text(
            "insert into review_threshold_decisions "
            "(decision_id, run_id, person_id, kind, proposal_id, ends_approval_id, "
            "previous_severity_pct, previous_persistence_days, severity_pct, persistence_days, "
            "decided_by, trigger_case_id, trigger_review_id, decided_on_day, "
            "effective_from_day, decided_at) "
            "values (:decision_id, 'run-legacy', 'legacy-person', :kind, :proposal_id, "
            ":ends_approval_id, 40, 3, 40, 4, 'coordinator', 'case-legacy', 'review-legacy', "
            "'2026-01-05', '2026-01-06', :now)"
        ),
        {
            "decision_id": decision_id,
            "kind": kind,
            "proposal_id": proposal_id,
            "ends_approval_id": ends_approval_id,
            "now": datetime.now(UTC).isoformat(),
        },
    )


@pytest.fixture
def threshold_db(pre_threshold_db: str) -> Iterator[str]:
    """Upgraded to the calibrator revision with one proposal and one approval stored."""
    command.upgrade(_alembic_config(pre_threshold_db), _THRESHOLD_REVISION)
    engine = _engine(pre_threshold_db)
    with engine.begin() as connection:
        _insert_proposal(connection, "proposal-1")
        _insert_decision(connection, "decision-1", proposal_id="proposal-1")
    engine.dispose()
    yield pre_threshold_db


def test_the_upgrade_adds_both_tables_and_the_column_without_inventing_a_value(
    pre_threshold_db: str,
) -> None:
    command.upgrade(_alembic_config(pre_threshold_db), _THRESHOLD_REVISION)

    engine = _engine(pre_threshold_db)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    review_columns = {column["name"] for column in inspector.get_columns("case_reviews")}
    with engine.connect() as connection:
        review = connection.execute(
            text(
                "select note, override_reason, reached_too_late from case_reviews "
                "where review_id = 'review-legacy'"
            )
        ).one()
    engine.dispose()

    assert set(_NEW_TABLES) <= tables
    assert "reached_too_late" in review_columns
    assert review.note == "Usual for her."
    assert review.override_reason == "known_context"
    # No past reviewer was asked whether the case reached them too late.
    assert review.reached_too_late is None


@pytest.mark.parametrize(
    "statement",
    [
        "update review_threshold_proposals set reasoning = 'rewritten'",
        "delete from review_threshold_proposals",
        "update review_threshold_decisions set severity_pct = 55",
        "delete from review_threshold_decisions",
    ],
)
def test_both_threshold_tables_are_append_only_on_sqlite(threshold_db: str, statement: str) -> None:
    engine = _engine(threshold_db)
    try:
        with engine.begin() as connection, pytest.raises(DatabaseError, match="append-only"):
            connection.execute(text(statement))
        with engine.connect() as connection:
            assert (
                connection.execute(text("select count(*) from review_threshold_proposals")).scalar()
                == 1
            )
            assert (
                connection.execute(text("select count(*) from review_threshold_decisions")).scalar()
                == 1
            )
    finally:
        engine.dispose()


def test_a_proposal_is_decided_at_most_once(threshold_db: str) -> None:
    engine = _engine(threshold_db)
    try:
        with engine.begin() as connection, pytest.raises(DatabaseError, match="UNIQUE"):
            _insert_decision(connection, "decision-2", kind="rejected", proposal_id="proposal-1")
    finally:
        engine.dispose()


def test_an_approval_is_ended_at_most_once(threshold_db: str) -> None:
    engine = _engine(threshold_db)
    try:
        with engine.begin() as connection:
            _insert_decision(connection, "revert-1", kind="reverted", ends_approval_id="decision-1")
        with engine.begin() as connection, pytest.raises(DatabaseError, match="UNIQUE"):
            _insert_decision(connection, "expire-1", kind="expired", ends_approval_id="decision-1")
    finally:
        engine.dispose()


def test_a_revert_gets_at_most_one_write_up(threshold_db: str) -> None:
    engine = _engine(threshold_db)
    try:
        with engine.begin() as connection:
            _insert_proposal(connection, "write-up-1", write_up_for="revert-x")
        with engine.begin() as connection, pytest.raises(DatabaseError, match="UNIQUE"):
            _insert_proposal(connection, "write-up-2", write_up_for="revert-x")
    finally:
        engine.dispose()


@pytest.fixture
def reference_case_review_triggers(tmp_path: Path) -> dict[str, str]:
    """The `case_reviews` trigger DDL of a never-downgraded database built by the same chain, so
    the comparison is against the real thing rather than a copy that could drift."""
    database_url = f"sqlite+pysqlite:///{tmp_path / 'reference.db'}"
    command.upgrade(_alembic_config(database_url), _THRESHOLD_REVISION)
    return _triggers_on(database_url, "case_reviews")


def test_the_downgrade_removes_the_stores_and_keeps_case_reviews_append_only(
    threshold_db: str, reference_case_review_triggers: dict[str, str]
) -> None:
    assert set(reference_case_review_triggers) == _CASE_REVIEW_TRIGGERS
    assert _triggers_on(threshold_db, "case_reviews") == reference_case_review_triggers

    command.downgrade(_alembic_config(threshold_db), _PRE_THRESHOLD_REVISION)

    engine = _engine(threshold_db)
    try:
        inspector = inspect(engine)
        assert not (set(_NEW_TABLES) & set(inspector.get_table_names()))
        review_columns = {column["name"] for column in inspector.get_columns("case_reviews")}
        assert "reached_too_late" not in review_columns
        # The review row itself survives the batch rebuild.
        with engine.connect() as connection:
            assert connection.execute(text("select review_id from case_reviews")).all() == [
                ("review-legacy",)
            ]
        assert _triggers_on(threshold_db, "case_reviews") == reference_case_review_triggers
        # And the triggers fire, not merely exist.
        for statement in (
            "update case_reviews set note = 'rewritten'",
            "delete from case_reviews",
        ):
            with engine.begin() as connection, pytest.raises(DatabaseError, match="append-only"):
                connection.execute(text(statement))
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_round_trips(
    pre_threshold_db: str, reference_case_review_triggers: dict[str, str]
) -> None:
    config = _alembic_config(pre_threshold_db)
    command.upgrade(config, _THRESHOLD_REVISION)
    reference_new_table_triggers = {
        table: _triggers_on(pre_threshold_db, table) for table in _NEW_TABLES
    }
    for table, triggers in reference_new_table_triggers.items():
        assert set(triggers) == {f"{table}_reject_update", f"{table}_reject_delete"}

    command.downgrade(config, _PRE_THRESHOLD_REVISION)
    command.upgrade(config, _THRESHOLD_REVISION)

    assert _triggers_on(pre_threshold_db, "case_reviews") == reference_case_review_triggers
    for table in _NEW_TABLES:
        assert _triggers_on(pre_threshold_db, table) == reference_new_table_triggers[table]

    engine = _engine(pre_threshold_db)
    try:
        with engine.begin() as connection:
            _insert_proposal(connection, "proposal-again")
        with engine.begin() as connection, pytest.raises(DatabaseError, match="append-only"):
            connection.execute(text("delete from review_threshold_proposals"))
    finally:
        engine.dispose()
