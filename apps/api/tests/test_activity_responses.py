"""The senior answers a search result, and the user-initiated loop finally learns from it.

Before these routes existed a "Not for me" on a search card lived and died in the browser, a
result could not be chosen, and so nothing a person found for themselves reached the week, the
follow-through question, the enjoyment question or the dimensional learner. Everything here runs
through the FastAPI contract where a browser could reach it.

Also pinned here, because this is the path that made it matter: the preference table's key now
includes `source`, so a decline can never overwrite what an enjoyed activity taught; an expired
(temporary) preference is absent to every reader and is started again from one, never
resurrected, when new evidence arrives on the same key.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import date, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import DatabaseError

from silverloop.activity_search import DECLINE_COOLDOWN_DAYS
from silverloop.config import Settings
from silverloop.db_models import ActivityDimensionPreferenceRow, ActivityOfferResponseRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.main import create_app
from silverloop.migrations import upgrade_database
from silverloop.models import SourceTier
from silverloop.sql_repository import SqlAlchemyRepository

SENIOR_VOCABULARY = ("stable", "watch", "review", "%")


def _search(client: TestClient, intent: dict | None = None) -> dict:
    response = client.post("/v1/activities/search", json={"intent": intent or {}})
    assert response.status_code == 200, response.text
    return response.json()


def _respond(client: TestClient, activity_id: str, **body: object):
    return client.post(f"/v1/activities/{activity_id}/response", json=body)


def _stored_event_detail(client: TestClient, event_id: str) -> dict:
    """The stored copy of an audit event, read back through the operator route."""
    events = client.get("/v1/simulation/events", params={"person_id": DEMO_PERSON_ID}).json()
    return next(event for event in events if event["event_id"] == event_id)["detail"]


def _stored_search_detail(client: TestClient, event_id: str) -> dict:
    """The evaluator's copy of a search audit event (operator route), never the senior's."""
    return _stored_event_detail(client, event_id)


def _current_day(client: TestClient) -> date:
    return date.fromisoformat(
        client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["current_day"]
    )


def _advance(client: TestClient, event: str = "recovery") -> None:
    assert client.post("/v1/simulation/advance", json={"event": event}).status_code == 200


# ── "I'm interested" ──────────────────────────────────────────────────────────────────────────


def test_interested_puts_a_listing_on_the_week_and_says_so(client: TestClient) -> None:
    results = _search(client)["results"]
    today = _current_day(client)
    this_week = next(
        r
        for r in results
        if r["candidate"]["start_at"]
        and today
        <= date.fromisoformat(r["candidate"]["start_at"][:10])
        <= today + timedelta(days=6 - today.weekday())
    )
    activity_id = this_week["candidate"]["activity_id"]

    response = _respond(
        client, activity_id, response="interested", query_id="q-1", rank_shown=this_week["rank"]
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["planned"] is True
    assert payload["response"] == "interested"
    assert "Added to your week" in payload["note"]
    assert "booked" in payload["note"]
    assert any(e["activity"]["activity_id"] == activity_id for e in payload["week"]["entries"])
    for word in SENIOR_VOCABULARY:
        assert word not in payload["note"]

    week = client.get(f"/v1/people/{DEMO_PERSON_ID}/week").json()
    entry = next(e for e in week["entries"] if e["activity"]["activity_id"] == activity_id)
    assert entry["origin"] == "chosen"
    assert entry["follow_through"] is None
    assert entry["awaiting_report"] is False


def test_interested_in_a_session_after_this_week_is_recorded_not_planned(
    client: TestClient,
) -> None:
    results = _search(client)["results"]
    today = _current_day(client)
    week_end = today + timedelta(days=6 - today.weekday())
    later = next(
        r
        for r in results
        if r["candidate"]["start_at"]
        and date.fromisoformat(r["candidate"]["start_at"][:10]) > week_end
    )
    response = _respond(client, later["candidate"]["activity_id"], response="interested")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["planned"] is False
    assert payload["week"] is None
    assert "not on your week" in payload["note"]
    # Still evidence: the response row exists and the engagement factor will see it.
    assert client.get("/v1/metrics").json()["activity_interested"] == 1
    assert client.get("/v1/metrics").json()["activities_planned"] == 0


def test_interested_twice_is_one_plan_and_two_responses(client: TestClient) -> None:
    results = _search(client)["results"]
    activity_id = results[0]["candidate"]["activity_id"]
    first = _respond(client, activity_id, response="interested").json()
    second = _respond(client, activity_id, response="interested").json()
    assert first["planned"] == second["planned"]
    metrics = client.get("/v1/metrics").json()
    assert metrics["activity_interested"] == 2
    if first["planned"]:
        assert metrics["activities_planned"] == 1


# ── "Not for me" reaches the dimensional learner ──────────────────────────────────────────────


def test_too_far_from_a_search_card_teaches_the_distance_dimension(client: TestClient) -> None:
    """The defect this whole file exists for: the learner was unreachable from Ask."""
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )
    results = _search(client)["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)

    response = _respond(
        client, far["candidate"]["activity_id"], response="not_for_me", reason="too_far"
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["planned"] is False
    assert [p["dimension"] for p in payload["preferences_updated"]] == ["distance"]
    learned = payload["preferences_updated"][0]
    # A ceiling in metres, not a bucket: the number the person's own answer put a line at.
    assert learned["pivot"] == far["candidate"]["distance_m"]
    assert learned["direction"] == "lower"
    assert learned["source"] == "decline_reason"
    assert learned["first_observed_at"] is not None

    preferences = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()
    assert [(p["dimension"], p["pivot"]) for p in preferences["dimensions"]] == [
        ("distance", far["candidate"]["distance_m"])
    ]


def test_a_second_too_far_strengthens_rather_than_duplicates(client: TestClient) -> None:
    results = _search(client)["results"]
    far = [r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000]
    first = _respond(
        client, far[0]["candidate"]["activity_id"], response="not_for_me", reason="too_far"
    ).json()
    second = _respond(
        client, far[1]["candidate"]["activity_id"], response="not_for_me", reason="too_far"
    ).json()
    assert second["preferences_updated"][0]["observations"] == 2
    # More evidence on the same axis, on one row -- and the ceiling moves to the tighter of the
    # two distances, because the narrowest thing a person has said is the one that binds.
    assert (
        second["preferences_updated"][0]["strength"] > first["preferences_updated"][0]["strength"]
    )
    assert second["preferences_updated"][0]["pivot"] == min(
        far[0]["candidate"]["distance_m"], far[1]["candidate"]["distance_m"]
    )
    preferences = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()
    assert len(preferences["dimensions"]) == 1


def test_ten_identical_taps_on_one_listing_in_one_day_are_one_observation(
    client: TestClient,
) -> None:
    """Audit I finding 3, reproduced live: ten "not for me: too far" taps on one listing on one
    day wrote ten observations and saturated `distance` to -0.833 in seconds. A stuck button, a
    browser retry or a bored demo operator must not be able to manufacture a belief about
    someone. Every tap is still recorded -- it happened -- and the audit says what was skipped.
    """
    results = _search(client)["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    activity_id = far["candidate"]["activity_id"]

    payloads = [
        _respond(client, activity_id, response="not_for_me", reason="too_far").json()
        for _ in range(10)
    ]
    assert all(payload["response"] == "not_for_me" for payload in payloads)

    dimensions = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()[
        "dimensions"
    ]
    assert [(p["dimension"], p["value"], p["observations"]) for p in dimensions] == [
        ("distance", "lower", 1)
    ]
    assert dimensions[0]["strength"] == pytest.approx(0.333, abs=1e-3)

    # The first tap is an ordinary answer; every repeat is recorded and says so.
    assert payloads[0]["audit_event"]["detail"]["inference_skipped"] is None
    assert all(
        payload["audit_event"]["detail"]["inference_skipped"] == "duplicate_same_day"
        for payload in payloads[1:]
    )
    # The taps themselves are all still on record -- this table is append-only.
    assert client.get("/v1/metrics").json()["activity_decline_reasons"] == {"too_far": 10}


def test_the_same_answer_on_a_second_day_is_a_second_observation(client: TestClient) -> None:
    """The rule is "same day", not "ever": someone who says "too far" again a day later is
    telling us the same thing twice about two different days, and that is real evidence."""
    results = _search(client)["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    activity_id = far["candidate"]["activity_id"]

    _respond(client, activity_id, response="not_for_me", reason="too_far")
    _respond(client, activity_id, response="not_for_me", reason="too_far")
    _advance(client)
    second_day = _respond(client, activity_id, response="not_for_me", reason="too_far").json()

    assert second_day["audit_event"]["detail"]["inference_skipped"] is None
    dimensions = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()[
        "dimensions"
    ]
    assert [(p["dimension"], p["value"], p["observations"]) for p in dimensions] == [
        ("distance", "lower", 2)
    ]


def test_alternating_taps_on_one_listing_in_one_day_cannot_manufacture_a_belief(
    client: TestClient,
) -> None:
    """Red team P1-1: the same-day rule compared a tap against the *latest* answer only, so
    interleaving any other answer reset the comparison. Fifty (`interested`,
    `not_for_me: too_far`) pairs on one listing on one day wrote fifty observations, and the
    belief they built reported `evidence_count: 50` at `STRONG_LEARNED` -- fifty distinct people
    agreeing, from one person and one listing on one afternoon.

    One scored observation per (listing, answer, reason, day). The taps are all still recorded.
    """
    results = _search(client)["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    activity_id = far["candidate"]["activity_id"]
    day = _current_day(client)

    skipped = 0
    for _ in range(50):
        _respond(client, activity_id, response="interested")
        decline = _respond(client, activity_id, response="not_for_me", reason="too_far").json()
        if decline["audit_event"]["detail"]["inference_skipped"] == "duplicate_same_day":
            skipped += 1
    assert skipped == 49, "every repeat of an answer already given today is a repeat"
    assert _current_day(client) == day, "the whole cycle happened on one simulated day"

    preferences = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()
    assert [(p["dimension"], p["observations"]) for p in preferences["dimensions"]] == [
        ("distance", 1)
    ]
    assert [(r["dimension"], r["evidence_count"], r["tier"]) for r in preferences["resolved"]] == [
        ("distance", 1, SourceTier.WEAK_LEARNED)
    ]
    # Every tap is on record -- this table is append-only and the metric counts the taps.
    assert client.get("/v1/metrics").json()["activity_decline_reasons"] == {"too_far": 50}


def test_alternating_taps_cannot_saturate_the_content_axis_either(client: TestClient) -> None:
    """The same probe on `not_for_me` (the ACTIVITY_TYPE axis), which reached `STRONG_LEARNED`
    in thirty cycles and taught a dislike of a whole kind of activity from one listing."""
    results = _search(client)["results"]
    walk = next(r for r in results if r["candidate"].get("activity_type") == "walking")
    activity_id = walk["candidate"]["activity_id"]

    for _ in range(30):
        _respond(client, activity_id, response="interested")
        _respond(client, activity_id, response="not_for_me", reason="not_for_me")

    preferences = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()
    assert [(p["dimension"], p["value"], p["observations"]) for p in preferences["dimensions"]] == [
        ("activity_type", "walking", 1)
    ]
    assert all(r["tier"] == SourceTier.WEAK_LEARNED for r in preferences["resolved"])


def test_every_learned_belief_names_the_answer_it_came_from(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """`_fold` counts distinct origins, and a row with a null `origin_id` is a row that guard
    cannot see. Every production write path names its own evidence row: the search response, the
    plan, the intervention outcome. Before this, `grep origin_id=` over the whole repository
    found only the parameter forwarding its own `None`.
    """
    results = _search(client)["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    declined = _respond(
        client, far["candidate"]["activity_id"], response="not_for_me", reason="too_far"
    ).json()

    with repository.sessions() as session:
        rows = list(session.scalars(select(ActivityDimensionPreferenceRow)))
    assert rows, "the decline taught something"
    assert all(row.origin_id is not None for row in rows)
    # And the origin is the person's own answer, not the listing it was about.
    assert {row.origin_id for row in rows} == {declined["response_id"]}


def test_a_second_tap_on_the_same_listing_the_next_day_is_a_second_origin(
    client: TestClient,
) -> None:
    """The origin rule must not swallow genuine evidence: a fresh answer is a fresh row id, so
    the same answer a day later still counts -- which is the property the same-day rule already
    holds and the one `_fold` must not undo."""
    results = _search(client)["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    activity_id = far["candidate"]["activity_id"]

    _respond(client, activity_id, response="not_for_me", reason="too_far")
    _advance(client)
    second = _respond(client, activity_id, response="not_for_me", reason="too_far").json()

    assert second["audit_event"]["detail"]["inference_skipped"] is None
    assert second["preferences_updated"][0]["observations"] == 2


def test_a_different_reason_on_the_same_day_is_not_a_duplicate(client: TestClient) -> None:
    """The reason is part of the answer -- it is what the dimensional learner reads -- so
    changing it is a new answer, not a repeat of the old one."""
    results = _search(client)["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    activity_id = far["candidate"]["activity_id"]

    _respond(client, activity_id, response="not_for_me", reason="too_far")
    changed = _respond(client, activity_id, response="not_for_me", reason="too_tiring").json()

    assert changed["audit_event"]["detail"]["inference_skipped"] is None
    dimensions = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()[
        "dimensions"
    ]
    # Both axes are ordinal, and both are keyed by the direction the answer pointed in; the
    # number that means something lives in `pivot`.
    assert {(p["dimension"], p["direction"]) for p in dimensions} == {
        ("distance", "lower"),
        ("intensity", "lower"),
    }


def test_repeated_interested_taps_on_one_day_count_once(client: TestClient) -> None:
    """Audit D §8: `_activity_engagement` counted every response row, and `_engagement` adds
    0.25 per `interested` -- so three accidental taps out-weighed actually going. Storage is
    unchanged (the rows and the metric still count every tap); only the score is capped."""
    results = _search(client)["results"]
    activity_id = results[0]["candidate"]["activity_id"]

    def _engagement_factor() -> float:
        payload = _search(client)
        detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
        row = next(row for row in detail["ranking"] if row["activity_id"] == activity_id)
        return row["factors"]["engagement"]

    _respond(client, activity_id, response="interested")
    after_one = _engagement_factor()
    for _ in range(4):
        _respond(client, activity_id, response="interested")
    assert _engagement_factor() == after_one

    assert client.get("/v1/metrics").json()["activity_interested"] == 5


def test_bad_day_and_no_reason_move_nothing(client: TestClient) -> None:
    results = _search(client)["results"]
    a, b = results[0]["candidate"]["activity_id"], results[1]["candidate"]["activity_id"]
    assert (
        _respond(client, a, response="not_for_me", reason="bad_day").json()["preferences_updated"]
        == []
    )
    assert _respond(client, b, response="not_for_me").json()["preferences_updated"] == []
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )
    assert client.get("/v1/metrics").json()["activity_decline_reasons"] == {"bad_day": 1}


def test_a_declined_listing_is_held_back_on_the_next_search(client: TestClient) -> None:
    first = _search(client)["results"]
    top = first[0]["candidate"]["activity_id"]
    _respond(client, top, response="not_for_me", reason="prefer_something_else")
    second = _search(client)["results"]
    assert second[0]["candidate"]["activity_id"] != top
    assert top in [r["candidate"]["activity_id"] for r in second]  # held back, never removed
    assert [r["candidate"]["activity_id"] for r in second].index(top) > 0


def test_the_search_audit_records_the_breakdown_for_evaluators(client: TestClient) -> None:
    payload = _search(client)
    # The senior's own copy of the event carries counts, never the breakdown or the planner's
    # evidence; those live on the stored event an operator reads.
    assert "ranking" not in payload["audit_event"]["detail"]
    assert "agent" not in payload["audit_event"]["detail"]
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    assert detail["result_count"] == len(payload["results"])
    assert [row["activity_id"] for row in detail["ranking"]] == [
        r["candidate"]["activity_id"] for r in payload["results"]
    ]
    assert set(detail["ranking"][0]["factors"]) == {
        "intent",
        "preference",
        "engagement",
        "repetition",
        "context",
        "friction",
    }
    # Never on the card itself.
    assert "score_breakdown" not in payload["results"][0]


def test_each_search_audit_row_carries_the_sort_key_it_was_ordered_by(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """A row used to carry `total` and the factor contributions only, so the order could not be
    checked from the audit: the primary sort key (`tier`) and the tie-break (`matched_axes`) were
    nowhere on it. Each row now states the numbers `activity_search.sort_key_for` orders by, plus
    `coverage`; the event states the weights the contributions were multiplied by. All of it is
    evaluator-only."""
    from silverloop.activity_search import RANKING_WEIGHTS, rank_with_trace
    from silverloop.models import ActivityIntent

    intent = {"social_preference": "social", "time_window": "morning"}
    payload = _search(client, intent=intent)
    assert payload["results"], "this test needs a non-empty search"

    senior_copy = payload["audit_event"]["detail"]
    assert "ranking" not in senior_copy
    assert "ranking_weights" not in senior_copy

    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    assert detail["ranking_weights"] == RANKING_WEIGHTS

    # The same pure pipeline the search ran, over the same inputs, gives the sort key each row
    # must agree with.
    today = _current_day(client)
    with repository.sessions() as session:
        inputs = repository._ranking_inputs(session, DEMO_PERSON_ID, today=today)
    execution = rank_with_trace(
        inputs.catalogue,
        ActivityIntent.model_validate(intent),
        inputs.preferences,
        rain_forecast=inputs.rain_forecast,
        engagement=inputs.engagement,
        today=today,
    )
    by_id = {item.entry.ranked.candidate.activity_id: item for item in execution.scored}

    assert [row["activity_id"] for row in detail["ranking"]] == [
        item.ranked.candidate.activity_id for item in execution.final
    ]
    for row in detail["ranking"]:
        assert {"tier", "matched_axes", "coverage"} <= set(row)
        scored = by_id[row["activity_id"]]
        assert row["tier"] == scored.sort_key.tier
        assert row["matched_axes"] == scored.sort_key.matched_axes
        assert row["coverage"] == scored.entry.breakdown.coverage
        # No factor notes or raw values: the inspector is where those are read.
        assert all(isinstance(value, int | float) for value in row["factors"].values())
        assert "notes" not in row and "values" not in row


# ── A tap can only cite a query this run issued, about a listing it showed ────────────────────


def test_the_query_id_the_senior_receives_is_the_one_on_the_stored_search_event(
    client: TestClient,
) -> None:
    """It used to be minted in the return statement and stored nowhere, so nothing downstream
    could check a single thing about it beyond its shape."""
    payload = _search(client)
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    assert detail["query_id"] == payload["query_id"]


def test_a_query_id_this_run_never_issued_is_recorded_as_unverified_and_dropped(
    client: TestClient,
) -> None:
    results = _search(client)["results"]
    activity_id = results[0]["candidate"]["activity_id"]

    forged = _respond(
        client,
        activity_id,
        response="interested",
        query_id="query_0000000000000000",  # well-shaped, never issued
        rank_shown=1,
    )
    assert forged.status_code == 200, forged.text
    detail = forged.json()["audit_event"]["detail"]
    assert detail["query_id_verified"] is False
    assert detail["query_id"] is None, "an unverifiable label is not stored as if it were real"
    assert detail["rank_shown"] is None
    # The tap is still the person's: it is recorded, and the listing was genuinely shown.
    assert detail["shown"] is True
    assert forged.json()["response"] == "interested"


def test_a_rank_cannot_exceed_the_number_of_results_the_query_returned(
    client: TestClient,
) -> None:
    payload = _search(client)
    results = payload["results"]
    over = _respond(
        client,
        results[0]["candidate"]["activity_id"],
        response="not_for_me",
        reason="bad_day",
        query_id=payload["query_id"],
        rank_shown=50,
    )
    assert over.status_code == 200, over.text
    detail = over.json()["audit_event"]["detail"]
    assert detail["query_id_verified"] is True
    assert detail["rank_shown"] == len(results)

    # And the clamped value is what was stored, not only what was returned.
    stored = _stored_event_detail(client, over.json()["audit_event"]["event_id"])
    assert stored["rank_shown"] == len(results)


def test_a_verified_query_cited_without_a_rank_is_accepted_and_stays_rankless(
    client: TestClient,
) -> None:
    """`rank_shown` is optional on the contract. A tap citing a real `query_id` but no rank used
    to reach `min(None, n)` and fail with a 500; it is a valid tap and is recorded as one."""
    payload = _search(client)
    response = _respond(
        client,
        payload["results"][0]["candidate"]["activity_id"],
        response="not_for_me",
        reason="bad_day",
        query_id=payload["query_id"],
    )
    assert response.status_code == 200, response.text
    detail = response.json()["audit_event"]["detail"]
    assert detail["query_id_verified"] is True
    assert detail["query_id"] == payload["query_id"]
    assert detail["rank_shown"] is None
    assert detail["shown"] is True

    stored = _stored_event_detail(client, response.json()["audit_event"]["event_id"])
    assert stored["rank_shown"] is None


def test_interested_in_a_listing_the_filter_removed_is_recorded_but_never_planned(
    client: TestClient,
) -> None:
    """Audit I finding 5, reproduced: a 4.6 km listing the person's own "1 km or less" removed
    was planned onto their week. The filter encodes what they asked for; a hand-made request
    must not be able to overrule it. Never a 4xx -- the tap is still theirs."""
    payload = _search(client, intent={"max_distance_m": 1000})
    filtered_out = payload["filtered_out"]
    assert filtered_out, "this test needs the filter to have removed something"
    removed = filtered_out[0]["activity_id"]
    assert removed not in [r["candidate"]["activity_id"] for r in payload["results"]]

    response = _respond(
        client,
        removed,
        response="interested",
        query_id=payload["query_id"],
        rank_shown=1,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["planned"] is False
    assert body["week"] is None
    assert body["note"] == "Noted. This one wasn't among your results."
    assert body["audit_event"]["detail"]["shown"] is False
    assert body["audit_event"]["detail"]["query_id_verified"] is True

    week = client.get(f"/v1/people/{DEMO_PERSON_ID}/week").json()
    assert removed not in [entry["activity"]["activity_id"] for entry in week["entries"]]


def test_a_listing_shown_by_an_earlier_search_is_still_plannable(client: TestClient) -> None:
    """`shown` is about what this run offered this person, not about one query: a person who
    searched twice may answer the card from either search."""
    first = _search(client)
    today = _current_day(client)
    this_week = next(
        r
        for r in first["results"]
        if r["candidate"]["start_at"]
        and today
        <= date.fromisoformat(r["candidate"]["start_at"][:10])
        <= today + timedelta(days=6 - today.weekday())
    )
    _search(client, intent={"environment": "indoor"})  # a second, narrower search

    response = _respond(client, this_week["candidate"]["activity_id"], response="interested").json()
    assert response["audit_event"]["detail"]["shown"] is True
    assert response["audit_event"]["detail"]["query_id_verified"] is None
    assert response["planned"] is True


def test_outreach_and_search_read_the_same_series_engagement(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_activity_engagement` (the outreach path) and `_ranking_inputs` (the search path) both
    roll a decline up to its programme. The first used to spell the series key out inline, in a
    shape the shared roll-up no longer takes; both now key by `activity_search.series_keys_for`,
    so a decline on one session reaches its siblings identically on either path."""
    from silverloop.activity_search import series_keys_for

    keys = series_keys_for(repository.list_activities())
    sessions_by_series: dict[str, list[str]] = {}
    for activity_id, key in keys.items():
        sessions_by_series.setdefault(key, []).append(activity_id)
    siblings = next(ids for ids in sessions_by_series.values() if len(ids) >= 2)

    declined = _respond(client, siblings[0], response="not_for_me", reason="bad_day")
    assert declined.status_code == 200, declined.text

    today = _current_day(client)
    with repository.sessions() as session:
        run = repository._active_run(session, DEMO_PERSON_ID)
        outreach = repository._activity_engagement(session, DEMO_PERSON_ID, run.run_id)
        search = repository._ranking_inputs(session, DEMO_PERSON_ID, today=today).engagement

    assert outreach == search
    for sibling in siblings:
        assert outreach[sibling].not_for_me == 1, "the decline reaches every session of the series"

    # And it is one definition, not two that happen to agree: change what "the same programme"
    # means and both paths follow it. Here every session becomes its own programme, so the decline
    # stays on the session that was declined -- on the outreach path as on the search path.
    import silverloop.activity_search as activity_search

    monkeypatch.setattr(activity_search, "series_key", lambda candidate: candidate.activity_id)
    with repository.sessions() as session:
        run = repository._active_run(session, DEMO_PERSON_ID)
        outreach = repository._activity_engagement(session, DEMO_PERSON_ID, run.run_id)
        search = repository._ranking_inputs(session, DEMO_PERSON_ID, today=today).engagement
    assert outreach == search
    assert siblings[1] not in outreach or outreach[siblings[1]].not_for_me == 0


