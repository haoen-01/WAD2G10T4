"""`SqlAlchemyRepository.simulation_history` / `GET /v1/simulation/history`.

Every `advance()` call that carries an `event_id` (every browser call does) already persists the
full `AdvanceResponse` in `SimulationEventRow.response_json`; `latest_advance()` only ever
surfaced the most recent one. `simulation_history` makes the rest of that multi-day narrative
readable, oldest-first, scoped to the person's active run.
"""

from __future__ import annotations

import pytest

from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository

PERSON_B = "person-b"


@pytest.fixture
def repo() -> SqlAlchemyRepository:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()
    instance.reset()  # seeds DEMO_PERSON_ID
    return instance


def test_simulation_history_empty_for_person_with_no_stored_events(
    repo: SqlAlchemyRepository,
) -> None:
    assert repo.simulation_history() == []


def test_simulation_history_is_oldest_first(repo: SqlAlchemyRepository) -> None:
    repo.advance("activity_declines", event_id="hist-1")
    repo.advance("recovery", event_id="hist-2")
    repo.advance("low_wear", event_id="hist-3")

    history = repo.simulation_history()

    assert [entry.event_name for entry in history] == [
        "activity_declines",
        "recovery",
        "low_wear",
    ]
    days = [entry.day for entry in history]
    assert days == sorted(days)


def test_simulation_history_respects_the_limit_cap(repo: SqlAlchemyRepository) -> None:
    for index in range(35):
        repo.advance("recovery", event_id=f"hist-{index:03d}")

    uncapped_request = repo.simulation_history(limit=100)
    assert len(uncapped_request) == 30  # capped even though 35 events were stored

    default_request = repo.simulation_history()
    assert len(default_request) == 10  # default

    small_request = repo.simulation_history(limit=3)
    assert len(small_request) == 3
    # The last N, oldest-first among that window.
    assert [entry.day for entry in small_request] == sorted(entry.day for entry in small_request)
    assert small_request[-1].day == uncapped_request[-1].day


def test_simulation_history_is_person_scoped(repo: SqlAlchemyRepository) -> None:
    repo.reset(person_id=PERSON_B, allow_new_person=True)
    repo.advance("activity_declines", event_id="a-1", person_id=DEMO_PERSON_ID)
    repo.advance("low_wear", event_id="b-1", person_id=PERSON_B)
    repo.advance("recovery", event_id="b-2", person_id=PERSON_B)

    history_a = repo.simulation_history(person_id=DEMO_PERSON_ID)
    history_b = repo.simulation_history(person_id=PERSON_B)

    assert [entry.event_name for entry in history_a] == ["activity_declines"]
    assert [entry.event_name for entry in history_b] == ["low_wear", "recovery"]


def test_simulation_history_raises_key_error_for_unknown_person(
    repo: SqlAlchemyRepository,
) -> None:
    with pytest.raises(KeyError):
        repo.simulation_history(person_id="no-such-person")
