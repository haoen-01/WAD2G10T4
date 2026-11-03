"""Review-setting writers on PostgreSQL: the run-row lock and its ordering (ADR 0008).

Skipped unless `SILVERLOOP_POSTGRES_TEST_URL` names a dedicated test database, like the rest of the
PostgreSQL suite. SQLite has no row locks; `test_review_threshold_api.py` pins the
lock-before-insert ordering there, and these tests pin what that ordering buys on the engine the
shared runtime uses.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from silverloop.db_models import (
    AuditEventRow,
    ScenarioRunRow,
)
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.migrations import upgrade_database
from silverloop.sql_repository import (
    SqlAlchemyRepository,
    _sync_database_url,
    _utcnow,
)

POSTGRES_TEST_URL = os.getenv("SILVERLOOP_POSTGRES_TEST_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not POSTGRES_TEST_URL,
        reason="SILVERLOOP_POSTGRES_TEST_URL is required for PostgreSQL integration tests",
    ),
]


def _repository() -> SqlAlchemyRepository:
    assert POSTGRES_TEST_URL is not None
    database_url = _sync_database_url(POSTGRES_TEST_URL)
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql" or "test" not in (parsed.database or "").lower():
        pytest.fail("PostgreSQL tests require a dedicated database whose name contains 'test'.")
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    repository.reset()
    return repository


def _run_id(repository: SqlAlchemyRepository) -> str:
    with repository.sessions() as session:
        run_id = session.scalar(
            select(ScenarioRunRow.run_id).where(
                ScenarioRunRow.active.is_(True), ScenarioRunRow.person_id == DEMO_PERSON_ID
            )
        )
    assert run_id is not None
    return run_id


def test_the_run_lock_serialises_writers_but_never_blocks_a_child_insert() -> None:
    repository = _repository()
    run_id = _run_id(repository)
    holder = repository.sessions()
    try:
        holder.begin()
        repository._lock_threshold_run(holder, run_id)

        # FOR NO KEY UPDATE is compatible with the KEY SHARE lock a child insert takes.
        with repository.sessions.begin() as other:
            other.execute(text("SET LOCAL lock_timeout = '2s'"))
            other.add(
                AuditEventRow(
                    event_id=f"evt_lock_probe_{_utcnow().timestamp():.0f}",
                    run_id=run_id,
                    person_id=DEMO_PERSON_ID,
                    event_type="lock_probe",
                    actor="test",
                    decision=None,
                    detail_json={},
                    recorded_at=_utcnow(),
                )
            )

        # A second review-setting writer waits for the first.
        waiting = repository.sessions()
        try:
            waiting.begin()
            waiting.execute(text("SET LOCAL lock_timeout = '300ms'"))
            with pytest.raises(DBAPIError, match="lock"):
                repository._lock_threshold_run(waiting, run_id)
        finally:
            waiting.rollback()
            waiting.close()
    finally:
        holder.rollback()
        holder.close()
        repository.close()
