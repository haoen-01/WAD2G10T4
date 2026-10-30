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
        # Bumped by `c1e5a8f2d640_group_member_last_opened`. Pinned
        # literally on purpose: `/ready` compares the live revision against the repo
        # head, and asserting it against `expected_database_revision()` would compare
        # the implementation to itself.
        "expected_migration_revision": "c1e5a8f2d640",
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


def test_operational_metrics_expose_evidence_health(client: TestClient) -> None:
    client.post("/v1/simulation/advance", json={"event": "low_wear"})
    metrics = client.get("/v1/metrics")
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["decision_evidence"] == 1
    assert payload["no_action_decisions"] == 1
    assert payload["source_classification_counts"] == {"synthetic_fixture": 30}
    assert payload["policy_version"] == "silverloop-policy-v1"
    assert payload["offline_ready"] is True


def test_api_event_idempotency_replays_the_same_evidence(client: TestClient) -> None:
    request = {"event": "activity_declines", "event_id": "browser-event-001"}
    first = client.post("/v1/simulation/advance", json=request)
    replay = client.post("/v1/simulation/advance", json=request)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert client.get("/v1/simulation/latest").json() == first.json()
    assert client.get("/v1/metrics").json()["decision_evidence"] == 1


def test_demo_progresses_to_review_with_evidence(client: TestClient) -> None:
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
    queue = client.get("/v1/coordinator/queue").json()
    assert len(queue) == 1
    assert len(queue[0]["evidence"]) >= 2


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


def test_outcome_and_case_review_are_durable_api_operations(client: TestClient) -> None:
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

    client.post("/v1/simulation/advance", json={"event": "activity_declines"})
    third = client.post("/v1/simulation/advance", json={"event": "activity_declines"}).json()
    case_id = third["created_case"]["case_id"]
    reviewed = client.post(
        f"/v1/cases/{case_id}/review",
        json={"status": "resolved", "reviewer_note": "Synthetic review completed."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["case"]["status"] == "resolved"
    assert reviewed.json()["outcome"] == "coordinator_resolved"
    assert reviewed.json()["review_evidence_id"].startswith("review_")


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


# ── person_id scoping: /v1/simulation/events, /v1/simulation/latest, /v1/metrics ───────────────
#
# The repository methods behind these three routes have always accepted `person_id`; only the
# routes ignored it, so a five-persona UI would show `mdm-lim`'s timeline/metrics for whoever was
# selected. See docs/WAYFINDER.md and the F5 persona work.

PERSON_B = "person-b"


def test_events_latest_and_metrics_return_the_requested_persons_data(
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

    events_a = client.get("/v1/simulation/events").json()
    events_b = client.get("/v1/simulation/events", params={"person_id": PERSON_B}).json()
    assert all(event["person_id"] == "mdm-lim" for event in events_a)
    assert all(event["person_id"] == PERSON_B for event in events_b)
    assert events_a != events_b

    latest_a = client.get("/v1/simulation/latest").json()
    latest_b = client.get("/v1/simulation/latest", params={"person_id": PERSON_B}).json()
    assert latest_a["state"]["person_id"] == "mdm-lim"
    assert latest_b["state"]["person_id"] == PERSON_B
    assert latest_a["state"]["last_decision"] == "no_action"  # low_wear
    assert latest_b["state"]["last_decision"] != "no_action"  # activity_declines

    metrics_a = client.get("/v1/metrics").json()
    metrics_b = client.get("/v1/metrics", params={"person_id": PERSON_B}).json()
    assert metrics_a["scenario_run_id"] != metrics_b["scenario_run_id"]
    assert metrics_a["decision_evidence"] == 1
    assert metrics_b["decision_evidence"] == 1

    history_a = client.get("/v1/simulation/history").json()
    history_b = client.get("/v1/simulation/history", params={"person_id": PERSON_B}).json()
    assert [entry["event_name"] for entry in history_a] == ["low_wear"]
    assert [entry["event_name"] for entry in history_b] == ["activity_declines"]
    assert history_a != history_b


@pytest.mark.parametrize(
    "path",
    ["/v1/simulation/events", "/v1/simulation/latest", "/v1/simulation/history", "/v1/metrics"],
)
def test_person_scoped_endpoints_404_on_unknown_person(client: TestClient, path: str) -> None:
    response = client.get(path, params={"person_id": "no-such-person"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Person not found"


def test_person_scoped_endpoints_default_to_the_demo_person_when_omitted(
    client: TestClient,
) -> None:
    """Every existing caller (no `person_id` query param) must keep working unchanged."""
    assert client.get("/v1/simulation/events").status_code == 200
    assert client.get("/v1/simulation/latest").status_code == 200
    assert client.get("/v1/simulation/history").status_code == 200
    assert client.get("/v1/metrics").status_code == 200


def test_the_browser_may_put_a_stated_preference(client: TestClient) -> None:
    """The preference route is a PUT, and the CORS allow-list used to name GET and POST only, so
    the browser's preflight was refused and "Forget this" could never reach the server from the
    web app. Caught by the e2e loop, pinned here where it is cheap."""
    preflight = client.options(
        "/v1/people/mdm-lim/activity-preferences/distance/near",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert preflight.status_code == 200, preflight.text
    assert "PUT" in preflight.headers.get("access-control-allow-methods", "")
