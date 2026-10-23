"""A second unclarified answer only widens a belief when it is about a *different* programme.

One unclarified "not for me" (`THIS_ONE`) or "bad timing" (`THIS_SLOT`) is item-level and held
back until a second agreeing answer. Saying no to the same programme again -- the same listing on
another day, a sibling session of it, or its outreach card -- is not a second, independent view of
the *kind* of thing or the *time*: the cooldown already holds that programme back. It used to be
counted as one, so two answers about one Tuesday chair class became "no mornings" and "no chair
exercise".

The pure rule lives in `preferences._fold`; this file pins the repository half through the routes
a browser reaches -- every path names the programme of the answer (`series`) and of each held
belief's origin (`origin_series`) by looking the origin up by id, never by parsing it -- and the
inspector's read-only preview, which must reach the same verdict and write nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from silverloop.activity_search import series_key
from silverloop.db_models import ActivityCandidateRow, ActivityDimensionPreferenceRow, Base
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import ActivityRankingTrace
from silverloop.sql_repository import SqlAlchemyRepository

# (reason, dimension, first listing, a sibling session of the same programme, a session of a
# different programme on the same value of that dimension). Chair Mobility & Balance and Seated
# Strength Basics are both `chair_exercise`, run by the same provider under different titles; the
# Sheltered Morning Walk sessions and Tai Chi in the Park all start in the local morning.
_AXES = (
    pytest.param(
        "not_for_me",
        "activity_type",
        "activity-chair-mobility-1",
        "activity-chair-mobility-2",
        "activity-seated-strength-1",
        id="activity_type",
    ),
    pytest.param(
        "bad_timing",
        "timing",
        "activity-sheltered-walk-1",
        "activity-sheltered-walk-2",
        "activity-tai-chi-1",
        id="timing",
    ),
)

_PROGRAMME_KEY = "programme:aac-chair-mobility"


def _decline(client: TestClient, activity_id: str, reason: str) -> dict[str, Any]:
    response = client.post(
        f"/v1/activities/{activity_id}/response",
        json={"response": "not_for_me", "reason": reason},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["audit_event"]["detail"]["inference_skipped"] is None
    return payload


def _preferences(client: TestClient) -> dict[str, Any]:
    response = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences")
    assert response.status_code == 200, response.text
    return response.json()


def _rows_on(client: TestClient, dimension: str) -> list[dict[str, Any]]:
    return [p for p in _preferences(client)["dimensions"] if p["dimension"] == dimension]


def _resolved_on(client: TestClient, dimension: str) -> list[dict[str, Any]]:
    return [r for r in _preferences(client)["resolved"] if r["dimension"] == dimension]


def _advance(client: TestClient, event: str = "recovery") -> dict[str, Any]:
    response = client.post("/v1/simulation/advance", json={"event": event})
    assert response.status_code == 200, response.text
    return response.json()


def _assert_still_held_back(client: TestClient, dimension: str, origin_id: str) -> None:
    """One row, one unit of evidence, still named after the first answer, and nothing resolved."""
    rows = _rows_on(client, dimension)
    assert [(row["observations"], row["origin_id"]) for row in rows] == [(1, origin_id)]
    assert rows[0]["positive_evidence"] + rows[0]["negative_evidence"] == 1.0
    assert _resolved_on(client, dimension) == []


def _assert_widened(client: TestClient, payload: dict[str, Any], dimension: str) -> None:
    assert [p["dimension"] for p in payload["preferences_updated"]] == [dimension]
    rows = _rows_on(client, dimension)
    assert [row["observations"] for row in rows] == [2]
    assert [r["evidence_count"] for r in _resolved_on(client, dimension)] == [2]


def _decline_programme_outreach(client: TestClient, reason: str) -> dict[str, Any]:
    """Advance until the chair-mobility programme is offered as outreach, then decline it."""
    for _ in range(12):
        intervention = _advance(client, "activity_declines").get("created_intervention")
        if intervention is not None and intervention["candidate_key"] == _PROGRAMME_KEY:
            response = client.post(
                f"/v1/interventions/{intervention['intervention_id']}/outcome",
                json={"outcome": "declined", "reason": reason},
            )
            assert response.status_code == 200, response.text
            return response.json()
    raise AssertionError(f"no {_PROGRAMME_KEY} outreach was created in twelve declining days")


# ── Same programme: still held back ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(("reason", "dimension", "first", "sibling", "other"), _AXES)
def test_the_same_listing_declined_again_on_another_day_stays_held_back(
    client: TestClient, reason: str, dimension: str, first: str, sibling: str, other: str
) -> None:
    opening = _decline(client, first, reason)
    assert opening["preferences_updated"] == []
    _advance(client)

    again = _decline(client, first, reason)

    # A real second answer on a real second day -- not the same-day duplicate rule -- and still
    # nothing the person is told was learned, because nothing generalised.
    assert again["preferences_updated"] == []
    _assert_still_held_back(client, dimension, opening["response_id"])


@pytest.mark.parametrize(("reason", "dimension", "first", "sibling", "other"), _AXES)
def test_a_sibling_session_of_the_same_programme_stays_held_back(
    client: TestClient, reason: str, dimension: str, first: str, sibling: str, other: str
) -> None:
    opening = _decline(client, first, reason)
    _advance(client)

    again = _decline(client, sibling, reason)

    assert again["preferences_updated"] == []
    _assert_still_held_back(client, dimension, opening["response_id"])


@pytest.mark.parametrize("order", ["outreach_first", "search_first"])
def test_an_outreach_decline_and_a_search_decline_on_that_programme_are_one_programme(
    client: TestClient, repository: SqlAlchemyRepository, order: str
) -> None:
    """`programme:aac-chair-mobility` has no provider or title of its own to compare; it is the
    same programme as its catalogue listing through `_catalogue_row_for_programme`'s title join,
    and the outcome row's series is read through its intervention's candidate key."""
    with repository.sessions() as session:
        listing = session.get(ActivityCandidateRow, "activity-chair-mobility-2")
        assert listing is not None
        assert repository._series_for_candidate_key(session, _PROGRAMME_KEY) == series_key(listing)

    if order == "outreach_first":
        outreach = _decline_programme_outreach(client, "not_for_me")
        origin_id = outreach["outcome_evidence_id"]
        search = _decline(client, "activity-chair-mobility-2", "not_for_me")
        assert search["preferences_updated"] == []
    else:
        search = _decline(client, "activity-chair-mobility-2", "not_for_me")
        origin_id = search["response_id"]
        _decline_programme_outreach(client, "not_for_me")

    _assert_still_held_back(client, "activity_type", origin_id)


# ── A different programme: the second answer agrees ──────────────────────────────────────────


@pytest.mark.parametrize(("reason", "dimension", "first", "sibling", "other"), _AXES)
def test_a_different_programme_on_the_same_value_widens(
    client: TestClient, reason: str, dimension: str, first: str, sibling: str, other: str
) -> None:
    _decline(client, first, reason)
    _advance(client)

    agreeing = _decline(client, other, reason)

    _assert_widened(client, agreeing, dimension)


def test_an_outreach_decline_and_a_different_programme_s_listing_widen(
    client: TestClient,
) -> None:
    _decline_programme_outreach(client, "not_for_me")

    agreeing = _decline(client, "activity-seated-strength-1", "not_for_me")

    _assert_widened(client, agreeing, "activity_type")
    assert [r["value"] for r in _resolved_on(client, "activity_type")] == ["chair_exercise"]


@pytest.mark.parametrize(("reason", "dimension", "first", "sibling", "other"), _AXES)
def test_after_widening_a_repeat_about_the_latest_programme_adds_no_evidence(
    client: TestClient, reason: str, dimension: str, first: str, sibling: str, other: str
) -> None:
    """Order matters through the routes: a different programme widens, and a further answer about
    that same (latest) programme -- a sibling session of it -- adds nothing, so repeats about one
    programme never push a belief toward `STRONG_LEARNED`. Another answer about the first
    programme does count: only the latest origin is stored (a documented approximation)."""
    _decline(client, first, reason)
    _advance(client)
    agreeing = _decline(client, other, reason)
    _assert_widened(client, agreeing, dimension)
    other_sibling = f"{other[:-1]}2"
    _advance(client)

    repeat = _decline(client, other_sibling, reason)

    assert repeat["preferences_updated"] == []
    rows = _rows_on(client, dimension)
    assert [(row["observations"], row["origin_id"]) for row in rows] == [
        (2, agreeing["response_id"])
    ]
    assert [r["evidence_count"] for r in _resolved_on(client, dimension)] == [2]

    _advance(client)
    back_to_first = _decline(client, sibling, reason)
    assert [row["observations"] for row in _rows_on(client, dimension)] == [3]
    assert back_to_first["preferences_updated"] != []


# ── An origin nothing can be looked up for: today's behaviour ─────────────────────────────────


@pytest.mark.parametrize("legacy_origin", [None, "plan-not-an-answer-table-row"])
@pytest.mark.parametrize(("reason", "dimension", "first", "sibling", "other"), _AXES)
def test_a_row_whose_origin_names_no_answer_keeps_today_s_behaviour(
    client: TestClient,
    repository: SqlAlchemyRepository,
    legacy_origin: str | None,
    reason: str,
    dimension: str,
    first: str,
    sibling: str,
    other: str,
) -> None:
    """A row written before origins were recorded, or whose origin is not a search response or an
    outreach outcome, cannot be said to be about any programme -- so the rule cannot apply, and a
    second answer on the same listing widens exactly as it did before."""
    _decline(client, first, reason)
    with repository.sessions.begin() as session:
        session.execute(
            update(ActivityDimensionPreferenceRow)
            .where(ActivityDimensionPreferenceRow.dimension == dimension)
            .values(origin_id=legacy_origin)
        )
    _advance(client)

    again = _decline(client, first, reason)

    _assert_widened(client, again, dimension)


# ── The lookups themselves ────────────────────────────────────────────────────────────────────


def test_origin_series_is_read_by_id_from_both_answer_tables_only(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    outreach = _decline_programme_outreach(client, "not_for_me")
    search = _decline(client, "activity-tai-chi-1", "not_for_me")

    with repository.sessions() as session:
        chair = session.get(ActivityCandidateRow, "activity-chair-mobility-1")
        tai_chi = session.get(ActivityCandidateRow, "activity-tai-chi-1")
        assert chair is not None and tai_chi is not None
        found = repository._origin_series(
            session,
            [
                outreach["outcome_evidence_id"],
                search["response_id"],
                None,
                "",
                # Shaped like an answer id, but in neither table: absent, never guessed from its
                # prefix.
                "aresp_does_not_exist",
                "activity-tai-chi-1",
            ],
        )
        assert found == {
            outreach["outcome_evidence_id"]: series_key(chair),
            search["response_id"]: series_key(tai_chi),
        }
        assert repository._origin_series(session, []) == {}
        # Outreach that is not a programme (a gentle nudge) and unknown kinds name no programme.
        assert repository._series_for_candidate_key(session, "gentle_nudge:walk") is None
        assert repository._series_for_candidate_key(session, "activity:nope") is None
        assert repository._series_for_candidate_key(session, "programme:nope") is None


def test_a_programme_with_no_catalogue_listing_is_only_ever_itself(
    repository: SqlAlchemyRepository,
) -> None:
    with repository.sessions.begin() as session:
        session.execute(
            update(ActivityCandidateRow)
            .where(ActivityCandidateRow.title == "Chair Mobility & Balance")
            .values(title="Renamed listing")
        )
    with repository.sessions() as session:
        assert repository._series_for_candidate_key(session, _PROGRAMME_KEY) == _PROGRAMME_KEY


# ── The inspector previews the same rule, and writes nothing ──────────────────────────────────


def _snapshot(repository: SqlAlchemyRepository) -> dict[str, list[tuple[str, ...]]]:
    with repository.sessions() as session:
        return {
            table.name: sorted(
                tuple(repr(value) for value in row) for row in session.execute(select(table))
            )
            for table in Base.metadata.sorted_tables
        }


def _preview(client: TestClient, activity_id: str, reason: str) -> ActivityRankingTrace:
    response = client.post(
        "/v1/evaluator/ranker/inspect",
        json={
            "person_id": DEMO_PERSON_ID,
            "feedback": {"activity_id": activity_id, "response": "not_for_me", "reason": reason},
        },
    )
    assert response.status_code == 200, response.text
    return ActivityRankingTrace.model_validate(response.json()["variant"])


@pytest.mark.parametrize(("reason", "dimension", "first", "sibling", "other"), _AXES)
def test_the_inspector_preview_on_the_same_programme_applies_no_new_fact(
    client: TestClient,
    repository: SqlAlchemyRepository,
    reason: str,
    dimension: str,
    first: str,
    sibling: str,
    other: str,
) -> None:
    _decline(client, first, reason)
    before = _snapshot(repository)

    same = _preview(client, sibling, reason)

    assert same.applied.learning_preview is not None
    assert same.applied.learning_preview.duplicate_same_day is False
    assert same.applied.learning_preview.teaches_dimension is False
    assert not [fact.fact_key for fact in same.person_context.facts if fact.changed_by_preview]
    assert not [
        fact.fact_key
        for fact in same.person_context.facts
        if fact.fact_key.startswith(f"{dimension}:") and fact.used_in_scoring
    ]

    # The control: the identical preview about a different programme does teach -- so the silence
    # above is the rule, not an inert preview.
    different = _preview(client, other, reason)
    assert different.applied.learning_preview is not None
    assert different.applied.learning_preview.teaches_dimension is True
    assert [
        fact.fact_key
        for fact in different.person_context.facts
        if fact.fact_key.startswith(f"{dimension}:") and fact.changed_by_preview
    ]

    assert _snapshot(repository) == before
