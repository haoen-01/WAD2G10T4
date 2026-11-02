"""Which programme an answer was about: the repository half of the second-answer rule.

One unclarified "not for me" (`THIS_ONE`) or "bad timing" (`THIS_SLOT`) is item-level and held
back until a second agreeing answer, and saying no to the same programme again is not a second,
independent view. The pure rule lives in `preferences._fold`; what `advance` and the outcome route
still need from the repository is the lookup that names the programme of each held belief's
origin (`origin_series`) by id, never by parsing it. That is what this file pins.

The search-result answers ("not for me" on a listing) and the ranker inspector's preview that the
rest of this file drove went with their routes in step 7; a stored search answer is written here
as a row so the lookup over both answer tables stays covered.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import update

from silverloop.activity_search import series_key
from silverloop.db_models import ActivityCandidateRow, ActivityOfferResponseRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository

_PROGRAMME_KEY = "programme:aac-chair-mobility"


def _advance(client: TestClient, event: str = "recovery") -> dict[str, Any]:
    response = client.post("/v1/simulation/advance", json={"event": event})
    assert response.status_code == 200, response.text
    return response.json()


def _stored_search_answer(
    repository: SqlAlchemyRepository,
    activity_id: str,
    reason: str | None,
    *,
    response: str = "not_for_me",
) -> str:
    """An answer to a search result, as `respond_to_activity` stored it (removed in step 7)."""
    response_id = f"aresp_{uuid4().hex[:16]}"
    with repository.sessions.begin() as session:
        run = repository._active_run(session, DEMO_PERSON_ID)
        session.add(
            ActivityOfferResponseRow(
                response_id=response_id,
                run_id=run.run_id,
                person_id=DEMO_PERSON_ID,
                activity_id=activity_id,
                response=response,
                reason=reason,
                recorded_on_day=run.current_day,
                actor="senior",
                recorded_at=datetime.now(UTC),
            )
        )
    return response_id


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


# ── The lookups themselves ────────────────────────────────────────────────────────────────────


def test_origin_series_is_read_by_id_from_both_answer_tables_only(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    outreach = _decline_programme_outreach(client, "not_for_me")
    search = {"response_id": _stored_search_answer(repository, "activity-tai-chi-1", "not_for_me")}

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


# ── What advance's replan step reads back about the person's answers ──────────────────────────


def _engagement(repository: SqlAlchemyRepository) -> dict[str, Any]:
    """`_activity_engagement` for the active run: the per-listing counts `advance` hands
    `replanning.notices_for` when it writes replan offers."""
    with repository.sessions() as session:
        run = repository._active_run(session, DEMO_PERSON_ID)
        return SqlAlchemyRepository._activity_engagement(session, DEMO_PERSON_ID, run.run_id)


def test_stored_answers_roll_up_to_the_programme_once_per_day_and_per_run(
    repository: SqlAlchemyRepository,
) -> None:
    assert _engagement(repository) == {}
    # Two taps on one session the same day count once.
    _stored_search_answer(repository, "activity-chair-mobility-1", "not_for_me")
    _stored_search_answer(repository, "activity-chair-mobility-1", "not_for_me")
    _stored_search_answer(repository, "activity-tai-chi-1", None, response="interested")
    engagement = _engagement(repository)
    today = repository.person_state().current_day

    first, sibling = (
        engagement["activity-chair-mobility-1"],
        engagement["activity-chair-mobility-2"],
    )
    assert (first.not_for_me, first.last_not_for_me) == (1, today)
    # The sibling session carries the programme's total, though it was never answered itself.
    assert (sibling.not_for_me, sibling.last_not_for_me) == (1, today)
    assert sibling.own is not None and sibling.own.not_for_me == 0
    assert engagement["activity-tai-chi-1"].interested == 1
    assert engagement["activity-tai-chi-1"].not_for_me == 0
    assert "activity-seated-strength-1" not in engagement

    # A reset starts a new story: the earlier run's answers stay on record but count for nothing.
    repository.reset()
    assert _engagement(repository) == {}
