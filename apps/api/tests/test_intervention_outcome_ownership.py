"""Authorization tests for `POST /v1/interventions/{intervention_id}/outcome`.

`GET /v1/interventions` is person-scoped (`current_user.person_id`), but the outcome route used
to forward `intervention_id` straight to `repository.record_outcome` with no ownership check --
any authenticated senior holding another senior's `intervention_id` could close it, record an
outcome attributed to themselves, append to the victim's audit trail, and (most subtly) shift the
victim's Beta-Bernoulli preference ranking. These tests prove the ownership check closes that gap
end-to-end through the HTTP layer, and that none of those side effects occur when it fires.
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
from tests.row_fixtures import audit_events

JWT_SECRET = "outcome-ownership-test-secret"
SUPABASE_URL = "https://project.supabase.co"
PERSON_B = "person-b"


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


def _bearer(sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(sub)}"}


@pytest.fixture
def repo() -> Iterator[SqlAlchemyRepository]:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()
    instance.reset()  # seeds DEMO_PERSON_ID (senior A)
    instance.reset(person_id=PERSON_B, allow_new_person=True)  # senior B
    instance.upsert_person_link("senior-a-sub", DEMO_PERSON_ID, "test")
    instance.upsert_person_link("senior-b-sub", PERSON_B, "test")
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


@pytest.fixture
def offline_client(repo: SqlAlchemyRepository) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
    )
    app = create_app(repo, settings=settings, migrate_on_start=False)
    return TestClient(app, raise_server_exceptions=False)


def test_senior_records_outcome_on_own_intervention(
    repo: SqlAlchemyRepository, auth_client: TestClient
) -> None:
    advance = repo.advance("activity_declines", person_id=DEMO_PERSON_ID)
    assert advance.created_intervention is not None
    intervention_id = advance.created_intervention.intervention_id

    response = auth_client.post(
        f"/v1/interventions/{intervention_id}/outcome",
        json={"outcome": "accepted"},
        headers=_bearer("senior-a-sub"),
    )

    assert response.status_code == 200
    assert response.json()["intervention"]["status"] == "closed"


def test_senior_cannot_record_outcome_on_another_persons_intervention(
    repo: SqlAlchemyRepository, auth_client: TestClient
) -> None:
    advance = repo.advance("activity_declines", person_id=DEMO_PERSON_ID)
    assert advance.created_intervention is not None
    intervention_id = advance.created_intervention.intervention_id
    candidate_key = advance.created_intervention.evidence["candidate_key"]

    events_before = audit_events(repo, person_id=DEMO_PERSON_ID)
    preference_before = repo.metrics(person_id=DEMO_PERSON_ID).candidate_preference_scores.get(
        candidate_key
    )

    # Senior B, authenticated as themselves, attempts to close Senior A's intervention.
    response = auth_client.post(
        f"/v1/interventions/{intervention_id}/outcome",
        json={"outcome": "accepted"},
        headers=_bearer("senior-b-sub"),
    )

    # Must be indistinguishable from an unknown intervention_id -- 404, not 403, so the endpoint
    # cannot be used as an existence oracle for other people's data.
    assert response.status_code == 404

    # A's intervention is untouched: still open, no outcome recorded.
    interventions_a = repo.list_interventions(person_id=DEMO_PERSON_ID)
    matching = [item for item in interventions_a if item.intervention_id == intervention_id]
    assert len(matching) == 1
    assert matching[0].status != "closed"
    assert matching[0].outcome is None

    # A's audit trail is unchanged -- no `intervention_outcome_recorded` event was appended.
    events_after = audit_events(repo, person_id=DEMO_PERSON_ID)
    assert len(events_after) == len(events_before)
    assert {event.event_id for event in events_after} == {event.event_id for event in events_before}

    # The subtle damage: B's rejected attempt must not have moved A's preference score for the
    # candidate that was offered to A. This is the assertion the naive fix (403 + no ownership
    # check on the repository) would still fail, because the mutation happens inside
    # `record_outcome` before any response is returned.
    preference_after = repo.metrics(person_id=DEMO_PERSON_ID).candidate_preference_scores.get(
        candidate_key
    )
    assert preference_after == preference_before


def test_offline_demo_person_can_still_record_own_outcome(
    repo: SqlAlchemyRepository, offline_client: TestClient
) -> None:
    advance = repo.advance("activity_declines", person_id=DEMO_PERSON_ID)
    assert advance.created_intervention is not None
    intervention_id = advance.created_intervention.intervention_id

    response = offline_client.post(
        f"/v1/interventions/{intervention_id}/outcome",
        json={"outcome": "accepted"},
    )

    assert response.status_code == 200
    assert response.json()["intervention"]["status"] == "closed"
