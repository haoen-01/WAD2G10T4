"""Seniors who are fine are people, not an absence of cases (audit-H finding 2).

Care Team led with a queue of `ReviewCase`s and five counts. A coordinator could see who had a
case open and nothing else: not who was fine, not whose tracker had gone dark, not who was being
nudged right now. "No one needs human review" is a true sentence that answers a different question
from the one a coordinator actually asks at the start of a shift.

`GET /v1/coordinator/people` is the roster. What it deliberately does NOT carry is the point of
these tests: no step counts, no percentages, no priority score, no ranking of seniors. A band
word, a consent standing, a count of days a tracker did not sync, whether a case is open, and the
class of the last decision -- all of them already visible on the queue for anyone with a case, and
none of them a number about a person's body.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import AttentionBand, Decision
from silverloop.sql_repository import SqlAlchemyRepository


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def test_the_roster_lists_a_settled_person_with_the_band_their_own_state_reports() -> None:
    repository = _repo()
    try:
        state = repository.person_state()

        roster = repository.list_coordinator_roster()

        assert [row.person_id for row in roster] == [DEMO_PERSON_ID]
        row = roster[0]
        assert row.display_name == state.display_name
        assert row.attention_band == state.attention_band
        assert row.consent_active is True
        assert row.open_case_id is None
        assert row.last_decision == state.last_decision
    finally:
        repository.close()


def test_a_person_whose_tracker_did_not_sync_is_counted_without_being_alarmed_about() -> None:
    repository = _repo()
    try:
        repository.advance("low_wear", event_id="roster-low-wear")

        row = repository.list_coordinator_roster()[0]

        assert row.tracker_not_synced_days == 1
        # An uninterpretable reading claims nothing either way, so the band stays `stable`: a
        # tracker that was not worn is not evidence that anything is wrong. The device fact is
        # carried in its own field rather than smuggled into the band.
        assert row.attention_band == AttentionBand.STABLE
    finally:
        repository.close()


def test_a_person_under_review_is_flagged_with_their_open_case() -> None:
    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"roster-decline-{index}")
        case_id = repository.list_cases()[0].case_id

        row = repository.list_coordinator_roster()[0]

        assert row.attention_band == AttentionBand.REVIEW
        assert row.open_case_id == case_id
        assert row.last_decision == Decision.COORDINATOR_REVIEW
    finally:
        repository.close()


def test_a_resolved_case_stops_flagging_the_person_on_the_roster() -> None:
    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"roster-closed-{index}")
        repository.advance("recovery", event_id="roster-recovered")

        row = repository.list_coordinator_roster()[0]

        assert row.open_case_id is None
    finally:
        repository.close()


def test_the_roster_carries_no_figure_about_anyone(client: TestClient) -> None:
    """The standing decision is aggregates and bands, never a per-person metric. Asserting on the
    serialised field names rather than the model keeps that true when the model grows."""
    client.post("/v1/demo/reset")
    for index in range(3):
        client.post(
            "/v1/simulation/advance",
            json={"event": "activity_declines", "event_id": f"roster-shape-{index}"},
        )

    response = client.get("/v1/coordinator/people")

    assert response.status_code == 200, response.text
    rows = response.json()
    assert rows, "the roster must list the seeded person"
    assert set(rows[0]) == {
        "person_id",
        "display_name",
        "attention_band",
        "consent_active",
        "tracker_not_synced_days",
        "open_case_id",
        "last_decision",
    }
    # The band is a word. A number here -- a score, a percentage, a rank -- would turn a care
    # queue into a leaderboard of people.
    assert rows[0]["attention_band"] in {band.value for band in AttentionBand}
