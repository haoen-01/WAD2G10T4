"""Round trips per read, measured, with ceilings that do not grow with the caseload.

Against the shared database every query is a network round trip (~80 ms to the Supabase session
pooler), so a read's latency is its query count. The coordinator and person reads used to issue a
dozen queries per person and several per intervention; they now read each input set once for the
whole caseload (`_load_run_reads`, `_to_cases`, `_to_interventions`, `_world_models`,
`_run_counts`).

These tests pin both halves of that: every read stays within a small ceiling, and the count is the
same whether the caseload holds two people with a short history or six people with a long one. A
change that reintroduces a per-person or per-intervention query fails here long before anyone
notices the page getting slower.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from silverloop.config import Settings
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.main import create_app
from silverloop.models import CaseStatus, DeclineReason, FollowThrough, HumanAction, OutcomeKind
from silverloop.quality import MINIMUM_WEAR_HOURS
from silverloop.sql_repository import ROSTER_TRACKER_WINDOW_DAYS, SqlAlchemyRepository

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
    "coordinator_people": 10,
    "coordinator_priorities": 13,
    "coordinator_priorities_person": 13,
    "coordinator_metrics": 20,
    "coordinator_queue": 6,
    "case": 13,
    "metrics": 23,
    "state": 9,
    "world_model": 19,
    "replan_notices": 9,
    "senior_home": 13,
    "inspect": 9,
    "activity_relative": 4,
}

# Reads over the whole caseload: the count must not depend on how many people are on it.
_CASELOAD_READS = (
    "coordinator_people",
    "coordinator_priorities",
    "coordinator_priorities_person",
    "coordinator_metrics",
    "coordinator_queue",
)
# Reads about one person: the count must not depend on how long their history is.
_PERSON_READS = (
    "case",
    "metrics",
    "state",
    "world_model",
    "replan_notices",
    "senior_home",
    "inspect",
    "activity_relative",
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
            repository.record_follow_through(
                intervention.intervention_id, FollowThrough.COMPLETED, person_id=person_id
            )
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
    repository.review_case(
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
    client = demo.client
    person = f"/v1/people/{DEMO_PERSON_ID}"
    return {
        "coordinator_people": lambda: client.get("/v1/coordinator/people"),
        "coordinator_priorities": lambda: client.get("/v1/coordinator/priorities"),
        "coordinator_priorities_person": lambda: client.get(
            "/v1/coordinator/priorities", params={"person_id": DEMO_PERSON_ID}
        ),
        "coordinator_metrics": lambda: client.get("/v1/coordinator/metrics"),
        "coordinator_queue": lambda: client.get(
            "/v1/coordinator/queue", params={"status": "open,acknowledged,resolved"}
        ),
        "case": lambda: client.get(f"/v1/cases/{demo.case_id}"),
        "metrics": lambda: client.get("/v1/metrics", params={"person_id": DEMO_PERSON_ID}),
        "state": lambda: client.get(f"{person}/state"),
        "world_model": lambda: client.get(f"{person}/world-model"),
        "replan_notices": lambda: client.get(f"{person}/replan-notices"),
        "senior_home": lambda: client.get(f"/v1/evaluator/people/{DEMO_PERSON_ID}/senior-home"),
        "inspect": lambda: client.post(
            "/v1/evaluator/ranker/inspect", json={"person_id": DEMO_PERSON_ID}
        ),
        "activity_relative": lambda: client.get(
            f"/v1/coordinator/people/{DEMO_PERSON_ID}/activity-relative"
        ),
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
    assert response.status_code == 200, (name, response.text)
    return counts["queries"], counts["connections"]


@pytest.mark.parametrize("name", sorted(_CEILINGS))
def test_each_read_stays_within_its_query_ceiling_on_one_connection(
    large: _Demo, name: str
) -> None:
    queries, connections = _measure(large, name)
    assert queries <= _CEILINGS[name], f"{name} issued {queries} queries"
    assert connections == 1, f"{name} checked out {connections} connections"


@pytest.mark.parametrize("name", _CASELOAD_READS)
def test_caseload_reads_cost_the_same_for_two_people_as_for_six(
    small: _Demo, large: _Demo, name: str
) -> None:
    assert len(small.repository.list_coordinator_roster()) == 2
    assert len(large.repository.list_coordinator_roster()) == len(_PEOPLE)
    assert _measure(small, name)[0] == _measure(large, name)[0]


@pytest.mark.parametrize("name", _PERSON_READS)
def test_person_reads_cost_the_same_for_a_short_history_as_a_long_one(
    small: _Demo, large: _Demo, name: str
) -> None:
    short = small.repository.list_interventions(person_id=DEMO_PERSON_ID)
    long = large.repository.list_interventions(person_id=DEMO_PERSON_ID)
    assert 0 < len(short) < len(long)
    assert len(small.repository.list_cases()) < len(large.repository.list_cases())
    assert _measure(small, name)[0] == _measure(large, name)[0]


def test_fleet_metrics_are_the_sum_of_each_rostered_persons_metrics(large: _Demo) -> None:
    client = large.client
    roster = [row["person_id"] for row in client.get("/v1/coordinator/people").json()]
    per_person = [
        client.get("/v1/metrics", params={"person_id": person_id}).json() for person_id in roster
    ]
    fleet = client.get("/v1/coordinator/metrics").json()

    assert fleet["people"] == per_person[0]["people"]
    assert fleet["people_included"] == len(roster)
    for field in (
        "no_action_decisions",
        "interventions",
        "awaiting_reply",
        "no_reply_recorded",
        "coordinator_reviews",
        "coordinator_overrides",
        "device_suspected_days",
    ):
        assert fleet[field] == sum(metrics[field] for metrics in per_person), field
    for field, total in fleet["world_model_quality"].items():
        assert total == sum(m["world_model_quality"][field] for m in per_person), field
    # Not a vacuous sum: the seeded caseload has outreach, reviews and known facts in it.
    assert fleet["interventions"] > 0
    assert fleet["coordinator_reviews"] > 0
    assert fleet["world_model_quality"]["facts"] > 0


@pytest.mark.parametrize("top_k", [1, 2, 5])
def test_one_persons_priorities_are_their_row_of_the_full_board(large: _Demo, top_k: int) -> None:
    client = large.client
    board = client.get("/v1/coordinator/priorities", params={"top_k": top_k}).json()
    assert len(board["people"]) == len(_PEOPLE)
    for row in board["people"]:
        narrowed = client.get(
            "/v1/coordinator/priorities",
            params={"top_k": top_k, "person_id": row["person_id"]},
        ).json()
        assert narrowed["people"] == [row]
        assert narrowed["follow_up_first"] == [
            first for first in board["follow_up_first"] if first["person_id"] == row["person_id"]
        ]
        assert narrowed["top_k"] == board["top_k"]
        assert narrowed["boundary_note"] == board["boundary_note"]
        assert narrowed["thresholds"] == board["thresholds"]


def test_priorities_for_an_unknown_person_is_not_found(large: _Demo) -> None:
    response = large.client.get("/v1/coordinator/priorities", params={"person_id": "nobody"})
    assert response.status_code == 404


# ── Caseload rows agree with the single-person reads they summarise ──────────────────────────────
#
# The caseload reads now build every person's row from inputs loaded once for the whole caseload
# (`_load_run_reads`, `_latest_unresolved_cases`, ...), while the single-person reads load one
# person's inputs on their own. Both must describe the same person the same way.


def _open_case(client: TestClient, person_id: str) -> dict[str, Any] | None:
    """The person's most recently opened unresolved case, from the queue and the case read."""
    queue = client.get("/v1/coordinator/queue", params={"status": "open,acknowledged"}).json()
    theirs = [case for case in queue if case["person_id"] == person_id]
    if not theirs:
        return None
    latest = max(
        theirs, key=lambda case: (datetime.fromisoformat(case["opened_at"]), case["case_id"])
    )
    case = client.get(f"/v1/cases/{latest['case_id']}").json()
    assert case["status"] in ("open", "acknowledged")
    return case


