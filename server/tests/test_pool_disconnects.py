"""A pooled connection dropped while idle must not split a multi-transaction write.

`advance()` commits the day's reading in one transaction and writes that day's decision evidence,
audit event and replay record in a second. Without a blanket pre-ping, a second checkout handed a
connection the pooler closed while it sat idle would fail after the reading is committed, leaving
a day with no recorded decision (and a browser retry would advance another day).
`_ping_connections_idle_since` pings a connection that has been idle past a threshold on checkout,
and the pool replaces it before any statement runs.

These run on a SQLite file, where a closed `sqlite3` connection is a real dead connection that the
dialect classifies as a disconnect ("Cannot operate on a closed database."), so the pool's own
invalidate-and-replace path is what is exercised -- nothing about the ping or the pool is faked
except the clock.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from silverloop.db_models import DailyMetricRow, DecisionEvidenceRow, SimulationEventRow
from silverloop.sql_repository import SqlAlchemyRepository, _ping_connections_idle_since

IDLE_SECONDS = 30.0


@dataclass
class _Clock:
    now: float = 1_000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class _PoolWatch:
    invalidations: int = 0
    pings: int = 0
    killed: list[Any] = field(default_factory=list)


def _file_engine(path: Path) -> Engine:
    # No pre-ping, LIFO: the server-database configuration, on a file SQLite pool (QueuePool).
    return create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"check_same_thread": False},
        pool_use_lifo=True,
    )


def _watch(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> _PoolWatch:
    watch = _PoolWatch()

    def on_invalidate(*_: object) -> None:
        watch.invalidations += 1

    event.listen(engine, "invalidate", on_invalidate)
    real_ping = engine.dialect.do_ping

    def counting_ping(dbapi_connection: Any) -> bool:
        watch.pings += 1
        return real_ping(dbapi_connection)

    monkeypatch.setattr(engine.dialect, "do_ping", counting_ping)
    return watch


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    instance = _file_engine(tmp_path / "pool.db")
    yield instance
    instance.dispose()


def _checkout_and_return(engine: Engine) -> Any:
    with engine.connect() as connection:
        connection.execute(text("select 1"))
        return connection.connection.dbapi_connection


def test_a_connection_returned_recently_is_handed_out_without_a_ping(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _Clock()
    _ping_connections_idle_since(engine, IDLE_SECONDS, clock=clock)
    watch = _watch(engine, monkeypatch)

    _checkout_and_return(engine)  # a brand-new connection: never pinged
    clock.now += IDLE_SECONDS - 0.5
    _checkout_and_return(engine)

    assert watch.pings == 0


def test_a_connection_idle_past_the_threshold_is_pinged_once_on_checkout(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _Clock()
    _ping_connections_idle_since(engine, IDLE_SECONDS, clock=clock)
    watch = _watch(engine, monkeypatch)

    first = _checkout_and_return(engine)
    clock.now += IDLE_SECONDS
    second = _checkout_and_return(engine)

    assert watch.pings == 1
    assert watch.invalidations == 0
    assert second is first  # alive, so kept


def test_a_dead_idle_connection_is_replaced_before_any_statement_uses_it(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _Clock()
    _ping_connections_idle_since(engine, IDLE_SECONDS, clock=clock)
    watch = _watch(engine, monkeypatch)

    dead = _checkout_and_return(engine)
    dead.close()  # the pooler closed it while it sat in the pool
    clock.now += IDLE_SECONDS + 1

    with engine.connect() as connection:
        assert connection.execute(text("select 1")).scalar_one() == 1
        assert connection.connection.dbapi_connection is not dead

    assert watch.pings == 1
    assert watch.invalidations == 1


def test_without_the_idle_ping_the_same_dead_connection_fails_its_first_statement(
    engine: Engine,
) -> None:
    """The control: the scenario above is a real disconnect, not one the ping merely imagines."""
    dead = _checkout_and_return(engine)
    dead.close()

    with pytest.raises(DBAPIError) as raised, engine.connect() as connection:
        connection.execute(text("select 1"))

    assert raised.value.connection_invalidated is True


# ── advance(): the dead connection lands on the write phase's checkout ──────────────────────────


def _repository(path: Path, *, idle_ping: bool, clock: _Clock) -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository(f"sqlite+pysqlite:///{path}")
    # The file-SQLite options pre-ping every checkout, which would hide the failure under test;
    # swap in the server-database pool shape (no pre-ping, LIFO) before anything connects.
    repository.engine.dispose()
    repository.engine = _file_engine(path)
    repository.sessions = sessionmaker(repository.engine, expire_on_commit=False)
    if idle_ping:
        _ping_connections_idle_since(repository.engine, IDLE_SECONDS, clock=clock)
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def _kill_the_connection_advance_returns_after_its_first_commit(
    repository: SqlAlchemyRepository, clock: _Clock, watch: _PoolWatch
) -> None:
    """When the first `advance()` transaction commits, the connection it returns to the pool is
    closed and the clock moves past the idle threshold -- the planner window, during which the
    pooler dropped the idle connection. Only that one connection, only once."""
    armed = {"value": False}

    def on_commit(_: object) -> None:
        if not watch.killed:
            armed["value"] = True

    def on_checkin(dbapi_connection: Any, _: object) -> None:
        if armed["value"] and dbapi_connection is not None:
            armed["value"] = False
            dbapi_connection.close()
            watch.killed.append(dbapi_connection)
            clock.now += IDLE_SECONDS + 5

    event.listen(repository.sessions, "after_commit", on_commit)
    event.listen(repository.engine, "checkin", on_checkin)


def _count(repository: SqlAlchemyRepository, model: Any, *conditions: Any) -> int:
    with repository.sessions() as session:
        return int(session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


def test_advance_survives_a_dropped_connection_on_its_write_phase_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _Clock()
    repository = _repository(tmp_path / "advance.db", idle_ping=True, clock=clock)
    try:
        before = repository.person_state()
        decisions_before = _count(repository, DecisionEvidenceRow)
        watch = _watch(repository.engine, monkeypatch)
        _kill_the_connection_advance_returns_after_its_first_commit(repository, clock, watch)

        response = repository.advance("activity_declines", event_id="dropped-1")

        # The dead connection was really handed to the write phase, and replaced exactly once.
        assert len(watch.killed) == 1
        assert watch.invalidations == 1
        day = response.state.current_day
        assert day > before.current_day
        assert _count(repository, DailyMetricRow, DailyMetricRow.day == day) == 1
        assert _count(repository, DecisionEvidenceRow) == decisions_before + 1
        assert response.audit_event.detail["evidence_id"] is not None
        assert (
            _count(
                repository,
                SimulationEventRow,
                SimulationEventRow.client_event_id == "dropped-1",
            )
            == 1
        )

        # The browser's retry of the same event replays; it does not advance another day.
        replayed = repository.advance("activity_declines", event_id="dropped-1")
        assert replayed.state.current_day == day
        assert _count(repository, DecisionEvidenceRow) == decisions_before + 1
    finally:
        repository.close()


def test_without_the_idle_ping_the_write_phase_fails_after_the_day_is_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control for the test above: the same dropped connection, no idle ping, splits the
    advance -- the reading is committed and the decision is not. This is the failure the ping
    exists to prevent, shown to be reachable by the simulation."""
    clock = _Clock()
    repository = _repository(tmp_path / "control.db", idle_ping=False, clock=clock)
    try:
        before = repository.person_state()
        decisions_before = _count(repository, DecisionEvidenceRow)
        watch = _watch(repository.engine, monkeypatch)
        _kill_the_connection_advance_returns_after_its_first_commit(repository, clock, watch)

        with pytest.raises(DBAPIError) as raised:
            repository.advance("activity_declines", event_id="dropped-2")

        assert raised.value.connection_invalidated is True
        assert len(watch.killed) == 1
        next_day = before.current_day + timedelta(days=1)
        assert _count(repository, DailyMetricRow, DailyMetricRow.day == next_day) == 1
        assert _count(repository, DecisionEvidenceRow) == decisions_before
        assert (
            _count(
                repository,
                SimulationEventRow,
                SimulationEventRow.client_event_id == "dropped-2",
            )
            == 0
        )
    finally:
        repository.close()
