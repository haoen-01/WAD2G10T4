"""Authorization for every route the follow-through loop added.

`test_intervention_outcome_ownership.py` closed this gap for `POST .../outcome`: any
authenticated senior holding someone else's `intervention_id` could close it, attribute an
outcome to themselves, append to the victim's audit trail and shift the victim's preference
ranking. The follow-through work added five more routes that take an id or a `person_id` from
the path, and each one reopens exactly that hole if it forwards the identifier unchecked.

Two rules are asserted throughout:

* Out-of-scope is **404, not 403**, so none of these endpoints can be used as an existence
  oracle for another person's interventions or days.
* The refusal has **no side effects**. A rejected write that has already mutated the victim's
  preferences before returning is not a fixed bug, and it is the failure a naive
  "check the role, then call the repository" patch still ships.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import jwt
import pytest
from fastapi.testclient import TestClient

from silverloop.config import Settings
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository

JWT_SECRET = "follow-through-ownership-test-secret"
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
def repo() -> Iterator[SqlAlchemyRepository]:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()
    instance.reset()  # seeds DEMO_PERSON_ID (senior A)
    instance.reset(person_id=PERSON_B, allow_new_person=True)  # senior B
    instance.upsert_person_link(SENIOR_A, DEMO_PERSON_ID, "test")
    instance.upsert_person_link(SENIOR_B, PERSON_B, "test")
    yield instance
    instance.close()


@pytest.fixture
def auth_client(repo: SqlAlchemyRepository) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=True,
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=JWT_SECRET,
    )
    app = create_app(repo, settings=settings, migrate_on_start=False)
    return TestClient(app, raise_server_exceptions=False)


def _accepted_intervention_for_a(repo: SqlAlchemyRepository, client: TestClient) -> str:
    """One of senior A's interventions, already accepted so follow-through is legitimately open."""
    advance = repo.advance("activity_declines", person_id=DEMO_PERSON_ID)
    assert advance.created_intervention is not None
    intervention_id = advance.created_intervention.intervention_id
    accepted = client.post(
        f"/v1/interventions/{intervention_id}/outcome",
        json={"outcome": "accepted"},
        headers=_bearer(SENIOR_A),
    )
    assert accepted.status_code == 200, accepted.text
    return intervention_id


# ── Another person's intervention ─────────────────────────────────────────────────────────────


def test_senior_cannot_read_another_persons_outreach_detail(
    repo: SqlAlchemyRepository, auth_client: TestClient
) -> None:
    intervention_id = _accepted_intervention_for_a(repo, auth_client)

    response = auth_client.get(
        f"/v1/interventions/{intervention_id}/detail", headers=_bearer(SENIOR_B)
    )

    assert response.status_code == 404


def test_senior_cannot_read_another_persons_follow_up_observation(
    repo: SqlAlchemyRepository, auth_client: TestClient
) -> None:
    """The most sensitive read of the three: it describes someone else's activity week."""
    intervention_id = _accepted_intervention_for_a(repo, auth_client)

    response = auth_client.get(
        f"/v1/interventions/{intervention_id}/follow-up", headers=_bearer(SENIOR_B)
    )

    assert response.status_code == 404


def test_senior_cannot_record_follow_through_on_another_persons_intervention(
    repo: SqlAlchemyRepository, auth_client: TestClient
) -> None:
    intervention_id = _accepted_intervention_for_a(repo, auth_client)
    candidate_key = repo.list_interventions(person_id=DEMO_PERSON_ID)[0].evidence["candidate_key"]
    events_before = repo.list_events(person_id=DEMO_PERSON_ID)
    preference_before = repo.metrics(person_id=DEMO_PERSON_ID).candidate_preference_scores.get(
        candidate_key
    )

    response = auth_client.post(
        f"/v1/interventions/{intervention_id}/follow-through",
        json={"follow_through": "completed"},
        headers=_bearer(SENIOR_B),
    )

    assert response.status_code == 404

    # A's intervention is untouched -- no follow-through recorded on their behalf.
    matching = [
        item
        for item in repo.list_interventions(person_id=DEMO_PERSON_ID)
        if item.intervention_id == intervention_id
    ]
    assert len(matching) == 1
    assert matching[0].follow_through is None

    # A's audit trail is unchanged.
    events_after = repo.list_events(person_id=DEMO_PERSON_ID)
    assert {event.event_id for event in events_after} == {event.event_id for event in events_before}

    # And the subtle damage the naive fix still ships: B's rejected attempt must not have moved
    # A's ranking. The mutation would otherwise already have happened inside the repository.
    preference_after = repo.metrics(person_id=DEMO_PERSON_ID).candidate_preference_scores.get(
        candidate_key
    )
    assert preference_after == preference_before


def test_a_senior_can_use_all_three_routes_on_their_own_intervention(
    repo: SqlAlchemyRepository, auth_client: TestClient
) -> None:
    """The positive control -- without it the four 404s above could all be passing because the
    routes are simply broken for everyone."""
    intervention_id = _accepted_intervention_for_a(repo, auth_client)

    assert (
        auth_client.get(
            f"/v1/interventions/{intervention_id}/detail", headers=_bearer(SENIOR_A)
        ).status_code
        == 200
    )
    assert (
        auth_client.get(
            f"/v1/interventions/{intervention_id}/follow-up", headers=_bearer(SENIOR_A)
        ).status_code
        == 200
    )
    assert (
        auth_client.post(
            f"/v1/interventions/{intervention_id}/follow-through",
            json={"follow_through": "completed"},
            headers=_bearer(SENIOR_A),
        ).status_code
        == 200
    )