def _tracker_not_synced_days(client: TestClient, person_id: str) -> int:
    recent = client.get(
        f"/v1/people/{person_id}/metrics", params={"days": ROSTER_TRACKER_WINDOW_DAYS}
    ).json()
    assert 0 < len(recent) <= ROSTER_TRACKER_WINDOW_DAYS
    return sum(1 for day in recent if day["wear_hours"] < MINIMUM_WEAR_HOURS)


# The large caseload is uniform where these reads branch: everyone consents, every tracker synced,
# no offer is waiting for a reply and no review-timing change is proposed. A second, short caseload
# puts one person on each of those branches.
_VARIED_STORIES: dict[str, tuple[str, ...]] = {
    # A case open and reviewed as having come too late: a sooner review timing is proposed.
    "mdm-lim": ("activity_declines", "activity_declines", "activity_declines"),
    "mr-ravi": ("recovery", "recovery"),  # nothing happening
    "mdm-siti": ("activity_declines",),  # a nudge nobody has answered yet
    "mr-tan": ("activity_declines", "consent_revoked"),  # consent withdrawn after an offer
    "mdm-devi": ("low_wear", "low_wear"),  # the tracker did not sync
    "mdm-wong": ("activity_declines", "activity_declines", "activity_declines"),  # a case open
}


