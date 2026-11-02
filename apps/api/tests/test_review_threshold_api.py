"""What `advance` does with a person's review setting (ADR 0008).

A coordinator's structured false-alarm judgement used to lead Care+ to *propose* a one-step change
to when it asks a human about one person, and a coordinator approved it through the Care Team
routes. Those routes, and the review that started a calibration, went in step 7. What stays is
everything `advance` (and consent withdrawal) does with a setting already on record: the
protections -- shadow check, expiry, consent -- that undo it without anyone's approval, the senior
notice, and the run lock. Approvals and open proposals are inserted as rows here, as the removed
routes stored them, and the state is read straight from the rows `advance` writes.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from silverloop.db_models import (
    AuditEventRow,
    CaseReviewRow,
    ReviewCaseRow,
    ReviewThresholdDecisionRow,
    ReviewThresholdProposalRow,
    ScenarioRunRow,
)
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import (
    CaseStatus,
    ReviewThresholdOutputKind,
)
from silverloop.review_threshold import (
    DEFAULT_REVIEW_THRESHOLD,
    LOOSENED_EXPIRY_DAYS,
    SENIOR_NOTICE_DAYS,
    ReviewThreshold,
    resolve_live_threshold,
    senior_notice_for,
)
from silverloop.sql_repository import (
    SqlAlchemyRepository,
    StaleRunConflict,
    _utcnow,
)
from tests.row_fixtures import audit_events

# ── Helpers ───────────────────────────────────────────────────────────────────────────────────


def _advance(client: TestClient, event: str, person: str = DEMO_PERSON_ID) -> dict[str, Any]:
    response = client.post("/v1/simulation/advance", json={"event": event, "person_id": person})
    assert response.status_code == 200, response.text
    return response.json()


def _active_run(repository: SqlAlchemyRepository, person: str = DEMO_PERSON_ID) -> ScenarioRunRow:
    with repository.sessions() as session:
        run = session.scalar(
            select(ScenarioRunRow).where(
                ScenarioRunRow.active.is_(True), ScenarioRunRow.person_id == person
            )
        )
    assert run is not None
    return run


def _insert_agent_proposal(
    repository: SqlAlchemyRepository,
    *,
    person: str = DEMO_PERSON_ID,
    previous: tuple[int, int] = (40, 3),
    proposed: tuple[int, int] = (40, 4),
    cause: str | None = "too_tight_for_person",
    coordinator_reason: str | None = "not_a_concern",
    reported_by: str = "coordinator",
    round_id: str | None = None,
    proposed_at_offset: timedelta = timedelta(0),
    cite_a_review: bool = True,
    trigger_latest_case: bool = True,
    reasoning: str = "Agent reasoning (test fixture).",
) -> str:
    """A proposal as the stage-2 agent would store it. The fixed rule cannot produce three
    proposals in one round or a proposal inside a cooldown, so those states are set up here."""
    run = _active_run(repository, person)
    proposal_id = f"threshold_proposal_test{time.monotonic_ns() % 10**12:012d}"
    with repository.sessions.begin() as session:
        cited = session.scalar(
            select(CaseReviewRow.review_id).where(CaseReviewRow.run_id == run.run_id).limit(1)
        )
        latest_case = (
            session.scalar(
                select(ReviewCaseRow.case_id)
                .where(ReviewCaseRow.run_id == run.run_id)
                .order_by(ReviewCaseRow.opened_at.desc())
                .limit(1)
            )
            if trigger_latest_case
            else None
        )
        session.add(
            ReviewThresholdProposalRow(
                proposal_id=proposal_id,
                run_id=run.run_id,
                person_id=person,
                output_kind="proposal",
                proposer="agent",
                round_id=round_id,
                round_index=1,
                previous_severity_pct=previous[0],
                previous_persistence_days=previous[1],
                proposed_severity_pct=proposed[0],
                proposed_persistence_days=proposed[1],
                cause=cause,
                reasoning=reasoning,
                cited_evidence_ids=[cited] if cited and cite_a_review else [],
                trigger_case_id=latest_case,
                trigger_review_ids=[cited] if cited and cite_a_review else [],
                reported_by=reported_by,
                coordinator_reason=coordinator_reason,
                write_up_for_decision_id=None,
                agent_run_json=None,
                proposed_on_day=run.current_day,
                proposed_at=_utcnow() + proposed_at_offset,
            )
        )
    return proposal_id


def _row_counts(repository: SqlAlchemyRepository) -> tuple[int, ...]:
    with repository.sessions() as session:
        return tuple(
            int(session.scalar(select(func.count()).select_from(table)) or 0)
            for table in (
                AuditEventRow,
                ReviewCaseRow,
                CaseReviewRow,
                ReviewThresholdProposalRow,
                ReviewThresholdDecisionRow,
            )
        )


def _approve_directly(
    repository: SqlAlchemyRepository,
    after: tuple[int, int],
    person: str = DEMO_PERSON_ID,
    *,
    previous: tuple[int, int] = (40, 3),
    decision_id: str = "threshold_decision_fixture",
    days_ago: int = 1,
    effective_days_ago: int | None = None,
) -> str:
    """An approval already in force today, as the approve route leaves it one day later."""
    run = _active_run(repository, person)
    decided_on = run.current_day - timedelta(days=days_ago)
    effective = (
        decided_on + timedelta(days=1)
        if effective_days_ago is None
        else run.current_day - timedelta(days=effective_days_ago)
    )
    with repository.sessions.begin() as session:
        session.add(
            ReviewThresholdDecisionRow(
                decision_id=decision_id,
                run_id=run.run_id,
                person_id=person,
                kind="approved",
                previous_severity_pct=previous[0],
                previous_persistence_days=previous[1],
                severity_pct=after[0],
                persistence_days=after[1],
                decided_by="coordinator",
                replay_json=None,
                decided_on_day=decided_on,
                effective_from_day=effective,
                decided_at=_utcnow(),
            )
        )
    return decision_id


def _facts_on(repository: SqlAlchemyRepository, day: date) -> Any:
    run = _active_run(repository)
    with repository.sessions() as session:
        return resolve_live_threshold(repository._threshold_facts(session, run.run_id), day)


def _open_case_id(repository: SqlAlchemyRepository, person: str = DEMO_PERSON_ID) -> str | None:
    """The person's unresolved case, if any (the queue route that served this went in step 7)."""
    cases = [
        case
        for case in repository.list_cases(person_id=person)
        if case.status != CaseStatus.RESOLVED
    ]
    return cases[0].case_id if cases else None


