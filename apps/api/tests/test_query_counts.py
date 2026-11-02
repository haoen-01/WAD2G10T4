"""Round trips per read, measured, with ceilings that do not grow with the caseload.

Against the shared database every query is a network round trip (~80 ms to the Supabase session
pooler), so a read's latency is its query count. The person reads used to issue a dozen queries
per person and several per intervention; they now read each input set once (`_load_run_reads`,
`_to_cases`, `_to_interventions`, `_world_models`, `_run_counts`).

These tests pin both halves of that: every read stays within a small ceiling, and the count is the
same whether the person has a short history or a long one. A change that reintroduces a
per-intervention query fails here long before anyone notices the page getting slower. (The
coordinator caseload reads this file also measured went with their routes in step 7.)
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from silverloop.config import Settings
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.main import create_app
from silverloop.models import CaseStatus, DeclineReason, FollowThrough, HumanAction, OutcomeKind
from silverloop.sql_repository import SqlAlchemyRepository
from tests.row_fixtures import record_case_review, record_follow_through, world_model

_SETTINGS = dict(
    app_env="test",
    database_url="sqlite+pysqlite:///:memory:",
    silverloop_runtime_profile="offline",
    auth_enabled=False,
    llm_enabled=False,
)

_PEOPLE = ["mdm-lim", "mr-ravi", "mdm-siti", "mr-tan", "mdm-devi", "mdm-wong"]

# The most queries each read may issue on SQLite, where each is one round trip. Measured on the
# large caseload below and kept tight: raising one is a deliberate, reviewed decision.
_CEILINGS: dict[str, int] = {
    "metrics": 23,
    "state": 9,
    "world_model": 19,
}

# Reads about one person: the count must not depend on how long their history is.
_PERSON_READS = (
    "metrics",
    "state",
    "world_model",
)


@dataclass
class _Demo:
    repository: SqlAlchemyRepository
    client: TestClient
    case_id: str


def _answer_open_offers(repository: SqlAlchemyRepository, person_id: str, turn: list[int]) -> None:
    """Answer each new offer in a fixed rotation, so outcome rows of several kinds exist."""
    for intervention in repository.list_interventions(person_id=person_id):
        if intervention.status != "proposed":
            continue
        choice = turn[0] % 4
        turn[0] += 1
        if choice == 1:
            repository.record_outcome(
                intervention.intervention_id,
                OutcomeKind.DECLINED,
                reason=DeclineReason.ALREADY_ACTIVE,
                person_id=person_id,
            )
        elif choice == 2:
            repository.record_outcome(
                intervention.intervention_id, OutcomeKind.ACCEPTED, person_id=person_id
            )
            record_follow_through(repository, intervention.intervention_id, FollowThrough.COMPLETED)
        elif choice == 3:
            repository.record_outcome(
                intervention.intervention_id,
                OutcomeKind.DECLINED,
                reason=DeclineReason.BAD_DAY,
                person_id=person_id,
            )
        # choice 0: left unanswered, for the response clock or the next event to settle.


# Three low days then a recovery, repeated: each turn of the cycle offers outreach and opens (then
# closes) a review case, so a longer story has proportionally more of both. Both stories end on a
# low day, so the demo person also has a case still open to review.
_CYCLE = ("activity_declines", "activity_declines", "activity_declines", "recovery")


def _build(people: list[str], days: int) -> _Demo:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=Settings(**_SETTINGS))
    repository.create_schema_for_tests()
    for person_id in people:
        repository.reset(person_id=person_id)
    for person_id in people:
        turn = [0]
        for day in range(days):
            repository.advance(
                _CYCLE[day % len(_CYCLE)], event_id=f"qc-{person_id}-{day}", person_id=person_id
            )
            _answer_open_offers(repository, person_id, turn)
    cases = repository.list_cases(person_id=DEMO_PERSON_ID)
    unresolved = [case for case in cases if case.status != CaseStatus.RESOLVED]
    assert len(cases) > 1 and unresolved, "the demo person should have resolved and open cases"
    record_case_review(
        repository,
        unresolved[0].case_id,
        CaseStatus.ACKNOWLEDGED,
        "Looking into it.",
        human_action=HumanAction.HOLD,
    )
    client = TestClient(
        create_app(repository, settings=Settings(**_SETTINGS), migrate_on_start=False)
    )
    client.__enter__()
    return _Demo(repository=repository, client=client, case_id=unresolved[0].case_id)


@pytest.fixture(scope="module")
def small() -> Iterator[_Demo]:
    demo = _build(_PEOPLE[:2], days=7)
    yield demo
    demo.client.__exit__(None, None, None)
    demo.repository.close()


@pytest.fixture(scope="module")
def large() -> Iterator[_Demo]:
    demo = _build(_PEOPLE, days=23)
    yield demo
    demo.client.__exit__(None, None, None)
    demo.repository.close()


def _reads(demo: _Demo) -> dict[str, Callable[[], Any]]:
    """The person reads that remain after step 7: the senior's own state over HTTP, and the
    metrics and world model the removed `/v1/metrics` and `/world-model` routes served, read
    from the repository the same way those routes read them."""
    client = demo.client
    person = f"/v1/people/{DEMO_PERSON_ID}"
    return {
        "metrics": lambda: demo.repository.metrics(person_id=DEMO_PERSON_ID),
        "state": lambda: client.get(f"{person}/state"),
        "world_model": lambda: world_model(demo.repository, person_id=DEMO_PERSON_ID),
    }


@contextmanager
def _counting(repository: SqlAlchemyRepository) -> Iterator[dict[str, int]]:
    counts = {"queries": 0, "connections": 0}

    def on_query(*_: object) -> None:
        counts["queries"] += 1

    def on_checkout(*_: object) -> None:
        counts["connections"] += 1

    event.listen(repository.engine, "before_cursor_execute", on_query)
    event.listen(repository.engine.pool, "checkout", on_checkout)
    try:
        yield counts
    finally:
        event.remove(repository.engine, "before_cursor_execute", on_query)
        event.remove(repository.engine.pool, "checkout", on_checkout)


def _measure(demo: _Demo, name: str) -> tuple[int, int]:
    read = _reads(demo)[name]
    with _counting(demo.repository) as counts:
        response = read()
    if isinstance(response, httpx.Response):
        assert response.status_code == 200, (name, response.text)
    return counts["queries"], counts["connections"]


@pytest.mark.parametrize("name", sorted(_CEILINGS))
def test_each_read_stays_within_its_query_ceiling_on_one_connection(
    large: _Demo, name: str
) -> None:
    queries, connections = _measure(large, name)
    assert queries <= _CEILINGS[name], f"{name} issued {queries} queries"
    assert connections == 1, f"{name} checked out {connections} connections"


@pytest.mark.parametrize("name", _PERSON_READS)
def test_person_reads_cost_the_same_for_a_short_history_as_a_long_one(
    small: _Demo, large: _Demo, name: str
) -> None:
    short = small.repository.list_interventions(person_id=DEMO_PERSON_ID)
    long = large.repository.list_interventions(person_id=DEMO_PERSON_ID)
    assert 0 < len(short) < len(long)
    assert len(small.repository.list_cases()) < len(large.repository.list_cases())
    assert _measure(small, name)[0] == _measure(large, name)[0]