# ── Another person's preferences and days ─────────────────────────────────────────────────────


def test_senior_cannot_read_another_persons_candidate_preferences(auth_client: TestClient) -> None:
    response = auth_client.get(
        f"/v1/people/{DEMO_PERSON_ID}/preferences", headers=_bearer(SENIOR_B)
    )
    assert response.status_code == 404


def test_senior_cannot_write_another_persons_candidate_preference(
    auth_client: TestClient,
) -> None:
    response = auth_client.post(
        f"/v1/people/{DEMO_PERSON_ID}/preferences/gentle_nudge:indoor_walk",
        json={"suppressed": True, "reason": "Muting someone else's suggestion."},
        headers=_bearer(SENIOR_B),
    )

    assert response.status_code == 404

    # A's own view is unchanged -- nothing was muted on their behalf.
    own = auth_client.get(
        f"/v1/people/{DEMO_PERSON_ID}/preferences", headers=_bearer(SENIOR_A)
    ).json()
    assert not any(item["suppressed"] for item in own)


def test_senior_cannot_dispute_another_persons_day(auth_client: TestClient) -> None:
    metrics = auth_client.get(
        f"/v1/people/{DEMO_PERSON_ID}/metrics?days=3", headers=_bearer(SENIOR_A)
    ).json()

    response = auth_client.post(
        f"/v1/people/{DEMO_PERSON_ID}/day-dispute",
        json={"day": metrics[-1]["day"], "accurate": False, "note": "Not my day."},
        headers=_bearer(SENIOR_B),
    )

    assert response.status_code == 404


def test_a_senior_owns_their_own_preferences_and_days(auth_client: TestClient) -> None:
    """Positive control for the person-scoped half."""
    listed = auth_client.get(f"/v1/people/{DEMO_PERSON_ID}/preferences", headers=_bearer(SENIOR_A))
    assert listed.status_code == 200

    metrics = auth_client.get(
        f"/v1/people/{DEMO_PERSON_ID}/metrics?days=3", headers=_bearer(SENIOR_A)
    ).json()
    disputed = auth_client.post(
        f"/v1/people/{DEMO_PERSON_ID}/day-dispute",
        json={"day": metrics[-1]["day"], "accurate": False},
        headers=_bearer(SENIOR_A),
    )
    assert disputed.status_code == 200


# ── Only the senior may mute a suggestion ─────────────────────────────────────────────────────


def test_a_coordinator_cannot_mute_a_suggestion_on_someone_elses_behalf(
    auth_client: TestClient,
) -> None:
    """The whole reason the control exists is that it belongs to the person receiving the
    suggestions. A coordinator quietly switching off someone's options -- with the best of
    intentions -- is the outcome the ownership rule is there to prevent, and it would be
    invisible to the person it happened to."""
    response = auth_client.post(
        f"/v1/people/{DEMO_PERSON_ID}/preferences/gentle_nudge:indoor_walk",
        json={"suppressed": True, "reason": "Coordinator thinks this is not suitable."},
        headers=_bearer("coordinator-sub", role="coordinator"),
    )

    assert response.status_code == 403

    own = auth_client.get(
        f"/v1/people/{DEMO_PERSON_ID}/preferences", headers=_bearer(SENIOR_A)
    ).json()
    assert not any(item["suppressed"] for item in own)


def test_a_coordinator_cannot_read_or_write_the_follow_through_routes(
    repo: SqlAlchemyRepository, auth_client: TestClient
) -> None:
    intervention_id = _accepted_intervention_for_a(repo, auth_client)
    coordinator = _bearer("coordinator-sub", role="coordinator")

    assert (
        auth_client.get(
            f"/v1/interventions/{intervention_id}/detail", headers=coordinator
        ).status_code
        == 403
    )
    assert (
        auth_client.post(
            f"/v1/interventions/{intervention_id}/follow-through",
            json={"follow_through": "completed"},
            headers=coordinator,
        ).status_code
        == 403
    )
    assert (
        auth_client.get(f"/v1/people/{DEMO_PERSON_ID}/preferences", headers=coordinator).status_code
        == 403
    )


def test_unauthenticated_requests_reach_none_of_the_new_routes(
    repo: SqlAlchemyRepository, auth_client: TestClient
) -> None:
    intervention_id = _accepted_intervention_for_a(repo, auth_client)

    assert auth_client.get(f"/v1/interventions/{intervention_id}/detail").status_code == 401
    assert auth_client.get(f"/v1/interventions/{intervention_id}/follow-up").status_code == 401
    assert (
        auth_client.post(
            f"/v1/interventions/{intervention_id}/follow-through",
            json={"follow_through": "completed"},
        ).status_code
        == 401
    )
    assert auth_client.get(f"/v1/people/{DEMO_PERSON_ID}/preferences").status_code == 401