def _decline_until_case(client: TestClient, repository: SqlAlchemyRepository) -> str:
    for _ in range(6):
        _advance(client, "activity_declines")
        case_id = _open_case_id(repository)
        if case_id is not None:
            return case_id
    raise AssertionError("no review case opened after six declining days")


def _value(threshold: ReviewThreshold) -> dict[str, int]:
    return {"severity_pct": threshold.severity_pct, "persistence_days": threshold.persistence_days}


def _state(repository: SqlAlchemyRepository, person: str = DEMO_PERSON_ID) -> dict[str, Any]:
    """This person's review setting, read from the stored rows with the folds `advance` uses.

    The coordinator read behind `GET /v1/coordinator/people/{id}/review-threshold` went in step 7;
    what `advance` writes is unchanged, so these tests read the rows it writes directly: the live
    value (`resolve_live_threshold`), the decisions and proposals newest first, the senior notice,
    and the proposal still waiting for a decision.
    """
    run = _active_run(repository, person)
    with repository.sessions() as session:
        rows = repository._threshold_decision_rows(session, run.run_id)
        facts = [repository._threshold_fact(row) for row in rows]
        proposals = repository._threshold_proposal_rows(session, run.run_id)
        consent_active = repository._consent_active(session, run.run_id)
    live = resolve_live_threshold(facts, run.current_day)
    decided = {row.proposal_id for row in rows if row.proposal_id}
    waiting = [
        row.proposal_id
        for row in reversed(proposals)
        if row.output_kind == ReviewThresholdOutputKind.PROPOSAL.value
        and row.proposal_id not in decided
    ]
    notice = senior_notice_for(facts, run.current_day)
    return {
        "current_day": run.current_day.isoformat(),
        "consent_active": consent_active,
        "live": _value(live.threshold),
        "live_source": live.source,
        "live_decision_id": live.approval_id,
        "expires_on_day": live.expires_on_day.isoformat() if live.expires_on_day else None,
        "open_proposal": {"proposal_id": waiting[0]} if waiting else None,
        "decisions": [
            {
                "decision_id": row.decision_id,
                "kind": row.kind,
                "proposal_id": row.proposal_id,
                "ends_approval_id": row.ends_approval_id,
                "affects_decision_id": row.affects_decision_id,
                "revert_trigger": row.revert_trigger,
                "before": {
                    "severity_pct": row.previous_severity_pct,
                    "persistence_days": row.previous_persistence_days,
                },
                "after": (
                    {"severity_pct": row.severity_pct, "persistence_days": row.persistence_days}
                    if row.severity_pct is not None and row.persistence_days is not None
                    else None
                ),
                "decided_by": row.decided_by,
                "rejection_reason": row.rejection_reason,
                "trigger_case_id": row.trigger_case_id,
                "decided_on_day": row.decided_on_day.isoformat(),
                "effective_from_day": row.effective_from_day.isoformat(),
            }
            for row in reversed(rows)
        ],
        "proposals": [
            {
                "proposal_id": row.proposal_id,
                "output_kind": row.output_kind,
                "proposer": row.proposer,
                "write_up_for_decision_id": row.write_up_for_decision_id,
                "reasoning": row.reasoning,
            }
            for row in reversed(proposals)
        ],
        "senior_notice_preview": notice.model_dump(mode="json") if notice else None,
    }