# ── The loop after the plan: how did it go, and was it any good ───────────────────────────────


def _plan_this_week(client: TestClient) -> dict:
    results = _search(client)["results"]
    today = _current_day(client)
    week_end = today + timedelta(days=6 - today.weekday())
    soonest = min(
        (
            r
            for r in results
            if r["candidate"]["start_at"]
            and today <= date.fromisoformat(r["candidate"]["start_at"][:10]) <= week_end
        ),
        key=lambda r: r["candidate"]["start_at"],
    )
    payload = _respond(client, soonest["candidate"]["activity_id"], response="interested").json()
    assert payload["planned"] is True
    entry = next(
        e
        for e in payload["week"]["entries"]
        if e["activity"]["activity_id"] == soonest["candidate"]["activity_id"]
    )
    return entry


def _advance_past(client: TestClient, day: date) -> None:
    while _current_day(client) <= day:
        _advance(client)


def test_follow_through_is_asked_only_once_the_day_has_passed(client: TestClient) -> None:
    entry = _plan_this_week(client)
    plan_id = entry["plan_id"]
    early = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/follow-through",
        json={"follow_through": "went"},
    )
    assert early.status_code == 422
    assert "not happened yet" in early.json()["detail"]

    _advance_past(client, date.fromisoformat(entry["day"]))
    week = client.get(f"/v1/people/{DEMO_PERSON_ID}/week").json()
    entries = {e["plan_id"]: e for e in week["entries"]}
    # The plan may have rolled out of the Mon-Sun window; if it is still visible it is awaiting.
    if plan_id in entries:
        assert entries[plan_id]["awaiting_report"] is True

    went = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/follow-through",
        json={"follow_through": "went"},
    )
    assert went.status_code == 200, went.text
    assert went.json()["follow_through"] == "went"
    repeat = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/follow-through",
        json={"follow_through": "did_not_go"},
    )
    assert repeat.status_code == 422