@pytest.fixture(scope="module")
def varied() -> Iterator[_Demo]:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=Settings(**_SETTINGS))
    repository.create_schema_for_tests()
    for person_id in _PEOPLE:
        repository.reset(person_id=person_id)
    for person_id, story in _VARIED_STORIES.items():
        for day, event_name in enumerate(story):
            repository.advance(
                event_name, event_id=f"varied-{person_id}-{day}", person_id=person_id
            )
    (case,) = [
        case
        for case in repository.list_cases(person_id=DEMO_PERSON_ID)
        if case.status != CaseStatus.RESOLVED
    ]
    repository.review_case(
        case.case_id,
        CaseStatus.ACKNOWLEDGED,
        "This should have reached us sooner.",
        human_action=HumanAction.HOLD,
        reached_too_late=True,
    )
    client = TestClient(
        create_app(repository, settings=Settings(**_SETTINGS), migrate_on_start=False)
    )
    client.__enter__()
    yield _Demo(repository=repository, client=client, case_id=case.case_id)
    client.__exit__(None, None, None)
    repository.close()


@pytest.mark.parametrize("caseload", ["large", "varied"])
def test_each_roster_row_matches_that_persons_own_reads(
    request: pytest.FixtureRequest, caseload: str
) -> None:
    demo: _Demo = request.getfixturevalue(caseload)
    client = demo.client
    roster = client.get("/v1/coordinator/people").json()
    assert sorted(row["person_id"] for row in roster) == sorted(_PEOPLE)

    for row in roster:
        person_id = row["person_id"]
        state = client.get(f"/v1/people/{person_id}/state").json()
        metrics = client.get("/v1/metrics", params={"person_id": person_id}).json()
        open_case = _open_case(client, person_id)

        assert row["display_name"] == state["display_name"], person_id
        assert row["attention_band"] == state["attention_band"], person_id
        assert row["consent_active"] == state["consent_active"], person_id
        assert row["consent_active"] == metrics["consent_active"], person_id
        # The roster reports the read-time decision, as the person's state does. (`/v1/metrics`
        # reports the latest *recorded* decision, which a read-time gate may have since lowered.)
        assert row["last_decision"] == state["last_decision"], person_id
        assert row["tracker_not_synced_days"] == _tracker_not_synced_days(client, person_id), (
            person_id
        )
        assert row["open_case_id"] == (open_case["case_id"] if open_case else None), person_id

    # Not a vacuous agreement: each caseload reaches the branches it exists for.
    assert any(row["open_case_id"] for row in roster)
    assert len({row["last_decision"] for row in roster}) > 1
    if caseload == "varied":
        assert any(row["tracker_not_synced_days"] > 0 for row in roster)
        assert not all(row["consent_active"] for row in roster)


@pytest.mark.parametrize("caseload", ["large", "varied"])
def test_each_priority_row_matches_that_persons_own_reads(
    request: pytest.FixtureRequest, caseload: str
) -> None:
    demo: _Demo = request.getfixturevalue(caseload)
    client = demo.client
    board = client.get("/v1/coordinator/priorities").json()
    assert sorted(row["person_id"] for row in board["people"]) == sorted(_PEOPLE)

    for row in board["people"]:
        person_id = row["person_id"]
        state = client.get(f"/v1/people/{person_id}/state").json()
        open_case = _open_case(client, person_id)
        consented = state["consent_active"]
        history = client.get(f"/v1/coordinator/people/{person_id}/outreach-history").json()
        awaiting = [
            item["awaiting_reply_until"] for item in history if item["awaiting_reply_until"]
        ]
        threshold = client.get(f"/v1/coordinator/people/{person_id}/review-threshold").json()

        assert row["display_name"] == state["display_name"], person_id
        assert row["as_of_day"] == state["current_day"], person_id
        expected_evidence = [state["signal"]["quality"]["evidence_id"]]
        if open_case is not None:
            expected_evidence.append(open_case["decision_evidence_id"])
        assert row["evidence_ids"] == expected_evidence, person_id
        if consented and open_case is not None:
            assert row["open_case_id"] == open_case["case_id"], person_id
            assert row["review_back_on_day"] == open_case["review_by_day"], person_id
        else:
            assert row["open_case_id"] is None, person_id
            assert row["review_back_on_day"] is None, person_id
        assert row["awaiting_reply_until"] == (max(awaiting) if consented and awaiting else None), (
            person_id
        )
        assert row["review_timing_proposal_waiting"] == (
            consented and threshold["open_proposal"] is not None
        ), person_id

    assert any(row["open_case_id"] for row in board["people"])
    assert any(row["review_back_on_day"] for row in board["people"])
    if caseload == "varied":
        assert any(row["awaiting_reply_until"] for row in board["people"])
        assert any(row["review_timing_proposal_waiting"] for row in board["people"])
