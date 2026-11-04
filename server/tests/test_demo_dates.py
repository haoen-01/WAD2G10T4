"""The demo's synthetic readings end on today when `demo_dates_follow_today` is on: the same values,
every day moved by one offset, the programmes with them, and nothing real or earlier rewritten."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from silverloop.adapters.synthetic import SyntheticFixtureAdapter
from silverloop.config import Settings
from silverloop.db_models import DailyMetricRow, ProgrammeRow
from silverloop.fixtures import DEMO_ANCHOR_DAY, DEMO_PERSON_ID, synthetic_programmes
from silverloop.local_time import local_date
from silverloop.sql_repository import SqlAlchemyRepository

# 3 pm in Singapore: the fixture's midday-UTC stamp (8 pm local) is still to come.
NOW = datetime(2026, 11, 4, 7, 0, tzinfo=UTC)


def _repository(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> SqlAlchemyRepository:
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: NOW)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        llm_enabled=False,
        **overrides,
    )
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=settings)
    repository.create_schema_for_tests()
    return repository


def _rows(
    repository: SqlAlchemyRepository, person_id: str = DEMO_PERSON_ID
) -> list[DailyMetricRow]:
    with repository.sessions() as session:
        return list(
            session.scalars(
                select(DailyMetricRow)
                .where(DailyMetricRow.person_id == person_id)
                .order_by(DailyMetricRow.run_id, DailyMetricRow.day)
            )
        )


def test_the_readings_end_on_today_with_the_same_values_in_the_same_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(monkeypatch, demo_dates_follow_today=True)
    state = repository.reset().state
    today = local_date(NOW)
    assert state.current_day == today

    fixture = SyntheticFixtureAdapter(2026).read().metrics
    rows = _rows(repository)
    assert [row.steps for row in rows] == [metric.steps for metric in fixture]
    # One offset for every day: the gaps between days are the fixture's own.
    offset = today - DEMO_ANCHOR_DAY
    assert [row.day for row in rows] == [metric.day + offset for metric in fixture]
    # Still sample data, and never stamped later than the moment it was written.
    assert {row.source for row in rows} == {"synthetic"}
    assert {row.fixture_classification for row in rows} == {"synthetic_fixture"}
    assert max(row.observed_at.replace(tzinfo=UTC) for row in rows) <= NOW


def test_the_programmes_move_with_the_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(monkeypatch, demo_dates_follow_today=True)
    repository.reset()
    offset = local_date(NOW) - DEMO_ANCHOR_DAY
    with repository.sessions() as session:
        stored = {row.programme_id: row for row in session.scalars(select(ProgrammeRow))}
    for programme in synthetic_programmes():
        row = stored[programme.programme_id]
        assert row.next_session.replace(tzinfo=UTC) == programme.next_session + offset
        assert row.valid_until.replace(tzinfo=UTC) == programme.next_session + offset + timedelta(
            days=7
        )


def test_an_explicit_end_day_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _repository(monkeypatch, demo_dates_follow_today=True)
    two_days_ago = local_date(NOW) - timedelta(days=2)
    assert repository.reset(end_on=two_days_ago).state.current_day == two_days_ago


def test_with_the_setting_off_the_fixture_keeps_its_own_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(monkeypatch, demo_dates_follow_today=False)
    assert repository.reset().state.current_day == DEMO_ANCHOR_DAY == date(2026, 8, 18)


def test_a_reset_never_rewrites_an_earlier_run_or_anyone_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reset writes a new run from the synthetic fixture; the readings already stored (an earlier
    run, or another person's) keep their own days."""
    repository = _repository(monkeypatch, demo_dates_follow_today=False)
    repository.reset()
    repository.reset(person_id="mr-tan")
    before_lim = [(row.run_id, row.day, row.steps) for row in _rows(repository)]
    before_tan = [(row.day, row.steps) for row in _rows(repository, "mr-tan")]

    repository.reset(end_on=local_date(NOW))

    after_lim = [(row.run_id, row.day, row.steps) for row in _rows(repository)]
    assert set(before_lim) <= set(after_lim)  # the August run is still there, untouched
    assert [(row.day, row.steps) for row in _rows(repository, "mr-tan")] == before_tan