def test_enjoyment_requires_went_and_teaches_a_liked_aspect(client: TestClient) -> None:
    entry = _plan_this_week(client)
    plan_id = entry["plan_id"]
    too_early = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/enjoyment",
        json={"enjoyment": "enjoyed", "liked": ["people"]},
    )
    assert too_early.status_code == 422

    _advance_past(client, date.fromisoformat(entry["day"]))
    client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/follow-through",
        json={"follow_through": "went"},
    )
    enjoyed = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/enjoyment",
        json={"enjoyment": "enjoyed", "liked": ["people"]},
    )
    assert enjoyed.status_code == 200, enjoyed.text
    payload = enjoyed.json()
    # Read from the listing's own `social_shape` rather than asserted: "the people" is evidence
    # about company only when the catalogue actually says what the company is.
    assert [p["dimension"] for p in payload["preferences_updated"]] == ["social"]
    assert payload["preferences_updated"][0]["source"] == "inferred"
    again = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/enjoyment",
        json={"enjoyment": "okay", "liked": []},
    )
    assert again.status_code == 422

    metrics = client.get("/v1/metrics").json()
    assert metrics["activity_reports"] == 1
    assert metrics["activity_went"] == 1
    assert metrics["activity_enjoyed"] == 1


def test_did_not_go_blocks_enjoyment_and_teaches_nothing(client: TestClient) -> None:
    entry = _plan_this_week(client)
    plan_id = entry["plan_id"]
    _advance_past(client, date.fromisoformat(entry["day"]))
    assert (
        client.post(
            f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/follow-through",
            json={"follow_through": "did_not_go"},
        ).status_code
        == 200
    )
    blocked = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/enjoyment",
        json={"enjoyment": "enjoyed", "liked": ["people"]},
    )
    assert blocked.status_code == 422
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )


# ── The preference key includes source; expiry is absence, not resurrection ──────────────────


def test_a_decline_and_an_enjoyment_on_the_same_value_both_persist(
    repository: SqlAlchemyRepository,
) -> None:
    from datetime import UTC, datetime

    from silverloop.models import Enjoyment, LikedAspect

    now = datetime.now(UTC)
    candidates = repository.list_activities()
    near = next(c for c in candidates if c.distance_m is not None and c.distance_m < 2000)
    with repository.sessions.begin() as session:
        repository._apply_activity_decline(
            session, DEMO_PERSON_ID, f"activity:{near.activity_id}", "too_far", now
        )
        repository._apply_activity_enjoyment(
            session, DEMO_PERSON_ID, near, Enjoyment.ENJOYED, [LikedAspect.LOCATION], now
        )
    with repository.sessions() as session:
        rows = list(
            session.scalars(
                select(ActivityDimensionPreferenceRow).where(
                    ActivityDimensionPreferenceRow.dimension == "distance",
                )
            )
        )
    assert sorted(row.source for row in rows) == ["decline_reason", "inferred"]
    # The two point in opposite directions on the same ordinal axis and neither may reset the
    # other's accumulated evidence -- which is why they keep separate source tiers.
    assert {row.source: row.direction for row in rows} == {
        "decline_reason": "lower",
        "inferred": "higher",
    }


def test_a_stated_preference_can_be_temporary_and_then_is_simply_absent(
    client: TestClient,
) -> None:
    today = _current_day(client)
    stated = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/tai_chi",
        json={
            "stance": "avoid",
            "until": (today + timedelta(days=1)).isoformat(),
            "stated_text": "no classes this week",
        },
    )
    assert stated.status_code == 200, stated.text
    preference = stated.json()["preference"]
    assert preference["source"] == "senior_statement"
    assert preference["confirmed"] is True
    assert preference["strength"] == -1.0
    assert preference["expires_at"] is not None
    assert preference["stated_text"] == "no classes this week"

    held = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"]
    assert [(p["dimension"], p["value"]) for p in held] == [("activity_type", "tai_chi")]
    ranked_while_held = _search(client)["results"]
    assert ranked_while_held[0]["candidate"]["activity_type"] != "tai_chi"

    for _ in range(3):
        _advance(client)
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )


def test_a_past_until_day_is_refused(client: TestClient) -> None:
    today = _current_day(client)
    refused = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/tai_chi",
        json={"stance": "avoid", "until": (today - timedelta(days=1)).isoformat()},
    )
    assert refused.status_code == 422


def test_forget_retracts_learned_and_stated_rows_alike(client: TestClient) -> None:
    """ADR 0006. `forget` used to delete the rows. It now stamps `superseded_by` instead: the
    person sees exactly what they saw before -- nothing -- but the record of what Care+ once
    believed, and of them striking it out, is not quietly rewritten, and the next tap on that key
    starts a fresh belief from zero rather than resurrecting a count they had erased."""
    results = _search(client)["results"]
    walk = next(r for r in results if r["candidate"]["activity_type"] == "walking")
    _respond(client, walk["candidate"]["activity_id"], response="not_for_me", reason="not_for_me")
    client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/walking",
        json={"stance": "avoid"},
    )
    held = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"]
    # "That's right" consumes the inferred row rather than sitting beside it, so the person's own
    # words are the one belief on that key -- see A-F6.
    assert [(p["dimension"], p["value"]) for p in held] == [("activity_type", "walking")]
    forgotten = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/walking",
        json={"stance": "forget"},
    )
    assert forgotten.status_code == 200
    assert forgotten.json()["preference"] is None
    assert forgotten.json()["audit_event"]["detail"]["removed_rows"] == 1
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )


def test_a_forgotten_belief_is_retracted_rather_than_deleted(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """The row survives, stamped, and is invisible to every reader. Deleting looked identical to
    the person and rewrote the audit trail; under evidence counts it also left nothing to stop the
    very next tap resurrecting the belief from a count they believed they had erased."""
    client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/walking",
        json={"stance": "avoid"},
    )
    client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/walking",
        json={"stance": "forget"},
    )
    with repository.sessions() as session:
        rows = list(
            session.scalars(
                select(ActivityDimensionPreferenceRow).where(
                    ActivityDimensionPreferenceRow.dimension == "activity_type",
                    ActivityDimensionPreferenceRow.value == "walking",
                )
            )
        )
    assert len(rows) == 1
    assert rows[0].superseded_by is not None
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )


def test_new_evidence_on_an_expired_key_starts_again_rather_than_resurrecting(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """An expired row keeps its `(dimension, value, source)` key. A later decline on that key
    must start from one observation with no expiry -- never inherit the lapsed count."""
    from datetime import UTC, datetime

    results = _search(client)["results"]
    far = [r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000]
    for entry in far[:3]:
        _respond(client, entry["candidate"]["activity_id"], response="not_for_me", reason="too_far")
    with repository.sessions.begin() as session:
        session.execute(
            update(ActivityDimensionPreferenceRow)
            .where(ActivityDimensionPreferenceRow.dimension == "distance")
            .values(expires_at=datetime(2000, 1, 1, tzinfo=UTC))
        )
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )

    revived = _respond(
        client, far[3]["candidate"]["activity_id"], response="not_for_me", reason="too_far"
    ).json()["preferences_updated"][0]
    assert revived["observations"] == 1
    assert revived["expires_at"] is None
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"][0][
            "observations"
        ]
        == 1
    )


# ── Append-only, on the offline engine too ────────────────────────────────────────────────────


def test_sqlite_migration_makes_offer_responses_append_only(tmp_path) -> None:  # noqa: ANN001
    database_url = f"sqlite+pysqlite:///{tmp_path / 'responses.db'}"
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    repository.reset()
    activity_id = repository.list_activities()[0].activity_id
    repository.respond_to_activity(activity_id, "not_for_me", actor="test")
    with (
        pytest.raises(DatabaseError, match="append-only evidence"),
        repository.engine.begin() as connection,
    ):
        connection.execute(update(ActivityOfferResponseRow).values(response="interested"))
    repository.close()


# ── Ownership ─────────────────────────────────────────────────────────────────────────────────

JWT_SECRET = "activity-responses-ownership-test-secret"
SUPABASE_URL = "https://project.supabase.co"
PERSON_B = "person-b"
SENIOR_A = "senior-a-sub"
SENIOR_B = "senior-b-sub"


def _token(sub: str, role: str = "senior") -> str:
    return jwt.encode(
        {
            "sub": sub,
            "iss": SUPABASE_URL + "/auth/v1",
            "aud": "authenticated",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "app_metadata": {"role": role},
        },
        JWT_SECRET,
        algorithm="HS256",
    )


def _bearer(sub: str, role: str = "senior") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(sub, role)}"}


