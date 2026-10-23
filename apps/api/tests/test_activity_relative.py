"""`GET /v1/coordinator/people/{id}/activity-relative`: recent days against the person's usual.

The strip on a coordinator's case page used to fetch raw metrics and the senior's own state, then
re-derive the wear-time gate and the low-day line in the browser. These pin the server-derived
replacement: it classifies with the ladder's own rule and baseline, and says nothing numeric.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from silverloop.analytics import (
    ACTIVITY_RELATIVE_MAX_DAYS,
    LOW_DAY_FRACTION,
    MINIMUM_WEAR_HOURS,
    ConfirmedReference,
    activity_relative_to_usual,
    analyse_signal,
    calculate_baseline,
    low_day_threshold,
)
from silverloop.config import Settings
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.main import create_app
from silverloop.models import ActivityPosition, ContextSignal, DailyMetric
from silverloop.sql_repository import SqlAlchemyRepository

_SETTINGS = dict(
    app_env="test",
    database_url="sqlite+pysqlite:///:memory:",
    silverloop_runtime_profile="offline",
    auth_enabled=False,
    llm_enabled=False,
)


def _metric(offset: int, steps: int, wear_hours: float = 13) -> DailyMetric:
    return DailyMetric(
        day=date(2026, 1, 1) + timedelta(days=offset),
        steps=steps,
        active_minutes=30,
        wear_hours=wear_hours,
    )


def _steady(days: int, steps: int = 6000) -> list[DailyMetric]:
    return [_metric(offset, steps) for offset in range(days)]


# ── Pure classification ─────────────────────────────────────────────────────────────────────


def test_the_low_line_is_the_ladders_line_against_todays_effective_baseline() -> None:
    history = [*_steady(28), _metric(28, 4199)]
    today = _metric(29, 4200)
    # The line the ladder uses today: the baseline over everything before today.
    assert low_day_threshold(calculate_baseline(history)) == pytest.approx(6000 * LOW_DAY_FRACTION)
    result = activity_relative_to_usual(
        [*history, today], person_id="p", consent_active=True, days=2
    )
    # Strictly below the line is low; exactly on it is not.
    assert [day.position for day in result.days] == [
        ActivityPosition.LOWER,
        ActivityPosition.USUAL_OR_HIGHER,
    ]
    assert result.usual_available is True
    assert result.as_of_day == today.day
    assert (result.lower_days, result.usable_days) == (1, 2)


def test_a_worn_low_run_counts_the_same_as_the_ladders_persistence() -> None:
    history = [*_steady(26), _metric(26, 3000), _metric(27, 2900)]
    current = _metric(28, 2800)
    _, signal = analyse_signal(
        history,
        current,
        ContextSignal(),
        person_id="p",
        assessed_at=datetime(2026, 1, 29, 12, tzinfo=UTC),
    )
    result = activity_relative_to_usual(
        [*history, current], person_id="p", consent_active=True, days=7
    )
    assert signal.sustained_low_days == 3
    assert result.lower_days == signal.sustained_low_days
    assert [day.position for day in result.days[-3:]] == [ActivityPosition.LOWER] * 3


def test_a_much_higher_day_is_usual_or_higher_not_a_new_band() -> None:
    result = activity_relative_to_usual(
        [*_steady(28), _metric(28, 60_000)], person_id="p", consent_active=True, days=1
    )
    assert result.days[0].position is ActivityPosition.USUAL_OR_HIGHER


def test_a_day_without_enough_wear_is_unusable_and_has_no_position() -> None:
    short = MINIMUM_WEAR_HOURS - 0.5
    result = activity_relative_to_usual(
        [*_steady(28), _metric(28, 100, wear_hours=short), _metric(29, 100, MINIMUM_WEAR_HOURS)],
        person_id="p",
        consent_active=True,
        days=2,
    )
    assert [(day.reading_usable, day.position) for day in result.days] == [
        (False, None),
        (True, ActivityPosition.LOWER),
    ]
    assert (result.lower_days, result.usable_days) == (1, 1)


def test_no_usual_level_means_no_positions_but_usability_is_still_reported() -> None:
    result = activity_relative_to_usual(
        [_metric(0, 5000, wear_hours=2), _metric(1, 5000)],
        person_id="p",
        consent_active=True,
        days=7,
    )
    assert result.usual_available is False
    assert [(day.reading_usable, day.position) for day in result.days] == [
        (False, None),
        (True, None),
    ]
    assert (result.lower_days, result.usable_days) == (0, 1)


def test_a_confirmed_reference_moves_the_line_exactly_as_it_moves_the_ladder() -> None:
    # A long decline: the clamp holds the effective baseline up near the old reference, so a day
    # at the new level reads lower -- until the person confirms the new level as their usual.
    history = [*_steady(28, 8000), *_steady(40, 3000)]
    history = [_metric(offset, metric.steps) for offset, metric in enumerate(history)]
    today = _metric(len(history), 3000)
    clamped = activity_relative_to_usual(
        [*history, today], person_id="p", consent_active=True, days=1
    )
    confirmed = activity_relative_to_usual(
        [*history, today],
        person_id="p",
        consent_active=True,
        days=1,
        confirmed_reference=ConfirmedReference(steps=3000, days=28),
    )
    assert clamped.days[0].position is ActivityPosition.LOWER
    assert confirmed.days[0].position is ActivityPosition.USUAL_OR_HIGHER


def test_the_window_is_the_most_recent_days_oldest_first_and_bounded() -> None:
    metrics = _steady(40)
    result = activity_relative_to_usual(metrics, person_id="p", consent_active=True, days=5)
    assert [day.day for day in result.days] == [metric.day for metric in metrics[-5:]]
    widest = activity_relative_to_usual(metrics, person_id="p", consent_active=True, days=1000)
    assert len(widest.days) == ACTIVITY_RELATIVE_MAX_DAYS
    shorter = activity_relative_to_usual(metrics[:3], person_id="p", consent_active=True, days=7)
    assert len(shorter.days) == 3


def test_withdrawn_consent_reads_back_no_days_and_no_usual_level() -> None:
    # A real decline, which would otherwise read as lower days: withdrawal hides all of it.
    metrics = [*_steady(28), _metric(28, 1000), _metric(29, 1000, wear_hours=2)]
    result = activity_relative_to_usual(metrics, person_id="p", consent_active=False, days=7)
    assert result.consent_active is False
    assert result.usual_available is False
    assert result.days == []
    assert (result.lower_days, result.usable_days) == (0, 0)
    assert result.as_of_day == metrics[-1].day
    active = activity_relative_to_usual(metrics, person_id="p", consent_active=True, days=7)
    assert active.consent_active is True
    assert active.lower_days == 1


def test_an_empty_record_is_refused() -> None:
    with pytest.raises(ValueError):
        activity_relative_to_usual([], person_id="p", consent_active=True)


# ── Route ───────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> Iterator[tuple[TestClient, SqlAlchemyRepository]]:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=Settings(**_SETTINGS))
    repository.create_schema_for_tests()
    repository.reset(person_id=DEMO_PERSON_ID)
    with TestClient(
        create_app(repository, settings=Settings(**_SETTINGS), migrate_on_start=False)
    ) as test_client:
        yield test_client, repository
    repository.close()


def _path(person_id: str = DEMO_PERSON_ID) -> str:
    return f"/v1/coordinator/people/{person_id}/activity-relative"


def _numbers(value: Any, key: str = "") -> list[str]:
    """Every key in the JSON that holds a number (booleans aside)."""
    if isinstance(value, dict):
        return [found for k, v in value.items() for found in _numbers(v, k)]
    if isinstance(value, list):
        return [found for item in value for found in _numbers(item, key)]
    if isinstance(value, int | float) and not isinstance(value, bool):
        return [key]
    return []


def test_route_matches_the_ladders_persistence_on_a_real_decline(
    client: tuple[TestClient, SqlAlchemyRepository],
) -> None:
    test_client, repository = client
    for index in range(3):
        repository.advance("activity_declines", event_id=f"ar-{index}", person_id=DEMO_PERSON_ID)
    state = test_client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()
    response = test_client.get(_path())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["person_id"] == DEMO_PERSON_ID
    assert body["consent_active"] is True
    assert body["usual_available"] is True
    assert len(body["days"]) == 7
    assert body["as_of_day"] == body["days"][-1]["day"]
    trailing_lower = 0
    for day in reversed(body["days"]):
        if day["position"] != "lower":
            break
        trailing_lower += 1
    assert state["signal"]["sustained_low_days"] == 3
    assert trailing_lower == state["signal"]["sustained_low_days"]
    assert body["lower_days"] >= trailing_lower


def test_route_returns_no_days_once_consent_is_withdrawn(
    client: tuple[TestClient, SqlAlchemyRepository],
) -> None:
    test_client, repository = client
    for index in range(3):
        repository.advance("activity_declines", event_id=f"ar-c-{index}", person_id=DEMO_PERSON_ID)
    before = test_client.get(_path()).json()
    assert before["consent_active"] is True
    assert any(day["position"] == "lower" for day in before["days"])
    repository.advance("consent_revoked", event_id="ar-revoke", person_id=DEMO_PERSON_ID)
    response = test_client.get(_path())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["consent_active"] is False
    assert body["usual_available"] is False
    assert body["days"] == []
    assert (body["lower_days"], body["usable_days"]) == (0, 0)
    assert '"position"' not in response.text


def test_route_carries_no_step_counts_percentages_or_scores(
    client: tuple[TestClient, SqlAlchemyRepository],
) -> None:
    test_client, repository = client
    repository.advance("activity_declines", event_id="ar-num", person_id=DEMO_PERSON_ID)
    body = test_client.get(_path()).json()
    assert sorted(_numbers(body)) == ["lower_days", "usable_days"]
    text = test_client.get(_path()).text
    for forbidden in ("steps", "percent", "score", "median", "wear_hours", "threshold"):
        assert forbidden not in text


def test_route_bounds_the_window(client: tuple[TestClient, SqlAlchemyRepository]) -> None:
    test_client, _ = client
    assert len(test_client.get(_path(), params={"days": 3}).json()["days"]) == 3
    assert test_client.get(_path(), params={"days": ACTIVITY_RELATIVE_MAX_DAYS}).status_code == 200
    for bad in (0, ACTIVITY_RELATIVE_MAX_DAYS + 1):
        assert test_client.get(_path(), params={"days": bad}).status_code == 422


def test_route_unknown_person_is_not_found(
    client: tuple[TestClient, SqlAlchemyRepository],
) -> None:
    test_client, _ = client
    assert test_client.get(_path("nobody")).status_code == 404