def _events(repository: SqlAlchemyRepository, person: str = DEMO_PERSON_ID) -> list[dict[str, Any]]:
    """The active run's audit trail (`GET /v1/simulation/events` until step 7)."""
    return [event.model_dump(mode="json") for event in audit_events(repository, person_id=person)]


# ── What advance does with a review setting ───────────────────────────────────────────────────


def test_system_closures_record_no_reached_too_late_answer(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _decline_until_case(client, repository)
    _advance(client, "recovery")
    [case] = [item for item in repository.list_cases() if item.status == CaseStatus.RESOLVED]
    assert case.action_history[-1].reviewer == "system"
    assert case.action_history[-1].reached_too_late is None


def test_a_loosening_approved_on_day_d_expires_on_d_plus_1_plus_60(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    approved_on = _active_run(repository).current_day
    _approve_directly(repository, (40, 4), days_ago=0)
    expires = approved_on + timedelta(days=1 + LOOSENED_EXPIRY_DAYS)

    _advance(client, "recovery")
    assert _state(repository)["expires_on_day"] == expires.isoformat()
    while date.fromisoformat(_state(repository)["current_day"]) < expires - timedelta(days=1):
        _advance(client, "recovery")
    last_day = _state(repository)
    assert last_day["current_day"] == (expires - timedelta(days=1)).isoformat()
    assert last_day["live"] == {"severity_pct": 40, "persistence_days": 4}

    _advance(client, "recovery")
    lapsed = _state(repository)
    assert lapsed["current_day"] == expires.isoformat()
    assert lapsed["live"] == {"severity_pct": 40, "persistence_days": 3}
    assert lapsed["live_source"] == "expired"
    [expired] = [item for item in lapsed["decisions"] if item["kind"] == "expired"]
    assert expired["decided_on_day"] == expires.isoformat()
    assert expired["effective_from_day"] == expires.isoformat()
    assert expired["after"] == {"severity_pct": 40, "persistence_days": 3}
    assert lapsed["senior_notice_preview"]["kind"] == "sooner"
    person = client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()
    assert person["review_threshold_notice"]["kind"] == "sooner"

    _advance(client, "recovery")
    assert [item["kind"] for item in _state(repository)["decisions"]].count("expired") == 1


def test_withdrawing_consent_rejects_the_open_proposal(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _decline_until_case(client, repository)
    proposal_id = _insert_agent_proposal(repository)
    assert _state(repository)["open_proposal"] == {"proposal_id": proposal_id}
    response = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/consent",
        json={"active": False, "reason": "No longer wishes to take part."},
    )
    assert response.status_code == 200, response.text

    after = _state(repository)
    assert after["consent_active"] is False
    assert after["open_proposal"] is None
    [rejection] = [item for item in after["decisions"] if item["kind"] == "rejected"]
    assert rejection["proposal_id"] == proposal_id
    assert rejection["rejection_reason"] == "consent_withdrawn"
    assert rejection["decided_by"] == "system"


def test_the_consent_revoked_event_also_rejects_the_open_proposal(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _decline_until_case(client, repository)
    proposal_id = _insert_agent_proposal(repository)
    _advance(client, "consent_revoked")
    after = _state(repository)
    assert after["open_proposal"] is None
    [rejection] = [item for item in after["decisions"] if item["kind"] == "rejected"]
    assert rejection["proposal_id"] == proposal_id
    assert rejection["rejection_reason"] == "consent_withdrawn"


def test_the_senior_notice_appears_for_seven_simulated_days_after_a_loosening(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    state = _state(repository)
    assert (
        client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["review_threshold_notice"] is None
    )
    _approve_directly(repository, (40, 4), days_ago=0)

    def notice() -> dict[str, Any] | None:
        return client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["review_threshold_notice"]

    shown = notice()
    assert shown is not None
    assert shown["kind"] == "later"
    assert shown["shown_from_day"] == state["current_day"]
    for _ in range(SENIOR_NOTICE_DAYS - 1):
        _advance(client, "recovery")
        assert notice() == shown
    _advance(client, "recovery")
    assert notice() is None


def test_the_shadow_check_asks_on_f_plus_3_and_the_revert_is_written_exactly_once(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    # 45% for three days, and a decline that sits between 40% and 45%: the starting setting asks
    # on day three (F); this person's own setting never would.
    _approve_directly(repository, (45, 3))
    days = [_advance(client, "rain_explains_decline")["state"] for _ in range(6)]
    gates = [day["decided_by_gate"] for day in days]
    sustained = [day["signal"]["sustained_low_days"] for day in days]
    first_default = next(
        index
        for index, day in enumerate(days)
        if day["signal"]["sustained_low_days"] >= 3 and day["signal"]["delta_percent"] <= -40
    )
    assert "coordinator_review" not in {day["last_decision"] for day in days[: first_default + 3]}
    assert gates[first_default + 3] == "shadow_check", (gates, sustained)
    assert days[first_default + 3]["last_decision"] == "coordinator_review"
    shadow_day = days[first_default + 3]
    assert shadow_day["rationale"][0].endswith(f"{days[first_default]['current_day']}.")

    reverts = [item for item in _state(repository)["decisions"] if item["kind"] == "reverted"]
    assert len(reverts) == 1
    assert reverts[0]["revert_trigger"] == "shadow_check"
    assert reverts[0]["after"] == {"severity_pct": 40, "persistence_days": 3}
    assert reverts[0]["trigger_case_id"] == _open_case_id(repository)
    counts = _row_counts(repository)

    # Re-reading the shadow day any number of times writes nothing and still says shadow_check.
    for _ in range(3):
        assert client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["decided_by_gate"] == (
            "shadow_check"
        )
        _state(repository)
    assert _row_counts(repository) == counts

    following = _advance(client, "rain_explains_decline")["state"]
    assert following["decided_by_gate"] == "severity_persistence"
    assert following["last_decision"] == "coordinator_review"
    assert [item["kind"] for item in _state(repository)["decisions"]].count("reverted") == 1
    assert _state(repository)["live"] == {"severity_pct": 40, "persistence_days": 3}


def test_resetting_one_persona_resets_only_that_persona(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    assert client.post("/v1/demo/reset", params={"person_id": "mdm-wong"}).status_code == 200
    _advance(client, "activity_declines")
    _advance(client, "activity_declines", "mdm-wong")
    lim_day = client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["current_day"]
    lim_events = _events(repository)
    wong_state = client.get("/v1/people/mdm-wong/state").json()
    anchor_day = date.fromisoformat(wong_state["current_day"]) - timedelta(days=1)

    response = client.post("/v1/demo/reset", params={"person_id": "mdm-wong"})
    assert response.status_code == 200, response.text
    assert response.json()["state"]["person_id"] == "mdm-wong"
    assert response.json()["state"]["display_name"] == "Mdm Wong"
    assert response.json()["state"]["current_day"] == anchor_day.isoformat()
    assert client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["current_day"] == lim_day
    assert _events(repository) == lim_events

    # No `person_id` still means the demo person.
    assert client.post("/v1/demo/reset").json()["state"]["person_id"] == DEMO_PERSON_ID
    assert client.post("/v1/demo/reset", params={"person_id": "nobody-here"}).status_code == 422


def test_the_shadow_revert_supersedes_an_open_proposal_in_the_advance(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (45, 3))
    stale = _insert_agent_proposal(repository, previous=(45, 3), proposed=(45, 4))
    gates = [
        _advance(client, "rain_explains_decline")["state"]["decided_by_gate"] for _ in range(6)
    ]
    assert "shadow_check" in gates
    [superseded] = [
        item for item in _state(repository)["decisions"] if item["proposal_id"] == stale
    ]
    assert superseded["rejection_reason"] == "superseded"


def test_a_same_day_two_level_expiry_names_every_lapsed_approval(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    lower = _approve_directly(
        repository, (40, 4), decision_id="t_lower", days_ago=60, effective_days_ago=59
    )
    upper = _approve_directly(
        repository,
        (40, 5),
        previous=(40, 4),
        decision_id="t_upper",
        days_ago=60,
        effective_days_ago=59,
    )
    assert _state(repository)["live_decision_id"] == upper
    _advance(client, "recovery")
    state = _state(repository)
    assert state["live"] == {"severity_pct": 40, "persistence_days": 3}
    [expired] = [item for item in state["decisions"] if item["kind"] == "expired"]
    assert expired["ends_approval_id"] == upper
    assert expired["after"] == {"severity_pct": 40, "persistence_days": 3}
    [event] = [e for e in _events(repository) if e["event_type"] == "review_threshold_expired"]
    assert event["detail"]["lapsed_approval_ids"] == [upper, lower]


def test_a_shadow_clear_folds_after_an_approval_stamped_during_the_planner_window(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (45, 3))
    for _ in range(5):
        _advance(client, "rain_explains_decline")
    run = _active_run(repository)
    shadow_day = run.current_day + timedelta(days=1)
    with repository.sessions.begin() as session:
        session.add(
            ReviewThresholdDecisionRow(
                decision_id="t_planner_window",
                run_id=run.run_id,
                person_id=DEMO_PERSON_ID,
                kind="approved",
                previous_severity_pct=45,
                previous_persistence_days=3,
                severity_pct=45,
                persistence_days=4,
                decided_by="coordinator",
                decided_on_day=shadow_day,
                effective_from_day=shadow_day + timedelta(days=1),
                decided_at=_utcnow() + timedelta(hours=1),
            )
        )
    state = _advance(client, "rain_explains_decline")["state"]
    assert state["decided_by_gate"] == "shadow_check"
    assert _facts_on(repository, shadow_day + timedelta(days=1)).threshold == (
        DEFAULT_REVIEW_THRESHOLD
    )


@pytest.mark.parametrize("writer", ["consent", "advance"])
def test_a_run_reset_before_the_lock_is_a_conflict_and_writes_nothing(
    client: TestClient,
    repository: SqlAlchemyRepository,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    _decline_until_case(client, repository)
    _insert_agent_proposal(repository)
    counts = _row_counts(repository)
    original = repository._lock_threshold_run

    def deactivate_first(session: Any, run_id: str) -> Any:
        with repository.sessions.begin() as other:
            other.execute(
                update(ScenarioRunRow).where(ScenarioRunRow.run_id == run_id).values(active=False)
            )
        return original(session, run_id)

    monkeypatch.setattr(repository, "_lock_threshold_run", deactivate_first)
    calls = {
        "consent": lambda: client.post(
            f"/v1/people/{DEMO_PERSON_ID}/consent", json={"active": False, "reason": "Stop."}
        ),
        "advance": lambda: client.post(
            "/v1/simulation/advance",
            json={"event": "activity_declines", "person_id": DEMO_PERSON_ID},
        ),
    }
    response = calls[writer]()
    assert response.status_code == 409, response.text
    assert _row_counts(repository) == counts


def test_an_advance_whose_day_moved_while_context_was_fetched_is_a_conflict() -> None:
    from silverloop.context import ExternalContext
    from silverloop.models import ContextSignal

    class RacingProvider:
        def __init__(self) -> None:
            self.repository: SqlAlchemyRepository | None = None
            self.raced = False

        def fetch(self, as_of: Any) -> ExternalContext:
            if not self.raced and self.repository is not None:
                self.raced = True
                # Another advance lands while this one is still fetching, before its lock.
                self.repository.advance("activity_declines", event_id="the-other-advance")
            return ExternalContext(signal=ContextSignal(), evidence=[])

    provider = RacingProvider()
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", context_provider=provider)
    repository.create_schema_for_tests()
    repository.reset()
    provider.repository = repository
    try:
        start = repository.person_state().current_day
        with pytest.raises(StaleRunConflict):
            repository.advance("activity_declines", event_id="the-late-advance")
        assert repository.person_state().current_day == start + timedelta(days=1)
        # With nothing racing, the same provider is read before the lock and the day advances.
        repository.advance("activity_declines", event_id="the-late-advance-retry")
        assert repository.person_state().current_day == start + timedelta(days=2)
    finally:
        repository.close()
