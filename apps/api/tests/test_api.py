import pytest
from fastapi.testclient import TestClient

from silverloop.config import Settings
from silverloop.main import create_app
from silverloop.runtime import RuntimeConfigurationError
from silverloop.sql_repository import SqlAlchemyRepository


def test_health_and_initial_state(client: TestClient) -> None:
    health = client.get("/health", headers={"x-request-id": "req_test_health"})
    assert health.json()["status"] == "ok"
    assert health.headers["x-request-id"] == "req_test_health"
    response = client.get("/v1/people/mdm-lim/state")
    assert response.status_code == 200
    assert response.json()["attention_band"] == "stable"


def test_person_metrics_returns_oldest_first_history(client: TestClient) -> None:
    response = client.get("/v1/people/mdm-lim/metrics")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 14
    days = [entry["day"] for entry in body]
    assert days == sorted(days)
    assert all({"day", "steps", "wear_hours"} <= entry.keys() for entry in body)


def test_person_metrics_respects_the_days_query_param(client: TestClient) -> None:
    response = client.get("/v1/people/mdm-lim/metrics", params={"days": 5})

    assert response.status_code == 200
    assert len(response.json()) == 5


def test_person_metrics_unknown_person_returns_404(client: TestClient) -> None:
    response = client.get("/v1/people/does-not-exist/metrics")

    assert response.status_code == 404


def test_readiness_reports_database_backend_without_exposing_connection_details(
    client: TestClient,
) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_ready",
        "database_backend": "sqlite",
        "runtime_profile": "offline",
        "database_connected": True,
        "migration_revision": None,
        # Bumped by `a7d4c2e9f1b3_add_family_tasks`. Pinned
        # literally on purpose: `/ready` compares the live revision against the repo
        # head, and asserting it against `expected_database_revision()` would compare
        # the implementation to itself.
        "expected_migration_revision": "a7d4c2e9f1b3",
        # PostgreSQL-only: RLS, `pg_policies` and the Data API roles do not exist on SQLite, so
        # this reads as "nothing to report" rather than as "every table is open".
        "tables_without_rls": [],
    }
    assert "database_url" not in response.text


def test_shared_app_startup_rejects_sqlite_even_when_uvicorn_is_called_directly(
    repository: SqlAlchemyRepository,
) -> None:
    application = create_app(
        repository,
        settings=Settings(
            app_env="development",
            database_url="sqlite+pysqlite:///:memory:",
            silverloop_runtime_profile="shared",
        ),
        migrate_on_start=False,
    )

    with (
        pytest.raises(
            RuntimeConfigurationError,
            match="Supabase-first startup requires a PostgreSQL DATABASE_URL",
        ),
        TestClient(application),
    ):
        pass


