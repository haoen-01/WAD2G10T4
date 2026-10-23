"""The guided scenario "A false alarm teaches Care+", pinned offline on `mdm-wong`.

The Simulator's guided scenario (docs/demo-scenario-playback-spec.md) is only honest if what it
narrates is what the offline demo actually does: SQLite, fixture adapters, `LLM_ENABLED=false`, so
the fixed rule proposes. Mdm Wong's rolling baseline moves with every day the arc adds, so the
per-day decisions and gates are pinned here rather than assumed; if the fixture or the policy
moves, this test says exactly where the story stopped being true.

Chapter 1  A swing asks a person: activity_declines x3 -> case on day 3 -> "Not a concern for
           this person" (the fixed rule waits for a second).
Chapter 2  Rain, and a second swing: recovery; rain_explains_decline x1; recovery;
           activity_declines x3 -> case on day 3 -> "Not a concern" -> fixed-rule proposal: wait
           four valid-wear days instead of three -> approve.
Chapter 3  The next swing stays quiet: recovery (the approved setting is live from here);
           activity_declines x3 with no case; recovery.
Chapter 4  A real change still asks: activity_declines x4 -> case on day 4 -> "This should have
           reached me sooner" -> revert to the starting setting from the next simulated day.
End        recovery: the starting setting is live again.

Exactly one rain day: a second consecutive one is decided by the weekly contact cap, not the rain.
Where the weekly contact cap holds back a nudge or programme suggestion inside a swing, that is
pinned too (`suppress` / `contact_cap`); it never stops a case from opening.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from silverloop.config import Settings
from silverloop.main import create_app
from silverloop.sql_repository import SqlAlchemyRepository

PERSON = "mdm-wong"
THRESHOLD = f"/v1/coordinator/people/{PERSON}/review-threshold"
DEMO_NOTE = "Mdm Wong's activity swings a lot from week to week; this is her usual pattern."
DEMO_SCRIPT_NOTE = "Recorded by the demo script to skip ahead. Not a coordinator's judgement."
SIGN_IN_ON = "Demo script actions are only available with sign-in off."

Step = tuple[str, str, str, int, bool]

# (event, last_decision, decided_by_gate, sustained_low_days, opened a case)
CHAPTER_1: list[Step] = [
    ("activity_declines", "gentle_nudge", "severity_persistence", 1, False),
    ("activity_declines", "programme_suggestion", "severity_persistence", 2, False),
    ("activity_declines", "coordinator_review", "severity_persistence", 3, True),
]
CHAPTER_2: list[Step] = [
    ("recovery", "no_action", "within_range", 0, False),
    ("rain_explains_decline", "no_action", "rain_context", 1, False),
    ("recovery", "no_action", "within_range", 0, False),
    ("activity_declines", "suppress", "contact_cap", 1, False),
    ("activity_declines", "programme_suggestion", "severity_persistence", 2, False),
    ("activity_declines", "coordinator_review", "severity_persistence", 3, True),
]
CHAPTER_3: list[Step] = [
    ("recovery", "no_action", "within_range", 0, False),
    ("activity_declines", "gentle_nudge", "severity_persistence", 1, False),
    ("activity_declines", "suppress", "contact_cap", 2, False),
    ("activity_declines", "suppress", "contact_cap", 3, False),
    ("recovery", "no_action", "within_range", 0, False),
]
CHAPTER_4: list[Step] = [
    ("activity_declines", "gentle_nudge", "severity_persistence", 1, False),
    ("activity_declines", "suppress", "contact_cap", 2, False),
    ("activity_declines", "suppress", "contact_cap", 3, False),
    ("activity_declines", "coordinator_review", "severity_persistence", 4, True),
]
END: list[Step] = [("recovery", "no_action", "within_range", 0, False)]

STARTING = {"severity_pct": 40, "persistence_days": 3}
APPROVED = {"severity_pct": 40, "persistence_days": 4}

NOT_A_CONCERN = {
    "status": "resolved",
    "human_action": "override",
    "override_reason": "not_a_concern",
}


def _play(client: TestClient, steps: list[Step]) -> list[dict[str, Any]]:
    responses = []
    for index, (event, decision, gate, sustained, opened) in enumerate(steps):
        response = client.post("/v1/simulation/advance", json={"event": event, "person_id": PERSON})
        assert response.status_code == 200, response.text
        body = response.json()
        state = body["state"]
        actual = (
            event,
            state["last_decision"],
            state["decided_by_gate"],
            state["signal"]["sustained_low_days"],
            body["created_case"] is not None,
        )
        assert actual == (event, decision, gate, sustained, opened), (
            f"step {index + 1} on {state['current_day']}: expected "
            f"{(event, decision, gate, sustained, opened)}, got {actual}"
        )
        responses.append(body)
    return responses


def _person_cases(client: TestClient) -> list[dict[str, Any]]:
    queue = client.get("/v1/coordinator/queue").json()
    return [case for case in queue if case["person_id"] == PERSON]


def _open_case(client: TestClient) -> str:
    cases = _person_cases(client)
    assert len(cases) == 1, cases
    return cases[0]["case_id"]


def _review(client: TestClient, case_id: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"/v1/cases/{case_id}/review", json={"reviewer_note": DEMO_NOTE, **body})
    assert response.status_code == 200, response.text
    return response.json()


def _state(client: TestClient) -> dict[str, Any]:
    response = client.get(THRESHOLD)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_guided_false_alarm_arc_runs_offline_on_mdm_wong(client: TestClient) -> None:
    reset = client.post("/v1/demo/reset", params={"person_id": PERSON})
    assert reset.status_code == 200, reset.text
    assert reset.json()["state"]["current_day"] == "2026-07-30"

    # Chapter 1: the starting setting asks on day three; the coordinator says it is her usual.
    opened = _play(client, CHAPTER_1)
    case_id = _open_case(client)
    assert opened[-1]["created_case"]["case_id"] == case_id
    _review(client, case_id, **NOT_A_CONCERN)
    state = _state(client)
    assert state["live"] == STARTING
    assert state["open_proposal"] is None
    assert [(item["output_kind"], item["cause"]) for item in state["proposals"]] == [
        ("no_change", None)
    ]

    # Chapter 2: one rain day explains itself; the second false alarm within 30 days opens exactly
    # one fixed-rule +1-day proposal.
    _play(client, CHAPTER_2)
    _review(client, _open_case(client), **NOT_A_CONCERN)
    state = _state(client)
    proposal = state["open_proposal"]
    assert proposal is not None
    assert proposal["proposer"] == "fixed_rule"
    assert proposal["agent_run"]["mode"] == "fallback_disabled"
    assert proposal["previous"] == STARTING
    assert proposal["proposed"] == APPROVED
    assert proposal["cause"] == "too_tight_for_person"

    replay = client.get(
        f"{THRESHOLD}/replay", params={"severity_pct": 40, "persistence_days": 4}
    ).json()
    assert replay["reviews_with_current"] >= 2

    approved = client.post(
        f"{THRESHOLD}/proposals/{proposal['proposal_id']}/approve",
        json={"cause_confirmed": True, "shown_on_day": state["current_day"]},
    )
    assert approved.status_code == 200, approved.text
    approved_on = date.fromisoformat(state["current_day"])
    decision = approved.json()["decision"]
    assert decision["decided_by"] == "coordinator"
    assert decision["effective_from_day"] == (approved_on + timedelta(days=1)).isoformat()
    assert approved.json()["audit_event"]["detail"]["recorded_by_demo_script"] is False
    # An approval takes effect from the next simulated day, not today.
    assert _state(client)["live"] == STARTING
    notice = client.get(f"/v1/people/{PERSON}/state").json()["review_threshold_notice"]
    assert notice["kind"] == "later"

    # Chapter 3: from the recovery day the approved setting is live; three low days, no case.
    _play(client, CHAPTER_3[:1])
    live = _state(client)
    assert live["live"] == APPROVED
    assert live["live_source"] == "approved"
    _play(client, CHAPTER_3[1:])
    assert _person_cases(client) == []
    assert _state(client)["live"] == APPROVED

    # Chapter 4: the fourth day asks; the coordinator says it should have reached them sooner.
    responses = _play(client, CHAPTER_4)
    assert responses[-1]["state"]["rationale"][1] == (
        "The decline has persisted for at least four valid-wear days."
    )
    marked = _review(
        client,
        _open_case(client),
        status="resolved",
        human_action="agree",
        reached_too_late=True,
    )
    assert marked["case"]["action_history"][-1]["reached_too_late"] is True
    state = _state(client)
    revert = state["decisions"][0]
    today = date.fromisoformat(state["current_day"])
    assert revert["kind"] == "reverted"
    assert revert["revert_trigger"] == "reached_too_late"
    assert revert["after"] == STARTING
    assert revert["effective_from_day"] == (today + timedelta(days=1)).isoformat()
    assert today - approved_on == timedelta(days=9)
    assert state["live"] == APPROVED

    # End: from the recovery day the starting setting is back.
    after = _play(client, END)[-1]["state"]
    assert after["review_threshold_notice"]["kind"] == "sooner"
    live = _state(client)
    assert live["live"] == STARTING
    assert live["live_source"] == "reverted"
    assert _person_cases(client) == []


def test_resetting_mdm_wong_starts_her_review_setting_over(client: TestClient) -> None:
    assert client.post("/v1/demo/reset", params={"person_id": PERSON}).status_code == 200
    _play(client, CHAPTER_1)
    _review(client, _open_case(client), **NOT_A_CONCERN)
    assert _state(client)["proposals"]
    assert client.post("/v1/demo/reset", params={"person_id": PERSON}).status_code == 200
    fresh = _state(client)
    assert fresh["proposals"] == []
    assert fresh["decisions"] == []
    assert fresh["live_source"] == "starting_setting"


# ── Demo-script actions ("Start from chapter n") ─────────────────────────────────────────────


def _demo_script_review(client: TestClient, case_id: str) -> dict[str, Any]:
    body = {**NOT_A_CONCERN, "reviewer_note": DEMO_SCRIPT_NOTE, "recorded_by_demo_script": True}
    return _review(client, case_id, **body)


def test_demo_script_actions_are_recorded_as_the_demo_script_and_still_calibrate(
    client: TestClient,
) -> None:
    """Skipping to chapter 3 records chapters 1 and 2's actions as `demo-script`, never `system`,
    and they still count as human reviews: the fixed rule proposes and the approval takes effect."""
    assert client.post("/v1/demo/reset", params={"person_id": PERSON}).status_code == 200
    _play(client, CHAPTER_1)
    first = _demo_script_review(client, _open_case(client))
    assert first["case"]["action_history"][-1]["reviewer"] == "demo-script"
    assert first["audit_event"]["actor"] == "demo-script"
    assert first["audit_event"]["detail"]["reviewer"] == "demo-script"
    assert first["audit_event"]["detail"]["recorded_by_demo_script"] is True
    # Not a system closure: it teaches what a coordinator's "not a concern" teaches.
    assert first["lesson"]["reason"] == "not_a_concern"

    _play(client, CHAPTER_2)
    _demo_script_review(client, _open_case(client))
    state = _state(client)
    proposal = state["open_proposal"]
    assert proposal is not None
    assert (proposal["previous"], proposal["proposed"]) == (STARTING, APPROVED)

    approved = client.post(
        f"{THRESHOLD}/proposals/{proposal['proposal_id']}/approve",
        json={
            "cause_confirmed": True,
            "shown_on_day": state["current_day"],
            "note": DEMO_SCRIPT_NOTE,
            "recorded_by_demo_script": True,
        },
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["decision"]["decided_by"] == "demo-script"
    assert body["audit_event"]["actor"] == "demo-script"
    assert body["audit_event"]["detail"]["recorded_by_demo_script"] is True
    assert DEMO_SCRIPT_NOTE not in str(body["audit_event"])

    # The quiet chapter plays exactly as it does after a coordinator's approval.
    _play(client, CHAPTER_3)
    assert _person_cases(client) == []
    assert _state(client)["live"] == APPROVED


def test_a_plain_review_is_not_marked_as_the_demo_script(client: TestClient) -> None:
    assert client.post("/v1/demo/reset", params={"person_id": PERSON}).status_code == 200
    _play(client, CHAPTER_1)
    reviewed = _review(client, _open_case(client), **NOT_A_CONCERN)
    assert reviewed["case"]["action_history"][-1]["reviewer"] == "coordinator"
    assert reviewed["audit_event"]["detail"]["recorded_by_demo_script"] is False


JWT_SECRET = "demo-script-test-secret-key-of-32-bytes"
SUPABASE_URL = "https://project.supabase.co"


def _coordinator_headers() -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": "coordinator-001",
            "iss": SUPABASE_URL + "/auth/v1",
            "aud": "authenticated",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "app_metadata": {"role": "coordinator"},
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def signed_in(repository: SqlAlchemyRepository) -> TestClient:
    """The same repository as `client`, behind an app with sign-in on."""
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=True,
        llm_enabled=False,
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=JWT_SECRET,
    )
    return TestClient(create_app(repository, settings=settings, migrate_on_start=False))


def test_demo_script_actions_are_refused_with_sign_in_on(
    client: TestClient, signed_in: TestClient
) -> None:
    """With real identities a request must never rename its own actor. Nothing is recorded."""
    assert client.post("/v1/demo/reset", params={"person_id": PERSON}).status_code == 200
    _play(client, CHAPTER_1)
    case_id = _open_case(client)
    review = {**NOT_A_CONCERN, "reviewer_note": DEMO_SCRIPT_NOTE, "recorded_by_demo_script": True}
    refused = signed_in.post(
        f"/v1/cases/{case_id}/review", headers=_coordinator_headers(), json=review
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == SIGN_IN_ON
    assert client.get(f"/v1/cases/{case_id}").json()["action_history"] == []
    assert _open_case(client) == case_id

    # Without the flag the signed-in coordinator's review is recorded under their own identity.
    plain = signed_in.post(
        f"/v1/cases/{case_id}/review",
        headers=_coordinator_headers(),
        json={**NOT_A_CONCERN, "reviewer_note": DEMO_NOTE},
    )
    assert plain.status_code == 200, plain.text
    assert plain.json()["case"]["action_history"][-1]["reviewer"] == "coordinator-001"

    _play(client, CHAPTER_2)
    _review(client, _open_case(client), **NOT_A_CONCERN)
    state = _state(client)
    proposal = state["open_proposal"]
    assert proposal is not None
    refused = signed_in.post(
        f"{THRESHOLD}/proposals/{proposal['proposal_id']}/approve",
        headers=_coordinator_headers(),
        json={
            "cause_confirmed": True,
            "shown_on_day": state["current_day"],
            "recorded_by_demo_script": True,
        },
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == SIGN_IN_ON
    after = _state(client)
    assert after["open_proposal"] is not None
    assert after["decisions"] == []