@pytest.fixture
def two_person_repo() -> Iterator[SqlAlchemyRepository]:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()
    instance.reset()
    instance.reset(person_id=PERSON_B, allow_new_person=True)
    instance.upsert_person_link(SENIOR_A, DEMO_PERSON_ID, "test")
    instance.upsert_person_link(SENIOR_B, PERSON_B, "test")
    yield instance
    instance.close()


@pytest.fixture
def auth_client(two_person_repo: SqlAlchemyRepository) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=True,
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=JWT_SECRET,
    )
    return TestClient(create_app(two_person_repo, settings=settings, migrate_on_start=False))


def test_a_response_is_always_the_callers_own(
    auth_client: TestClient, two_person_repo: SqlAlchemyRepository
) -> None:
    activity_id = two_person_repo.list_activities()[0].activity_id
    response = auth_client.post(
        f"/v1/activities/{activity_id}/response",
        json={"response": "interested"},
        headers=_bearer(SENIOR_B),
    )
    assert response.status_code == 200, response.text
    with two_person_repo.sessions() as session:
        rows = list(session.scalars(select(ActivityOfferResponseRow)))
    assert [row.person_id for row in rows] == [PERSON_B]
    unknown = auth_client.post(
        "/v1/activities/no-such-listing/response",
        json={"response": "interested"},
        headers=_bearer(SENIOR_B),
    )
    assert unknown.status_code == 404


def test_another_persons_plan_and_another_persons_path_are_both_404(
    auth_client: TestClient, two_person_repo: SqlAlchemyRepository
) -> None:
    activity = next(a for a in two_person_repo.list_activities() if a.start_at is not None)
    from silverloop.local_time import local_date

    plan = two_person_repo.plan_activity(
        activity.activity_id, local_date(activity.start_at), "test", person_id=DEMO_PERSON_ID
    )
    plan_id = plan.entries[0].plan_id

    foreign_plan = auth_client.post(
        f"/v1/people/{PERSON_B}/week/{plan_id}/follow-through",
        json={"follow_through": "went"},
        headers=_bearer(SENIOR_B),
    )
    assert foreign_plan.status_code == 404
    wrong_person_path = auth_client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{plan_id}/follow-through",
        json={"follow_through": "went"},
        headers=_bearer(SENIOR_B),
    )
    # `check_person_scope` answers a senior on someone else's path with 404, by design -- the
    # route must not be an existence oracle for another person (see docs/api.md, "Auth").
    assert wrong_person_path.status_code == 404
    foreign_enjoyment = auth_client.post(
        f"/v1/people/{PERSON_B}/week/{plan_id}/enjoyment",
        json={"enjoyment": "enjoyed", "liked": []},
        headers=_bearer(SENIOR_B),
    )
    assert foreign_enjoyment.status_code == 404
    foreign_preference = auth_client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/distance/far",
        json={"stance": "avoid"},
        headers=_bearer(SENIOR_B),
    )
    # Same 404-not-403 rule for the preference route: a senior on someone else's path.
    assert foreign_preference.status_code == 404
    coordinator = auth_client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/distance/far",
        json={"stance": "avoid"},
        headers=_bearer("coordinator-sub", role="coordinator"),
    )
    assert coordinator.status_code == 403


def test_cooldown_constant_is_the_one_the_ranker_uses() -> None:
    assert DECLINE_COOLDOWN_DAYS >= 7


# ── Consent pauses inference; input bounds; provenance; concurrency; redaction ────────────────


def _set_consent(client: TestClient, active: bool) -> None:
    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/consent",
        json={"active": active, "reason": "Test toggles consent."},
    )
    assert response.status_code == 200, response.text


def test_withdrawing_consent_pauses_inference_but_not_the_person_s_own_voice(
    client: TestClient,
) -> None:
    """The deterministic rule: while consent is withdrawn Care+ still answers a search and
    still records the tap, but infers nothing new from it. What the person states outright is
    still theirs to state."""
    _set_consent(client, False)
    results = _search(client)["results"]  # asking is not outreach; it is still answered
    assert results
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    response = _respond(
        client, far["candidate"]["activity_id"], response="not_for_me", reason="too_far"
    )
    assert response.status_code == 200, response.text
    assert response.json()["preferences_updated"] == []
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )

    stated = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/distance/near",
        json={"stance": "prefer", "stated_text": "close to home please"},
    )
    assert stated.status_code == 200, stated.text
    dimensions = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()[
        "dimensions"
    ]
    assert [(d["dimension"], d["value"], d["source"]) for d in dimensions] == [
        ("distance", "near", "senior_statement")
    ]

    _set_consent(client, True)
    again = _respond(
        client, far["candidate"]["activity_id"], response="not_for_me", reason="too_far"
    )
    assert [p["dimension"] for p in again.json()["preferences_updated"]] == ["distance"]


def test_a_preference_value_is_bounded_and_printable(client: TestClient) -> None:
    """The path itself must not carry a paragraph or a control character into storage.

    The accepted control is a real `ontology.ActivityType` value: every dimension's vocabulary is
    closed now, so anything outside it would be refused for a different reason and would stop
    testing printability at all.
    """
    too_long = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/{'A' * 200}",
        json={"stance": "prefer"},
    )
    assert too_long.status_code == 422
    control_chars = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/tai%0Achi",
        json={"stance": "prefer"},
    )
    assert control_chars.status_code == 422
    fine = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/tai_chi",
        json={"stance": "prefer"},
    )
    assert fine.status_code == 200, fine.text


def test_intent_text_fields_are_bounded_at_the_contract(client: TestClient) -> None:
    long_language = client.post("/v1/activities/search", json={"intent": {"language": "x" * 41}})
    assert long_language.status_code == 422
    long_raw = client.post("/v1/activities/search", json={"intent": {"raw_text": "x" * 401}})
    assert long_raw.status_code == 422
    assert _respond(client, "activity-x", response="interested", rank_shown=999).status_code == 422


def test_the_server_states_parser_provenance_not_the_client(client: TestClient) -> None:
    payload = client.post(
        "/v1/activities/search", json={"intent": {"parsed_by": "llm", "environment": "indoor"}}
    ).json()
    assert payload["audit_event"]["detail"]["parsed_by"] == "chips"
    assert payload["audit_event"]["detail"]["intent_mode"] == "chips"
    assert payload["intent"]["parsed_by"] == "chips"


def test_a_double_tap_racing_to_the_same_row_is_a_conflict_not_a_crash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import IntegrityError

    def _race(*args: object, **kwargs: object) -> object:
        raise IntegrityError("INSERT plan_follow_through", {}, Exception("unique"))

    monkeypatch.setattr(SqlAlchemyRepository, "record_planned_follow_through", _race)
    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/plan-1/follow-through",
        json={"follow_through": "went"},
    )
    assert response.status_code == 409
    assert "already recorded" in response.json()["detail"]


def test_the_audit_never_carries_the_person_s_note_only_that_one_exists(
    client: TestClient,
) -> None:
    entry = _plan_this_week(client)
    _advance_past(client, date.fromisoformat(entry["day"]))
    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{entry['plan_id']}/follow-through",
        json={"follow_through": "went", "note": "My neighbour Mrs Tan drove me there."},
    )
    assert response.status_code == 200, response.text
    detail = response.json()["audit_event"]["detail"]
    assert detail["note_present"] is True
    assert "note" not in detail
    assert "Mrs Tan" not in str(detail)


