"""The calibration-trust contract's evaluation seam (docs/calibration-trust-spec.md, the D seam).

The evaluation's `authored_metric` seam replaces a generated metric, but never on
`consent_revoked`. (Sections A and B -- the context-gap category on a coordinator's review, review
lessons and the review-setting receipt -- went with the review routes in step 7.)
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from silverloop.config import Settings
from silverloop.db_models import DailyMetricRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import (
    DailyMetric,
)
from silverloop.sql_repository import SqlAlchemyRepository


def _authored_repository(
    authored: dict[date, DailyMetric], calls: list[tuple[str, date]]
) -> SqlAlchemyRepository:
    def authored_metric(person_id: str, day: date) -> DailyMetric | None:
        calls.append((person_id, day))
        return authored.get(day)

    instance = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=Settings(
            app_env="test",
            database_url="sqlite+pysqlite:///:memory:",
            silverloop_runtime_profile="offline",
            auth_enabled=False,
            llm_enabled=False,
        ),
        authored_metric=authored_metric,
    )
    instance.create_schema_for_tests()
    instance.reset()
    return instance


def _stored_metric(repository: SqlAlchemyRepository, day: date) -> DailyMetricRow:
    with repository.sessions() as session:
        row = session.scalar(select(DailyMetricRow).where(DailyMetricRow.day == day))
    assert row is not None
    return row


def test_an_authored_metric_replaces_the_generated_one() -> None:
    calls: list[tuple[str, date]] = []
    probe = _authored_repository({}, calls)
    try:
        first_day = probe.advance("recovery", person_id=DEMO_PERSON_ID).state.current_day
    finally:
        probe.close()
    assert calls == [(DEMO_PERSON_ID, first_day)]

    calls.clear()
    authored = DailyMetric(
        day=first_day, steps=1234, active_minutes=11, sleep_hours=7.1, wear_hours=12.5
    )
    repository = _authored_repository({first_day: authored}, calls)
    try:
        repository.advance("recovery", person_id=DEMO_PERSON_ID)
        stored = _stored_metric(repository, first_day)
        assert (stored.steps, stored.active_minutes, stored.wear_hours) == (1234, 11, 12.5)
    finally:
        repository.close()


def test_an_authored_metric_for_the_wrong_day_is_refused() -> None:
    calls: list[tuple[str, date]] = []
    probe = _authored_repository({}, calls)
    try:
        first_day = probe.advance("recovery", person_id=DEMO_PERSON_ID).state.current_day
    finally:
        probe.close()

    wrong = DailyMetric(day=date(2000, 1, 1), steps=1, active_minutes=1, wear_hours=12.0)
    repository = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=Settings(
            app_env="test",
            database_url="sqlite+pysqlite:///:memory:",
            silverloop_runtime_profile="offline",
            auth_enabled=False,
            llm_enabled=False,
        ),
        authored_metric=lambda _person, day: wrong if day == first_day else None,
    )
    repository.create_schema_for_tests()
    repository.reset()
    try:
        with pytest.raises(ValueError, match="authored metric"):
            repository.advance("recovery", person_id=DEMO_PERSON_ID)
    finally:
        repository.close()


def test_consent_revoked_is_never_overridden_by_an_authored_metric() -> None:
    calls: list[tuple[str, date]] = []
    probe = _authored_repository({}, calls)
    try:
        next_day = probe.advance("recovery", person_id=DEMO_PERSON_ID).state.current_day
    finally:
        probe.close()

    calls.clear()
    authored = DailyMetric(
        day=next_day, steps=9999, active_minutes=99, sleep_hours=7.0, wear_hours=14.0
    )
    repository = _authored_repository({next_day: authored}, calls)
    try:
        repository.advance("consent_revoked", person_id=DEMO_PERSON_ID)
        assert calls == []
        stored = _stored_metric(repository, next_day)
        assert (stored.steps, stored.wear_hours) == (0, 0)
    finally:
        repository.close()
