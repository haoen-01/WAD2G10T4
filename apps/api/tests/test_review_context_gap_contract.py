"""The calibration-trust contract (docs/calibration-trust-spec.md, sections A, B and the D seam).

Pins what the frozen contract promises before the receipt and the evaluation are built on it:

- `context_gap_category` is accepted only beside an override for `known_context` (else 422), is
  stored and returned in the action history, and reaches the audit trail only as a presence flag;
- every review response carries a `lesson`, and the threshold state carries a receipt and a
  context-gap tally that change nothing;
- the evaluation's `authored_metric` seam replaces a generated metric, but never on
  `consent_revoked`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from silverloop.config import Settings
from silverloop.db_models import AuditEventRow, CaseReviewRow, DailyMetricRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import (
    CaseStatus,
    ContextGapCategory,
    DailyMetric,
    HumanAction,
    OverrideReason,
)
from silverloop.sql_repository import SqlAlchemyRepository

THRESHOLD = "/v1/coordinator/people/{person}/review-threshold"
NOTE = "Away visiting family this week."


def _advance(client: TestClient, event: str) -> dict[str, Any]:
    response = client.post(
        "/v1/simulation/advance", json={"event": event, "person_id": DEMO_PERSON_ID}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _open_case(client: TestClient) -> str:
    for _ in range(6):
        _advance(client, "activity_declines")
        cases = [
            case
            for case in client.get("/v1/coordinator/queue").json()
            if case["person_id"] == DEMO_PERSON_ID
        ]
        if cases:
            return str(cases[0]["case_id"])
    raise AssertionError("no review case opened after six declining days")


def _post_review(client: TestClient, case_id: str, **fields: Any) -> Any:
    body = {"status": "resolved", "reviewer_note": NOTE, **fields}
    return client.post(f"/v1/cases/{case_id}/review", json=body)


@pytest.mark.parametrize(
    "fields",
    [
        {"human_action": "agree"},
        {"human_action": "hold"},
        {},
        {"human_action": "override", "override_reason": "data_doubt"},
        {"human_action": "override", "override_reason": "recent_contact"},
        {"human_action": "override", "override_reason": "not_a_concern"},
        {"human_action": "override", "override_reason": "other"},
    ],
)
def test_a_category_without_a_known_context_override_is_refused(
    client: TestClient, fields: dict[str, str]
) -> None:
    case_id = _open_case(client)
    response = _post_review(client, case_id, context_gap_category="away", **fields)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("human_action", "override_reason"),
    [
        (None, None),
        (HumanAction.AGREE, None),
        (HumanAction.HOLD, None),
        (HumanAction.OVERRIDE, None),
        (HumanAction.OVERRIDE, OverrideReason.DATA_DOUBT),
        (HumanAction.OVERRIDE, OverrideReason.NOT_A_CONCERN),
        (None, OverrideReason.KNOWN_CONTEXT),
    ],
)
def test_the_repository_refuses_a_category_without_a_known_context_override(
    client: TestClient,
    repository: SqlAlchemyRepository,
    human_action: HumanAction | None,
    override_reason: OverrideReason | None,
) -> None:
    """The request model refuses this combination; the repository refuses it again, so a direct
    caller cannot store a category no coordinator could have meant."""
    case_id = _open_case(client)
    with repository.sessions() as session:
        reviews_before = session.scalar(select(func.count()).select_from(CaseReviewRow))
        audits_before = session.scalar(select(func.count()).select_from(AuditEventRow))
    with pytest.raises(ValueError, match="context_gap_category is allowed only"):
        repository.review_case(
            case_id,
            CaseStatus.RESOLVED,
            NOTE,
            "coordinator",
            human_action=human_action,
            override_reason=override_reason,
            context_gap_category=ContextGapCategory.AWAY,
        )
    with repository.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CaseReviewRow)) == reviews_before
        assert session.scalar(select(func.count()).select_from(AuditEventRow)) == audits_before
    assert repository.get_case(case_id).status == CaseStatus.OPEN

    accepted = repository.review_case(
        case_id,
        CaseStatus.RESOLVED,
        NOTE,
        "coordinator",
        human_action=HumanAction.OVERRIDE,
        override_reason=OverrideReason.KNOWN_CONTEXT,
        context_gap_category=ContextGapCategory.AWAY,
    )
    assert accepted.lesson.context_gap_category == ContextGapCategory.AWAY


def test_an_unknown_category_is_refused(client: TestClient) -> None:
    case_id = _open_case(client)
    response = _post_review(
        client,
        case_id,
        human_action="override",
        override_reason="known_context",
        context_gap_category="on_holiday",
    )
    assert response.status_code == 422


def test_a_known_context_category_is_stored_returned_and_audited_only_as_present(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    case_id = _open_case(client)
    response = _post_review(
        client,
        case_id,
        human_action="override",
        override_reason="known_context",
        context_gap_category="already_in_touch",
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["case"]["action_history"][-1]["context_gap_category"] == "already_in_touch"
    assert body["lesson"] == {
        "review_id": body["review_evidence_id"],
        "kind": "records_context_gap",
        "reason": "known_context",
        "context_gap_category": "already_in_touch",
        "summary": body["lesson"]["summary"],
    }
    assert body["lesson"]["summary"]
    assert NOTE not in body["lesson"]["summary"]

    detail = body["audit_event"]["detail"]
    assert detail["context_gap_category_present"] is True
    assert "context_gap_category" not in detail
    with repository.sessions() as session:
        stored = session.get(CaseReviewRow, body["review_evidence_id"])
        assert stored is not None
        assert stored.context_gap_category == "already_in_touch"
        audit_json = [row.detail_json for row in session.scalars(select(AuditEventRow))]
    assert "already_in_touch" not in repr(audit_json)


def test_a_review_without_a_category_stores_none_and_audits_absence(client: TestClient) -> None:
    case_id = _open_case(client)
    response = _post_review(client, case_id, human_action="agree")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["case"]["action_history"][-1]["context_gap_category"] is None
    assert body["audit_event"]["detail"]["context_gap_category_present"] is False
    assert (body["lesson"]["kind"], body["lesson"]["reason"]) == ("teaches_nothing", "agreed")


def test_the_threshold_state_tallies_context_gaps_and_carries_a_receipt(
    client: TestClient,
) -> None:
    case_id = _open_case(client)
    assert (
        _post_review(
            client,
            case_id,
            human_action="override",
            override_reason="known_context",
            context_gap_category="away",
        ).status_code
        == 200
    )
    response = client.get(THRESHOLD.format(person=DEMO_PERSON_ID))
    assert response.status_code == 200, response.text
    state = response.json()

    assert state["context_gaps"]["total"] == 1
    assert state["context_gaps"]["by_category"] == [{"category": "away", "count": 1}]
    assert state["context_gaps"]["disclosure"]
    assert state["receipt"]["subject"] in {"open_proposal", "live_setting", "next_proposal"}
    assert state["receipt"]["as_of_day"] == state["current_day"]
    # A context gap changes no review setting.
    assert state["live_source"] == "starting_setting"


def _authored_repository(
    authored: dict[date, DailyMetric], calls: list[tuple[str, date]]
) -> SqlAlchemyRepository:
    def authored_metric(person_id: str, day: date) -> DailyMetric | None:
        calls.append((person_id, day))
        return authored.get(day)

    instance = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=Settings(
            app_env="test",
            database_url="sqlite+pysqlite:///:memory:",
            silverloop_runtime_profile="offline",
            auth_enabled=False,
            llm_enabled=False,
        ),
        authored_metric=authored_metric,
    )
    instance.create_schema_for_tests()
    instance.reset()
    return instance


def _stored_metric(repository: SqlAlchemyRepository, day: date) -> DailyMetricRow:
    with repository.sessions() as session:
        row = session.scalar(select(DailyMetricRow).where(DailyMetricRow.day == day))
    assert row is not None
    return row


def test_an_authored_metric_replaces_the_generated_one() -> None:
    calls: list[tuple[str, date]] = []
    probe = _authored_repository({}, calls)
    try:
        first_day = probe.advance("recovery", person_id=DEMO_PERSON_ID).state.current_day
    finally:
        probe.close()
    assert calls == [(DEMO_PERSON_ID, first_day)]

    calls.clear()
    authored = DailyMetric(
        day=first_day, steps=1234, active_minutes=11, sleep_hours=7.1, wear_hours=12.5
    )
    repository = _authored_repository({first_day: authored}, calls)
    try:
        repository.advance("recovery", person_id=DEMO_PERSON_ID)
        stored = _stored_metric(repository, first_day)
        assert (stored.steps, stored.active_minutes, stored.wear_hours) == (1234, 11, 12.5)
    finally:
        repository.close()


def test_an_authored_metric_for_the_wrong_day_is_refused() -> None:
    calls: list[tuple[str, date]] = []
    probe = _authored_repository({}, calls)
    try:
        first_day = probe.advance("recovery", person_id=DEMO_PERSON_ID).state.current_day
    finally:
        probe.close()

    wrong = DailyMetric(day=date(2000, 1, 1), steps=1, active_minutes=1, wear_hours=12.0)
    repository = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:",
        settings=Settings(
            app_env="test",
            database_url="sqlite+pysqlite:///:memory:",
            silverloop_runtime_profile="offline",
            auth_enabled=False,
            llm_enabled=False,
        ),
        authored_metric=lambda _person, day: wrong if day == first_day else None,
    )
    repository.create_schema_for_tests()
    repository.reset()
    try:
        with pytest.raises(ValueError, match="authored metric"):
            repository.advance("recovery", person_id=DEMO_PERSON_ID)
    finally:
        repository.close()


def test_consent_revoked_is_never_overridden_by_an_authored_metric() -> None:
    calls: list[tuple[str, date]] = []
    probe = _authored_repository({}, calls)
    try:
        next_day = probe.advance("recovery", person_id=DEMO_PERSON_ID).state.current_day
    finally:
        probe.close()

    calls.clear()
    authored = DailyMetric(
        day=next_day, steps=9999, active_minutes=99, sleep_hours=7.0, wear_hours=14.0
    )
    repository = _authored_repository({next_day: authored}, calls)
    try:
        repository.advance("consent_revoked", person_id=DEMO_PERSON_ID)
        assert calls == []
        stored = _stored_metric(repository, next_day)
        assert (stored.steps, stored.wear_hours) == (0, 0)
    finally:
        repository.close()