def test_operational_metrics_expose_evidence_health(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    client.post("/v1/simulation/advance", json={"event": "low_wear"})
    # `GET /v1/metrics` went in step 7; the repository read behind it stays (`supabase_smoke`).
    payload = repository.metrics().model_dump(mode="json")
    assert payload["decision_evidence"] == 1
    assert payload["no_action_decisions"] == 1
    assert payload["source_classification_counts"] == {"synthetic_fixture": 30}
    assert payload["policy_version"] == "silverloop-policy-v1"
    assert payload["offline_ready"] is True


def test_api_event_idempotency_replays_the_same_evidence(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    request = {"event": "activity_declines", "event_id": "browser-event-001"}
    first = client.post("/v1/simulation/advance", json=request)
    replay = client.post("/v1/simulation/advance", json=request)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert repository.metrics().decision_evidence == 1


def test_demo_progresses_to_review_with_evidence(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    decisions = []
    payload = None
    for _ in range(3):
        response = client.post("/v1/simulation/advance", json={"event": "activity_declines"})
        assert response.status_code == 200
        payload = response.json()
        decisions.append(payload["state"]["last_decision"])

    assert "gentle_nudge" in decisions
    assert "programme_suggestion" in decisions
    assert decisions[-1] == "coordinator_review"
    assert payload is not None and payload["created_case"] is not None
    # Ten stages, not nine. `follow_through` sits between `outcome` and `learning` because that
    # is where it happens: the loop now records what the person actually did before anything is
    # learned from it, rather than learning straight off the tap.
    assert [step["stage"] for step in payload["loop_trace"]] == [
        "observation",
        "validation",
        "reasoning",
        "policy_gate",
        "action",
        "response",
        "outcome",
        "follow_through",
        "learning",
        "audit",
    ]
    assert [step["order"] for step in payload["loop_trace"]] == list(range(1, 11))
    assert payload["audit_event"]["detail"]["evidence_id"].startswith("decision_")
    assert payload["audit_event"]["detail"]["policy_version"] == "silverloop-policy-v1"
    cases = repository.list_cases()
    assert len(cases) == 1
    assert len(cases[0].evidence) >= 2


def test_low_wear_and_consent_do_not_trigger_outreach(client: TestClient) -> None:
    low_wear = client.post("/v1/simulation/advance", json={"event": "low_wear"}).json()
    assert low_wear["state"]["last_decision"] == "no_action"
    assert low_wear["state"]["rationale"] == low_wear["state"]["signal"]["quality"]["reasons"]
    audit_detail = low_wear["audit_event"]["detail"]
    assert audit_detail["quality_evidence_id"] == "dq_mdm-lim_2026-08-19_synthetic"
    assert audit_detail["source"] == "synthetic"
    assert audit_detail["observed_at"] == "2026-08-19T12:00:00+00:00"
    revoked = client.post("/v1/simulation/advance", json={"event": "consent_revoked"}).json()
    assert revoked["state"]["last_decision"] == "suppress"
    assert revoked["created_intervention"] is None


def test_outcome_is_a_durable_api_operation(client: TestClient) -> None:
    first = client.post("/v1/simulation/advance", json={"event": "activity_declines"}).json()
    intervention_id = first["created_intervention"]["intervention_id"]
    outcome = client.post(
        f"/v1/interventions/{intervention_id}/outcome", json={"outcome": "accepted"}
    )
    assert outcome.status_code == 200
    assert outcome.json()["outcome"] == "accepted"
    assert outcome.json()["intervention"]["outcome"] == "accepted"
    assert outcome.json()["preference_after"] > outcome.json()["preference_before"]
    assert outcome.json()["outcome_evidence_id"].startswith("outcome_")


def test_consent_revocation_withdraws_proposal_and_blocks_late_response(
    client: TestClient,
) -> None:
    first = client.post("/v1/simulation/advance", json={"event": "activity_declines"}).json()
    intervention_id = first["created_intervention"]["intervention_id"]
    consent = client.post(
        "/v1/people/mdm-lim/consent",
        json={"active": False, "reason": "I do not want suggestions."},
    )
    assert consent.status_code == 200
    assert intervention_id in consent.json()["withdrawn_intervention_ids"]
    intervention = client.get("/v1/interventions").json()[0]
    assert intervention["status"] == "withdrawn_consent_revoked"
    late = client.post(
        f"/v1/interventions/{intervention_id}/outcome",
        json={"outcome": "accepted"},
    )
    assert late.status_code == 422
    assert "withdrawn" in late.json()["detail"]


def test_preference_learning_ranks_only_policy_permitted_candidates(client: TestClient) -> None:
    first = client.post("/v1/simulation/advance", json={"event": "activity_declines"}).json()
    first_action = first["created_intervention"]
    client.post(
        f"/v1/interventions/{first_action['intervention_id']}/outcome",
        json={"outcome": "declined"},
    )
    reset = client.post("/v1/demo/reset")
    assert reset.status_code == 200
    assert "state" in reset.json()
    second = client.post("/v1/simulation/advance", json={"event": "activity_declines"}).json()
    second_action = second["created_intervention"]
    assert first_action["decision"] == second_action["decision"] == "gentle_nudge"
    assert first_action["evidence"]["candidate_key"] != second_action["evidence"]["candidate_key"]

    client.post(
        "/v1/people/mdm-lim/consent",
        json={"active": False, "reason": "Stop suggestions."},
    )
    blocked = client.post("/v1/simulation/advance", json={"event": "activity_declines"}).json()
    assert blocked["state"]["last_decision"] == "suppress"
    assert blocked["created_intervention"] is None


# ── person_id scoping of the operational metrics ─────────────────────────────────────────────
#
# `GET /v1/simulation/events`, `/latest`, `/history` and `/v1/metrics` went in step 7. The
# repository's `metrics()` stays (`supabase_smoke.py` reads it) and still answers per person.

PERSON_B = "person-b"


def test_metrics_return_the_requested_persons_data(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    repository.reset(person_id=PERSON_B, allow_new_person=True)

    client.post(
        "/v1/simulation/advance",
        json={"event": "activity_declines", "event_id": "evt-b-1", "person_id": PERSON_B},
    )
    client.post(  # defaults to mdm-lim
        "/v1/simulation/advance", json={"event": "low_wear", "event_id": "evt-a-1"}
    )

    metrics_a = repository.metrics()
    metrics_b = repository.metrics(person_id=PERSON_B)
    assert metrics_a.scenario_run_id != metrics_b.scenario_run_id
    assert metrics_a.decision_evidence == 1
    assert metrics_b.decision_evidence == 1


def test_metrics_for_an_unknown_person_raise_key_error(repository: SqlAlchemyRepository) -> None:
    with pytest.raises(KeyError):
        repository.metrics(person_id="no-such-person")


def test_the_browser_may_put(client: TestClient) -> None:
    """The CORS allow-list used to name GET and POST only, so the browser's preflight for a PUT
    was refused and the PUT never reached the server from the web app. Caught by the e2e loop on
    the stated-preference route (removed in step 7), pinned here on a PUT the web app still makes
    (ticking a task)."""
    preflight = client.options(
        "/v1/people/mdm-lim/tasks/task-1/days/2026-09-10",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert preflight.status_code == 200, preflight.text
    assert "PUT" in preflight.headers.get("access-control-allow-methods", "")