def test_the_search_audit_records_disagreement_when_a_planner_reorders(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the flag used to be computed after `ranked` was rebound to the planner's own
    order, so it compared the planner with itself and could never be false."""
    from datetime import UTC, datetime

    from silverloop.agent.planner import ActivityPlanRun

    def _reversing_planner(context, *, settings, fallback_order):  # noqa: ANN001, ANN202
        return ActivityPlanRun(
            evidence_id="agent_test",
            agent_version="test-planner",
            mode="agent",
            started_at=datetime.now(UTC),
            max_iterations=1,
            selected_order=list(reversed(fallback_order)),
            used_agent=True,
        )

    monkeypatch.setattr("silverloop.sql_repository.plan_activity_ranking", _reversing_planner)
    payload = _search(client)
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    assert detail["planner_mode"] == "agent"
    assert detail["planner_contested"] is True
    assert detail["planner_agreed_with_ranker"] is False
    assert detail["agent"]["mode"] == "agent"
    assert payload["results"][0]["selected_by"] == "agent"
    # Reordering is not narrowing: every permitted listing is still offered.
    assert not [f for f in payload["filtered_out"] if f["rule"] == "planner_narrowed"]
    assert len(payload["results"]) == detail["result_count"] == len(detail["ranking"])


def test_the_search_audit_reports_no_agreement_when_no_planner_ran(client: TestClient) -> None:
    """Offline -- the suite's own configuration -- the planner never runs, so there is no
    planner to have agreed with anything. Reporting `True` invented an agreement between the
    deterministic ranker and itself, and `planner_contested` claimed a contest that never
    happened: on a shared dashboard that inflates the agreement numerator with rows the planner
    was absent from. `None` is the only honest answer, and it is the one the outreach aggregate
    already gives (it counts only `mode == "agent"` runs).
    """
    payload = _search(client)
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])

    assert detail["planner_mode"] == "fallback_disabled"
    assert detail["agent"]["mode"] == "fallback_disabled"
    assert detail["planner_agreed_with_ranker"] is None
    assert detail["planner_contested"] is None
    # The results themselves are unaffected: the deterministic order still stands and is still
    # attributed to the ranker.
    assert payload["results"][0]["selected_by"] == "ranker"


def test_a_search_records_snapshot_stale_false_when_nothing_moves(client: TestClient) -> None:
    payload = _search(client)
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    assert detail["snapshot_stale"] is False


def test_a_reset_racing_the_ranking_planner_is_marked_stale_on_the_new_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`search_activities` opens no transaction across the ranking planner call, so a
    `/v1/demo/reset` can genuinely land in the gap between the read phase this search planned
    against and the write phase that records it. The write phase must notice its snapshot no
    longer describes the active run, mark the audit row accordingly, and attach that row to the
    run that is active now -- never to the one the reset just retired."""
    from datetime import UTC, datetime

    from silverloop.agent.planner import ActivityPlanRun

    def _resetting_planner(context, *, settings, fallback_order):  # noqa: ANN001, ANN202
        assert client.post("/v1/demo/reset").status_code == 200
        return ActivityPlanRun(
            evidence_id="agent_test",
            agent_version="test-planner",
            mode="agent",
            started_at=datetime.now(UTC),
            max_iterations=1,
            selected_order=list(reversed(fallback_order)),
        )

    monkeypatch.setattr("silverloop.sql_repository.plan_activity_ranking", _resetting_planner)
    payload = _search(client)

    # `_stored_search_detail` looks the event up among the *current* active run's events, via
    # `/v1/simulation/events`; finding it there at all is already proof the row followed the
    # reset rather than being written against the run that no longer exists.
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    assert detail["snapshot_stale"] is True
    # The planner ran in agent mode, but its answer never reached the person: no agreement or
    # contest is claimed for it.
    assert detail["planner_mode"] == "agent"
    assert detail["planner_agreed_with_ranker"] is None
    assert detail["planner_contested"] is None


def test_a_day_advancing_mid_search_discards_the_planners_reorder(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unlike a reset, an advance keeps the same run alive but moves `current_day` -- a second
    way the world can shift out from under a planner call that holds no lock. The write phase
    must still mark the search stale and fall back to the deterministic order computed before
    the planner ran, discarding whatever reordering it proposed."""
    from datetime import UTC, datetime

    from silverloop.agent.planner import ActivityPlanRun

    def _advancing_planner(context, *, settings, fallback_order):  # noqa: ANN001, ANN202
        _advance(client)
        return ActivityPlanRun(
            evidence_id="agent_test",
            agent_version="test-planner",
            mode="agent",
            started_at=datetime.now(UTC),
            max_iterations=1,
            selected_order=list(reversed(fallback_order)),
        )

    monkeypatch.setattr("silverloop.sql_repository.plan_activity_ranking", _advancing_planner)
    payload = _search(client)
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    assert detail["snapshot_stale"] is True

    # `ranking` is the deterministic account computed before the planner ever ran, and is never
    # rewritten by a reorder -- it is the ground truth `result_ids` must match once the stale
    # reorder is discarded.
    deterministic_order = [row["activity_id"] for row in detail["ranking"]]
    assert detail["result_ids"] == deterministic_order
    assert [r["candidate"]["activity_id"] for r in payload["results"]] == deterministic_order


def test_a_stale_snapshot_claims_neither_agreement_nor_contest(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the stale reorder is discarded, `ranked` is the deterministic order again, so the
    agreement comparison would always read `True`: the ranker agreeing with itself, counted as a
    planner agreement on a row whose planner answer the person never saw. `planner_contested`
    would likewise report a contest whose outcome was thrown away. Both are `None`, as for a
    run where no planner ran at all."""
    from datetime import UTC, datetime

    from silverloop.agent.planner import ActivityPlanRun

    def _advancing_agent(context, *, settings, fallback_order):  # noqa: ANN001, ANN202
        _advance(client)
        return ActivityPlanRun(
            evidence_id="agent_test",
            agent_version="test-planner",
            mode="agent",
            started_at=datetime.now(UTC),
            max_iterations=1,
            selected_order=list(reversed(fallback_order)),
        )

    monkeypatch.setattr("silverloop.sql_repository.plan_activity_ranking", _advancing_agent)
    payload = _search(client)
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    assert len(detail["ranking"]) >= 2, "the reorder must be a genuine contest for this to bite"

    assert detail["snapshot_stale"] is True
    assert detail["planner_mode"] == "agent"
    assert detail["agent"]["mode"] == "agent"
    assert detail["planner_agreed_with_ranker"] is None
    assert detail["planner_contested"] is None


def test_the_ranking_planner_call_holds_no_database_session_open(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a transaction opened by `search_activities` were still open while the ranking planner
    is consulted, a second write transaction opened here, from inside the planner call, would
    conflict with it: on the shared, single-connection SQLite pool this suite uses, SQLite
    refuses to begin a transaction while one is already active on the same connection. Succeeding
    is the proof that no session survives past read phase 2."""
    from datetime import UTC, datetime

    from silverloop.agent.planner import ActivityPlanRun

    def _session_opening_planner(context, *, settings, fallback_order):  # noqa: ANN001, ANN202
        with repository.sessions.begin() as session:
            run = repository._active_run(session, DEMO_PERSON_ID)
            # A genuine write, not just a read: it is the write-transaction lock, not a
            # read lock, that a leaked session from `search_activities` would still be
            # holding on this row.
            run.current_day = run.current_day + timedelta(days=0)
            session.flush()
        return ActivityPlanRun(
            evidence_id="agent_test",
            agent_version="test-planner",
            mode="agent",
            started_at=datetime.now(UTC),
            max_iterations=1,
            selected_order=list(fallback_order),
        )

    monkeypatch.setattr("silverloop.sql_repository.plan_activity_ranking", _session_opening_planner)
    # The assertion is really inside `_session_opening_planner`: opening and committing a second
    # write transaction there must not raise. A 200 response is confirmation the whole search
    # still completed normally around it.
    payload = _search(client)
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    assert detail["snapshot_stale"] is False


# ── A demo reset starts the story over ────────────────────────────────────────────────────────


def test_a_reset_rewinds_the_calendar_and_the_story_with_it(client: TestClient) -> None:
    """A reset returns the simulated calendar to the fixture's anchor day. A "not for me" from a
    later day of the previous run would then sit in the new run's future and hold the listing
    back until the clock caught up; engagement is read per run, and learned kinds of activity
    are cleared with the story, so neither can happen."""
    results = _search(client)["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    for _ in range(5):
        _advance(client)
    assert (
        _respond(
            client, far["candidate"]["activity_id"], response="not_for_me", reason="too_far"
        ).status_code
        == 200
    )

    def _ranking_row(activity_id: str) -> dict:
        payload = _search(client)
        detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
        return next(row for row in detail["ranking"] if row["activity_id"] == activity_id)

    held_back = _ranking_row(far["candidate"]["activity_id"])
    assert held_back["factors"]["repetition"] < 0

    assert client.post("/v1/demo/reset").status_code == 200
    fresh = _ranking_row(far["candidate"]["activity_id"])
    assert fresh["factors"]["repetition"] == 0
    assert fresh["factors"]["engagement"] == 0
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )


def test_a_reset_keeps_a_stated_preference_but_only_stales_an_inferred_one(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """ADR 0004: a stated preference is the person's own words, a standing instruction like an
    outreach mute (`candidate_preferences`), and is not scoped to the run it was said in -- it
    survives a reset exactly like a mute does. An inferred preference only means something
    against the simulated history that produced it, so a reset makes it stale (absent from every
    reader), but -- unlike before this repository stopped deleting `activity_dimension_preferences`
    on reset outright -- the row itself is not destroyed."""
    results = _search(client)["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    _respond(client, far["candidate"]["activity_id"], response="not_for_me", reason="too_far")
    stated = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/environment/outdoor",
        json={"stance": "avoid"},
    )
    assert stated.status_code == 200, stated.text

    held = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"]
    assert {(p["dimension"], p["value"]) for p in held} == {
        ("distance", "lower"),
        ("environment", "outdoor"),
    }
    with repository.sessions() as session:
        assert len(list(session.scalars(select(ActivityDimensionPreferenceRow)))) == 2

    assert client.post("/v1/demo/reset").status_code == 200

    # Not deleted -- reset no longer destroys this table.
    with repository.sessions() as session:
        assert len(list(session.scalars(select(ActivityDimensionPreferenceRow)))) == 2

    held_after_reset = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()[
        "dimensions"
    ]
    assert [(p["dimension"], p["value"]) for p in held_after_reset] == [("environment", "outdoor")]


def test_a_reset_does_not_resurrect_a_time_boxed_statement_that_had_already_lapsed(
    client: TestClient,
) -> None:
    """`expires_at` is compared against the simulated calendar, not the wall clock, and a reset
    rewinds that calendar to the fixture's anchor day -- earlier than any day the story has
    reached so far. State a preference timeboxed to lapse in 3 days, let 10 pass so it genuinely
    has lapsed, then reset: `current_day` falls back behind the `until` date again, and a
    calendar-only expiry check would read it as not-yet-expired and bring it back. This is the
    exact "wrong calendar" failure the original blanket delete on reset existed to prevent, and a
    time-boxed statement being run-scoped (ADR 0004) is what stops it now."""
    today = _current_day(client)
    stated = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/tai_chi",
        json={"stance": "avoid", "until": (today + timedelta(days=3)).isoformat()},
    )
    assert stated.status_code == 200, stated.text

    for _ in range(10):
        _advance(client)
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )

    assert client.post("/v1/demo/reset").status_code == 200

    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"] == []
    )


def test_a_legacy_null_run_id_inferred_row_drops_out_after_reset(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """Every row this table held before the `run_id` backfill (Alembic `c2725d7de5df`) -- or one
    backfilled for a person with no active run at the time -- has `run_id = NULL` without the
    repository ever having written it that way. `NULL` only means "standing" for a
    `senior_statement` row with no `expires_at`; misreading it as standing for a `decline_reason`
    row would make an inferred belief permanent. Inserted directly, bypassing every repository
    write path, to prove the *read* path (`_preference_inactive`) gets this right on its own,
    not merely because every write path happens to stamp `run_id`."""
    from datetime import UTC, datetime

    with repository.sessions.begin() as session:
        session.add(
            ActivityDimensionPreferenceRow(
                preference_id="legacy-inferred",
                person_id=DEMO_PERSON_ID,
                dimension="distance",
                value="far",
                strength=-0.3,
                source="decline_reason",
                confirmed=False,
                observations=1,
                updated_at=datetime.now(UTC),
                run_id=None,
            )
        )

    held_before = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()[
        "dimensions"
    ]
    assert held_before == []

    assert client.post("/v1/demo/reset").status_code == 200

    held_after = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()[
        "dimensions"
    ]
    assert held_after == []


def test_a_legacy_null_run_id_time_boxed_statement_drops_out_after_reset(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """Same gap as above, for the other shape `NULL` can be misread on: a time-boxed
    `senior_statement` row (`expires_at` set) written before the backfill existed. Left standing
    by accident, this is the exact resurrection bug ADR 0004 exists to close -- a promise that
    predates run-scoping entirely must not outlive the run it happened to be read in."""
    from datetime import UTC, datetime, timedelta

    with repository.sessions.begin() as session:
        run = repository._active_run(session, DEMO_PERSON_ID)
        session.add(
            ActivityDimensionPreferenceRow(
                preference_id="legacy-timeboxed",
                person_id=DEMO_PERSON_ID,
                dimension="category",
                value="Group class",
                strength=-1.0,
                source="senior_statement",
                confirmed=True,
                observations=1,
                updated_at=datetime.now(UTC),
                expires_at=datetime.combine(
                    run.current_day + timedelta(days=3), datetime.min.time(), tzinfo=UTC
                ),
                run_id=None,
            )
        )

    held_before = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()[
        "dimensions"
    ]
    assert held_before == []

    assert client.post("/v1/demo/reset").status_code == 200

    held_after = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()[
        "dimensions"
    ]
    assert held_after == []


def test_an_integrity_error_that_is_not_a_duplicate_is_still_an_internal_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import IntegrityError

    def _broken(*args: object, **kwargs: object) -> object:
        raise IntegrityError("INSERT", {}, Exception("NOT NULL constraint failed: x.y"))

    monkeypatch.setattr(SqlAlchemyRepository, "record_planned_follow_through", _broken)
    # Not converted to a 409: the test client re-raises what the app would have answered as 500.
    with pytest.raises(IntegrityError):
        client.post(
            f"/v1/people/{DEMO_PERSON_ID}/week/plan-1/follow-through",
            json={"follow_through": "went"},
        )


# ── Red-team fixes: the loop cannot be gamed or confused ──────────────────────────────────────


def _in_week_listing(client: TestClient) -> dict:
    today = _current_day(client)
    week_end = today - timedelta(days=today.weekday()) + timedelta(days=6)
    for result in _search(client)["results"]:
        start = result["candidate"]["start_at"]
        if start is None:
            continue
        day = date.fromisoformat(start[:10])
        if today <= day <= week_end:
            return result["candidate"]
    pytest.skip("no listing inside the current week on this fixture day")


def test_a_listing_is_planned_on_its_own_day_never_a_day_the_client_picks(
    client: TestClient,
) -> None:
    listing = _in_week_listing(client)
    yesterday = (_current_day(client) - timedelta(days=1)).isoformat()
    response = _respond(client, listing["activity_id"], response="interested", day=yesterday).json()
    if response["planned"]:
        assert response["plan_day"] == listing["start_at"][:10]
        assert response["plan_day"] >= _current_day(client).isoformat()
    # And the week route refuses a day already gone outright.
    week = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week",
        json={"activity_id": listing["activity_id"], "day": yesterday},
    )
    assert week.status_code == 422


def test_a_fully_booked_listing_is_noted_not_planned(client: TestClient) -> None:
    from silverloop.db_models import ActivityCandidateRow

    listing = _in_week_listing(client)
    repository: SqlAlchemyRepository = client.app.state.repository  # type: ignore[attr-defined]
    with repository.sessions.begin() as session:
        session.get(ActivityCandidateRow, listing["activity_id"]).availability = "full"
    response = _respond(client, listing["activity_id"], response="interested").json()
    assert response["planned"] is False
    assert "fully booked" in response["note"]
    assert not [
        e
        for e in client.get(f"/v1/people/{DEMO_PERSON_ID}/week").json()["entries"]
        if e["activity"]["activity_id"] == listing["activity_id"]
    ]


def test_an_interested_after_a_not_for_me_ends_the_cooldown(client: TestClient) -> None:
    listing = _search(client)["results"][0]["candidate"]
    _respond(client, listing["activity_id"], response="not_for_me")
    _respond(client, listing["activity_id"], response="interested")
    payload = _search(client)
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    row = next(r for r in detail["ranking"] if r["activity_id"] == listing["activity_id"])
    assert row["factors"]["repetition"] == 0


def test_a_reason_means_nothing_on_an_interested_reply(client: TestClient) -> None:
    listing = _search(client)["results"][0]["candidate"]
    response = _respond(client, listing["activity_id"], response="interested", reason="too_far")
    assert response.status_code == 200
    assert response.json()["audit_event"]["detail"]["reason"] is None
    assert client.get("/v1/metrics").json()["activity_decline_reasons"] == {}


def test_a_stated_value_must_belong_to_its_dimension(client: TestClient) -> None:
    """Every dimension is closed, and the content axis is `activity_type`.

    The route used to accept any 160-character string on `category`, so a person could state a
    preference for "Line dancing" and have it stored as a confirmed belief that no candidate could
    ever match -- and then read back to them on the Privacy screen as though it meant something.

    "Either" is refused on intensity and company for the same reason: a listing is light or
    moderate, never "either", so the row could match nothing.
    """
    for dimension, value in (
        ("distance", "9"),
        ("social", "near"),
        ("intensity", "banana"),
        ("intensity", "either"),
        ("social", "either"),
        ("activity_type", "Line%20dancing"),
        ("activity_type", "other"),
    ):
        response = client.put(
            f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/{dimension}/{value}",
            json={"stance": "prefer"},
        )
        assert response.status_code == 422, (dimension, value)
    assert (
        client.put(
            f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/tai_chi",
            json={"stance": "prefer"},
        ).status_code
        == 200
    )


def test_a_deprecated_dimension_refuses_a_new_statement_but_still_allows_a_forget(
    client: TestClient,
) -> None:
    """`CATEGORY` holds a format label, so one belief about it covered nine unrelated programmes.
    Nothing may write another -- but a person must still be able to delete one this product
    already holds about them, which is why the member is deprecated rather than removed."""
    refused = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/category/Group%20class",
        json={"stance": "prefer"},
    )
    assert refused.status_code == 422
    forgettable = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/category/Group%20class",
        json={"stance": "forget"},
    )
    assert forgettable.status_code == 200


def test_a_change_of_mind_is_a_new_statement_not_a_stronger_old_one(client: TestClient) -> None:
    base = f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/distance/near"
    client.put(base, json={"stance": "avoid", "stated_text": "no walks"})
    flipped = client.put(base, json={"stance": "prefer"}).json()["preference"]
    assert flipped["strength"] > 0
    assert flipped["observations"] == 1
    assert flipped["stated_text"] is None


def test_a_query_id_the_server_never_issued_is_dropped(client: TestClient) -> None:
    listing = _search(client)["results"][0]["candidate"]
    response = _respond(
        client, listing["activity_id"], response="interested", query_id="<img src=x>"
    )
    assert response.status_code == 200
    assert response.json()["audit_event"]["detail"]["query_id"] is None


def test_unparsed_terms_are_bounded_at_the_contract(client: TestClient) -> None:
    response = client.post("/v1/activities/search", json={"intent": {"unparsed_terms": ["x" * 41]}})
    assert response.status_code == 422
    response = client.post("/v1/activities/search", json={"intent": {"unparsed_terms": ["x"] * 21}})
    assert response.status_code == 422


# ── Series, verdicts and ratification ─────────────────────────────────────────────────────────


def _sessions_of_one_series(client: TestClient) -> list[dict]:
    """Two sessions of the same programme -- same provider, same title, different days."""
    results = _search(client)["results"]
    by_series: dict[tuple[str, str], list[dict]] = {}
    for entry in results:
        key = (entry["candidate"]["provider"], entry["candidate"]["title"])
        by_series.setdefault(key, []).append(entry)
    return next(entries for entries in by_series.values() if len(entries) >= 2)


def test_a_not_for_me_on_one_session_holds_back_the_whole_programme(client: TestClient) -> None:
    """B-F12. A programme with sessions on Monday, Wednesday and Friday is three `activity_id`s
    and one thing to go to. Keyed per session, "not for me" on Monday's chair class left
    Wednesday's and Friday's untouched, so the person was shown the identical class twice more
    that week -- the cooldown was real and reached nothing."""
    sessions = _sessions_of_one_series(client)
    declined, sibling = sessions[0]["candidate"], sessions[1]["candidate"]

    def _factors_for(activity_id: str) -> dict:
        payload = _search(client)
        detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
        return next(row for row in detail["ranking"] if row["activity_id"] == activity_id)[
            "factors"
        ]

    before = _factors_for(sibling["activity_id"])
    _respond(client, declined["activity_id"], response="not_for_me", reason="bad_day")
    after = _factors_for(sibling["activity_id"])

    assert before["repetition"] == 0.0
    assert after["repetition"] < 0.0


def test_a_listing_the_person_attended_and_disliked_is_never_promoted_with_a_positive_line(
    client: TestClient,
) -> None:
    """D-§9. `ActivityEngagement` had no field that could hold "I went, and it was not for me",
    so the best-grounded thing anyone can say about a listing was counted nowhere -- and `went`
    alone then pushed the card back up with "You went to this one before." printed on it as a
    reason it suited them."""
    entry = _plan_this_week(client)
    activity_id = entry["activity"]["activity_id"]
    _advance_past(client, date.fromisoformat(entry["day"]))
    client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{entry['plan_id']}/follow-through",
        json={"follow_through": "went"},
    )
    client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{entry['plan_id']}/enjoyment",
        json={"enjoyment": "not_for_me", "liked": []},
    )

    payload = _search(client)
    shown = next(
        (r for r in payload["results"] if r["candidate"]["activity_id"] == activity_id), None
    )
    if shown is not None:
        assert all("went to this one" not in reason["text"] for reason in shown["reasons"])
    detail = _stored_search_detail(client, payload["audit_event"]["event_id"])
    row = next((r for r in detail["ranking"] if r["activity_id"] == activity_id), None)
    if row is not None:
        assert row["factors"]["engagement"] < 0


def test_a_sibling_session_is_never_told_the_person_attended_it(client: TestClient) -> None:
    """The wording half of B-F12, through the contract.

    Engagement rolls up to the programme so a cooldown reaches every session of it. Read straight
    onto the card, that roll-up printed "You went to this one before." on a Friday session
    because the person went on the Wednesday -- a reason the listing suited them, grounded in an
    outing that never happened. The sibling may say it knows the programme; it may not claim the
    session.
    """
    wednesday, friday = "activity-chair-mobility-1", "activity-chair-mobility-2"
    # Shown before it can be chosen: a listing this run never put in front of the person cannot
    # be planned from a response (`_searches_shown`).
    _search(client)
    planned = _respond(client, wednesday, response="interested").json()
    entry = next(e for e in planned["week"]["entries"] if e["activity"]["activity_id"] == wednesday)
    _advance_past(client, date.fromisoformat(entry["day"]))
    report = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/week/{entry['plan_id']}/follow-through",
        json={"follow_through": "went"},
    )
    assert report.status_code == 200, report.text

    shown = next(
        result
        for result in _search(client)["results"]
        if result["candidate"]["activity_id"] == friday
    )

    texts = [reason["text"] for reason in shown["reasons"]]
    assert "You went to this programme before." in texts
    assert all("this one" not in text for text in texts), texts


def test_a_confirmed_statement_leaves_exactly_one_row_on_that_dimension_and_value(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """A-F6. "That's right" used to write a *second* row beside the inferred one and touch
    neither, so both rendered on the Privacy screen -- and on a reversed stance the orphan became
    a contradiction the system had manufactured against a belief the person had just agreed with.
    The statement consumes the row it ratifies."""
    results = _search(client)["results"]
    walk = next(r for r in results if r["candidate"]["activity_type"] == "walking")
    _respond(client, walk["candidate"]["activity_id"], response="not_for_me", reason="not_for_me")
    learned = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"]
    assert [(p["dimension"], p["source"]) for p in learned] == [("activity_type", "decline_reason")]

    confirmed = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/activity_type/walking",
        json={"stance": "avoid", "stated_text": "walking is not for me"},
    )
    assert confirmed.status_code == 200, confirmed.text

    held = client.get(f"/v1/people/{DEMO_PERSON_ID}/activity-preferences").json()["dimensions"]
    assert [(p["dimension"], p["value"], p["source"]) for p in held] == [
        ("activity_type", "walking", "senior_statement")
    ]
    # The inferred row is consumed, not deleted: the record of what was learned stays, stamped
    # with the statement that superseded it.
    with repository.sessions() as session:
        rows = list(
            session.scalars(
                select(ActivityDimensionPreferenceRow).where(
                    ActivityDimensionPreferenceRow.dimension == "activity_type",
                    ActivityDimensionPreferenceRow.value == "walking",
                )
            )
        )
    superseded = [row for row in rows if row.superseded_by is not None]
    assert len(superseded) == 1
    assert superseded[0].source == "decline_reason"
    # And the world model shows no contradiction, because there is no live disagreement.
    facts = client.get(f"/v1/people/{DEMO_PERSON_ID}/world-model").json()["facts"]
    assert all(not fact["contradicts"] for fact in facts)


def test_a_close_by_gentle_social_ask_leads_with_the_650m_gentle_option(
    client: TestClient,
) -> None:
    """The product-comprehension review's own reproduction (M-1), pinned end to end.

    The reviewer typed "something gentle near home with other people" on a reset demo and
    recorded the intent it was confirmed back with -- `max_distance_m 1000` as a *phrase* rather
    than a number, `intensity light`, `social` -- beside a top three of 3.4 km, 1.6 km moderate
    and 2.8 km moderate, each carrying the single line "You will be among other people, as you
    asked", with the 650 m gentle option at rank nine.

    Three separate things have to hold for that never to read back as an answer to this request,
    so each is asserted rather than left to the ordering alone: the near gentle option leads; an
    intensity mismatch really costs a listing its share of the request-fit tier, so every "more
    active" option sits below every gentle one; and no line on a 3.4 km card claims it is within
    anything the person asked for.
    """
    response = client.post(
        "/v1/activities/search",
        json={"text": "something gentle near home with other people"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    asked = payload["intent"]
    assert asked["max_distance_m"] == 1000
    assert asked["distance_is_explicit"] is False
    assert asked["intensity"] == "light"
    assert asked["social_preference"] == "social"

    ranks = {result["candidate"]["title"]: result["rank"] for result in payload["results"]}
    leader = payload["results"][0]["candidate"]
    assert leader["title"] == "Community Gardening"
    assert leader["distance_m"] == 650
    assert leader["intensity"] == "light"
    # Each "more active" listing the review saw above it, now below every gentle one.
    gentle = [
        result["rank"]
        for result in payload["results"]
        if result["candidate"]["intensity"] == "light"
    ]
    moderate = [
        result["rank"]
        for result in payload["results"]
        if result["candidate"]["intensity"] == "moderate"
    ]
    assert gentle and moderate
    assert max(gentle) < min(moderate)
    for title in ("Karaoke & Social Hour", "Cool-of-Day Park Walk", "Warm Water Exercise"):
        assert ranks[title] > ranks["Community Gardening"], title

    # The card's lines stay true to what was asked: only a listing inside the radius says so.
    far = next(r for r in payload["results"] if r["candidate"]["title"] == "Karaoke & Social Hour")
    assert all("you asked for" not in reason["text"] for reason in far["reasons"])
    near = payload["results"][0]
    assert any("within the 1 km you asked for" in r["text"] for r in near["reasons"])
