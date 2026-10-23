"""The case's "since your last review" delta, through the real API (UX audit P1-6).

Driven by the same simulation, review and response routes the product uses, then read back from
the case route and the review response -- the only two reads that gather it. The coordinator queue
and a newly created case on an advance carry `since_last_review: null`, so the queue never pays for
a per-case delta. The pure rules live in `test_case_delta.py`; these tests prove the repository
gathers the right rows for them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import event

from silverloop.agent.guardrails import coordinator_text_violations
from silverloop.models import CaseStatus, OutcomeKind
from silverloop.sql_repository import SqlAlchemyRepository

PRIVATE_REVIEW_NOTE = "PRIVATE-REVIEW-NOTE-7f3a"


def _advance(client: TestClient, event: str, event_id: str) -> dict[str, Any]:
    response = client.post("/v1/simulation/advance", json={"event": event, "event_id": event_id})
    assert response.status_code == 200, response.text
    return response.json()


def _review(client: TestClient, case_id: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        f"/v1/cases/{case_id}/review",
        json={"status": "acknowledged", "reviewer_note": PRIVATE_REVIEW_NOTE, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _case(client: TestClient, case_id: str) -> dict[str, Any]:
    response = client.get(f"/v1/cases/{case_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _open_case(client: TestClient, prefix: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    advances = [_advance(client, "activity_declines", f"{prefix}-{index}") for index in range(3)]
    queue = client.get("/v1/coordinator/queue").json()
    assert len(queue) == 1
    return _case(client, queue[0]["case_id"]), advances


def _decision_id(advance: dict[str, Any]) -> str:
    return advance["audit_event"]["detail"]["evidence_id"]


def _wearable_id(advance: dict[str, Any]) -> str:
    return advance["audit_event"]["detail"]["wearable_evidence_id"]


def test_a_new_case_has_nothing_new_since_it_opened(client: TestClient) -> None:
    case, _ = _open_case(client, "opened")

    delta = case["since_last_review"]
    assert delta["anchor_kind"] == "case_opened"
    assert delta["anchor_day"] == case["opened_day"]
    assert delta["anchor_recorded_at"] == case["opened_at"]
    assert delta["nothing_new"] is True
    assert delta["items"] == []


def test_the_delta_lists_days_context_and_a_response_recorded_after_the_review(
    client: TestClient,
) -> None:
    case, _ = _open_case(client, "seq")
    case_id = case["case_id"]
    pending = [step for step in case["prior_outreach"] if step["outcome"] is None]
    assert len(pending) == 1

    reviewed = _review(client, case_id)["case"]["since_last_review"]
    assert reviewed["anchor_kind"] == "last_review"
    assert reviewed["anchor_day"] == case["opened_day"]
    assert reviewed["nothing_new"] is True

    declined = client.post(
        f"/v1/interventions/{pending[0]['intervention_id']}/outcome",
        json={"outcome": OutcomeKind.DECLINED.value},
    )
    assert declined.status_code == 200, declined.text
    rain = _advance(client, "rain_explains_decline", "seq-rain")
    cleared = _advance(client, "rain_clears_activity_low", "seq-clear")
    lower = _advance(client, "activity_declines", "seq-lower")
    no_wear = _advance(client, "low_wear", "seq-nowear")

    detail = _case(client, case_id)
    assert detail["status"] == "acknowledged"
    delta = detail["since_last_review"]
    assert delta["anchor_kind"] == "last_review"
    assert delta["nothing_new"] is False
    summary = [
        (item["kind"], item["count"], item["day"], item["evidence_ids"]) for item in delta["items"]
    ]
    usable = [_wearable_id(rain), _wearable_id(cleared), _wearable_id(lower)]
    assert summary == [
        (
            "days_recorded",
            4,
            None,
            [_decision_id(day) for day in (rain, cleared, lower, no_wear)],
        ),
        ("usable_data_days", 3, None, usable),
        ("below_usual_range_days", 3, None, usable),
        ("rain_started", None, rain["state"]["current_day"], [_wearable_id(rain)]),
        ("rain_ended", None, cleared["state"]["current_day"], [_wearable_id(cleared)]),
        (
            "outreach_declined",
            None,
            pending[0]["day"],
            [declined.json()["outcome_evidence_id"], pending[0]["intervention_id"]],
        ),
    ]
    for item in delta["items"]:
        assert coordinator_text_violations(item["text"]) == []

    # The queue does not gather it: the case page is where the delta is read.
    queued = client.get("/v1/coordinator/queue").json()
    assert queued[0]["case_id"] == case_id
    assert queued[0]["since_last_review"] is None


def test_the_anchor_moves_to_each_new_human_review(client: TestClient) -> None:
    case, _ = _open_case(client, "anchor")
    case_id = case["case_id"]
    first = _review(client, case_id)["case"]["since_last_review"]
    _advance(client, "activity_declines", "anchor-3")
    assert _case(client, case_id)["since_last_review"]["items"][0]["count"] == 1

    second_case = _review(client, case_id)["case"]
    second = second_case["since_last_review"]
    assert second["anchor_kind"] == "last_review"
    assert second["anchor_recorded_at"] > first["anchor_recorded_at"]
    assert second["anchor_recorded_at"] == second_case["last_reviewed_at"]
    assert second["anchor_day"] > first["anchor_day"]
    assert second["nothing_new"] is True

    lower = _advance(client, "activity_declines", "anchor-4")
    after_second = _case(client, case_id)["since_last_review"]
    assert after_second["items"][0]["kind"] == "days_recorded"
    assert after_second["items"][0]["evidence_ids"] == [_decision_id(lower)]

    # A review marked as reaching the coordinator too late starts a one-step-sooner proposal
    # after the review is stored: that proposal is the only thing new since this third review.
    third = _review(client, case_id, human_action="agree", reached_too_late=True)["case"]
    assert third["since_last_review"]["nothing_new"] is True
    after_third = _case(client, case_id)["since_last_review"]
    assert [item["kind"] for item in after_third["items"]] == ["review_timing_proposed"]
    assert after_third["items"][0]["day"] == lower["state"]["current_day"]


def test_nothing_the_person_said_and_no_review_note_reaches_the_delta(client: TestClient) -> None:
    sentinel_answer = "SENTINEL-ANSWER-NOTE-91c2"
    sentinel_dispute = "SENTINEL-DISPUTE-NOTE-4b8e"
    first = _advance(client, "activity_declines", "privacy-0")
    question = first["state"]["pending_question"]
    assert question is not None
    answered = client.post(
        "/v1/people/mdm-lim/context-answer",
        json={"question_id": question["question_id"], "value": "away", "note": sentinel_answer},
    )
    assert answered.status_code == 200, answered.text
    for index in (1, 2):
        _advance(client, "activity_declines", f"privacy-{index}")
    case = client.get("/v1/coordinator/queue").json()[0]
    _review(client, case["case_id"])

    # The stated explanation runs out on the day after the review, and the person disputes a day.
    later = _advance(client, "activity_declines", "privacy-3")
    assert later["state"]["stated_explanation"] is None
    disputed = client.post(
        "/v1/people/mdm-lim/day-dispute",
        json={"day": later["state"]["current_day"], "accurate": False, "note": sentinel_dispute},
    )
    assert disputed.status_code == 200, disputed.text
    _advance(client, "activity_declines", "privacy-4")

    delta = _case(client, case["case_id"])["since_last_review"]
    serialised = json.dumps(delta).lower()
    for forbidden in (
        sentinel_answer.lower(),
        sentinel_dispute.lower(),
        PRIVATE_REVIEW_NOTE.lower(),
        "away",
        "explanation",
        "dispute",
        "stated",
        "said",
        "told",
        "%",
    ):
        assert forbidden not in serialised, forbidden
    assert {item["kind"] for item in delta["items"]} == {
        "days_recorded",
        "usable_data_days",
        "below_usual_range_days",
    }
    # The dispute is not allowed to change the count either: both new days stay below range.
    assert delta["items"][2]["count"] == 2


def test_a_resolved_case_carries_no_delta(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    case, _ = _open_case(client, "resolved")
    response = client.post(
        f"/v1/cases/{case['case_id']}/review",
        json={"status": CaseStatus.RESOLVED.value, "reviewer_note": "Checked in separately."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["case"]["since_last_review"] is None
    assert repository.get_case(case["case_id"]).since_last_review is None


@contextmanager
def _statements(repository: SqlAlchemyRepository) -> Iterator[list[str]]:
    seen: list[str] = []

    def record(*args: Any) -> None:
        seen.append(str(args[2]).lower())

    event.listen(repository.engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(repository.engine, "before_cursor_execute", record)


def test_the_queue_and_a_created_case_carry_no_delta_and_never_gather_one(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    advances = [_advance(client, "activity_declines", f"cost-{index}") for index in range(3)]
    created = [item["created_case"] for item in advances if item["created_case"] is not None]
    assert len(created) == 1
    assert created[0]["since_last_review"] is None
    case_id = created[0]["case_id"]
    _review(client, case_id)
    _advance(client, "activity_declines", "cost-3")

    queued = client.get("/v1/coordinator/queue").json()
    assert [item["case_id"] for item in queued] == [case_id]
    assert queued[0]["status"] == "acknowledged"
    assert queued[0]["since_last_review"] is None
    # The case route still has something new to say about the same case.
    assert _case(client, case_id)["since_last_review"]["nothing_new"] is False

    # Only the delta reads the review-setting proposals table on a case read; the queue must not.
    with _statements(repository) as queue_statements:
        assert repository.list_cases()[0].since_last_review is None
    assert queue_statements
    assert not any("review_threshold_proposals" in sql for sql in queue_statements)
    with _statements(repository) as case_statements:
        assert repository.get_case(case_id).since_last_review is not None
    assert any("review_threshold_proposals" in sql for sql in case_statements)
    # The delta reads the stored days once, not once for the readings and again for the signals.
    assert sum("daily_metrics" in sql for sql in case_statements) == (
        sum("daily_metrics" in sql for sql in queue_statements) + 1
    )


def _schema_refs(node: Any) -> set[str]:
    if isinstance(node, dict):
        found = {node["$ref"].rsplit("/", 1)[-1]} if "$ref" in node else set()
        for value in node.values():
            found |= _schema_refs(value)
        return found
    if isinstance(node, list):
        found: set[str] = set()
        for value in node:
            found |= _schema_refs(value)
        return found
    return set()


def test_only_coordinator_and_demo_operator_routes_can_return_the_delta(
    client: TestClient,
) -> None:
    """No senior route's response schema reaches `SinceLastReview`, directly or transitively.

    This pins which response *schemas* include the field. Only `GET /v1/cases/{case_id}` and the
    review response populate it; the queue, the advance's `created_case` and `latest` share the
    `ReviewCase` shape but always return `null` (pinned above).
    """
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]

    def reaches(name: str, seen: set[str]) -> bool:
        if name == "SinceLastReview":
            return True
        if name in seen or name not in schemas:
            return False
        seen.add(name)
        return any(reaches(ref, seen) for ref in _schema_refs(schemas[name]))

    routes: set[str] = set()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            refs = _schema_refs(operation.get("responses", {}))
            if any(reaches(ref, set()) for ref in refs):
                routes.add(f"{method.upper()} {path}")

    assert routes == {
        "GET /v1/coordinator/queue",
        "GET /v1/cases/{case_id}",
        "POST /v1/cases/{case_id}/review",
        "POST /v1/simulation/advance",
        "GET /v1/simulation/latest",
    }
