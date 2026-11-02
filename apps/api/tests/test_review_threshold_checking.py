"""Stage 3 of the review-threshold calibrator: checking afterwards (ADR 0008, spec section 7).

Offline (`LLM_ENABLED=false`), through the real repository and `advance()`, with each approval
inserted as the row the (removed, step 7) approve route stored:

- a case opened within the checking period at the far-more-severe bar reverts the loosening;
- the checking period closes `check_confirmed` once, and nothing is checked when nothing changed;
- the shadow check clears every approval it ends, writes one write-up per calibrator approval it
  reverts, and audits a skip it cannot act on.

What a coordinator's review started (reached-too-late reverts, false alarms counted inside the
period, tightening proposals) went with the review route in step 7. The calibration agent's
write-up and tightening tasks are exercised with fake transports in `test_threshold_planner.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop.agent.guardrails import coordinator_text_violations
from silverloop.db_models import ReviewThresholdProposalRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import (
    CaseStatus,
    DailyMetric,
    HumanAction,
    OverrideReason,
    ReviewThresholdDecisionKind,
    ReviewThresholdRevertTrigger,
)
from silverloop.review_threshold import (
    CHECKING_PERIOD_DAYS,
    FAR_MORE_SEVERE_PCT,
    ReviewThreshold,
    ThresholdDecisionFact,
    approval_stack,
    blocked_threshold_values,
    checking_until,
    far_more_severe,
    fixed_write_up_text,
    within_checking_period,
)
from silverloop.sql_repository import WRITE_UP_MAX_ATTEMPTS, SqlAlchemyRepository
from tests.row_fixtures import record_case_review
from tests.test_review_threshold_api import (
    _active_run,
    _advance,
    _approve_directly,
    _events,
    _state,
)

# ── Pure rules ────────────────────────────────────────────────────────────────────────────────


def test_far_more_severe_is_sixty_percent_or_the_floor() -> None:
    assert FAR_MORE_SEVERE_PCT == 60
    assert far_more_severe(-60.0, reached_floor=False)
    assert not far_more_severe(-59.9, reached_floor=False)
    assert not far_more_severe(12.0, reached_floor=False)
    assert far_more_severe(-10.0, reached_floor=True)


def test_the_checking_period_is_fourteen_days_from_the_effective_day() -> None:
    approval = ThresholdDecisionFact(
        decision_id="a",
        kind=ReviewThresholdDecisionKind.APPROVED,
        previous=ReviewThreshold(40, 3),
        after=ReviewThreshold(40, 4),
        decided_on_day=date(2026, 8, 1),
        effective_from_day=date(2026, 8, 2),
        decided_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert CHECKING_PERIOD_DAYS == 14
    assert checking_until(approval) == date(2026, 8, 16)
    assert within_checking_period(approval, date(2026, 8, 2))
    assert within_checking_period(approval, date(2026, 8, 15))
    assert not within_checking_period(approval, date(2026, 8, 16))
    assert not within_checking_period(approval, date(2026, 8, 1))


@pytest.mark.parametrize("trigger", list(ReviewThresholdRevertTrigger))
def test_the_write_up_template_passes_the_coordinator_wording_rule(
    trigger: ReviewThresholdRevertTrigger,
) -> None:
    text = fixed_write_up_text(
        trigger=trigger, previous=ReviewThreshold(45, 4), restored=ReviewThreshold(40, 3)
    )
    assert coordinator_text_violations(text) == []
    assert "will not suggest that looser setting" in text
    assert "more than 40% below usual for at least 3 low days" in text
    assert "being reviewed" not in text
    assert "shadow" not in text.lower() and "floor" not in text.lower()
    assert len(text) <= 1200


# ── What advance does with an approval on record ──────────────────────────────────────────────


def _deeper_declines(monkeypatch: pytest.MonkeyPatch) -> None:
    """Feed a deeper synthetic decline through the real `advance()`: the stock declining day
    bottoms out near 56% below baseline, short of the 60% far-more-severe bar."""
    import silverloop.sql_repository as sql_repository

    def deeper(day: date, previous_low_days: int) -> DailyMetric:
        return DailyMetric(
            day=day,
            steps=max(900, 1700 - previous_low_days * 300),
            active_minutes=max(8, 18 - previous_low_days * 4),
            sleep_hours=6.4,
            wear_hours=13.2,
        )

    monkeypatch.setattr(sql_repository, "_activity_decline_metric", deeper)


def _until_case(client: TestClient, event: str = "activity_declines") -> dict[str, Any]:
    for _ in range(6):
        body = _advance(client, event)
        if body["created_case"] is not None:
            return body
    raise AssertionError("no case was created")


def _reverts(repository: SqlAlchemyRepository) -> list[dict[str, Any]]:
    return [item for item in _state(repository)["decisions"] if item["kind"] == "reverted"]


def _close_after(client: TestClient, days: int, event: str = "recovery") -> None:
    for _ in range(days):
        _advance(client, event)


def _write_ups(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in state["proposals"] if item["output_kind"] == "write_up"]


def _approve_with_proposal(
    repository: SqlAlchemyRepository,
    after: tuple[int, int],
    *,
    previous: tuple[int, int],
    decision_id: str,
    days_ago: int,
    proposer: str,
) -> None:
    from silverloop.db_models import ReviewThresholdDecisionRow
    from silverloop.sql_repository import _utcnow

    run = _active_run(repository)
    proposal_id = f"proposal_{decision_id}"
    with repository.sessions.begin() as session:
        session.add(
            ReviewThresholdProposalRow(
                proposal_id=proposal_id,
                run_id=run.run_id,
                person_id=DEMO_PERSON_ID,
                output_kind="proposal",
                proposer=proposer,
                round_id=f"round_{decision_id}",
                round_index=1,
                previous_severity_pct=previous[0],
                previous_persistence_days=previous[1],
                proposed_severity_pct=after[0],
                proposed_persistence_days=after[1],
                cause="too_tight_for_person",
                reasoning="Fixture proposal.",
                cited_evidence_ids=[],
                trigger_case_id=None,
                trigger_review_ids=[],
                reported_by="coordinator",
                coordinator_reason="not_a_concern",
                write_up_for_decision_id=None,
                agent_run_json=None,
                proposed_on_day=run.current_day - timedelta(days=days_ago),
                proposed_at=_utcnow(),
            )
        )
        session.flush()
        session.add(
            ReviewThresholdDecisionRow(
                decision_id=decision_id,
                run_id=run.run_id,
                person_id=DEMO_PERSON_ID,
                kind="approved",
                proposal_id=proposal_id,
                previous_severity_pct=previous[0],
                previous_persistence_days=previous[1],
                severity_pct=after[0],
                persistence_days=after[1],
                decided_by="coordinator",
                replay_json=None,
                decided_on_day=run.current_day - timedelta(days=days_ago),
                effective_from_day=run.current_day - timedelta(days=days_ago - 1),
                decided_at=_utcnow(),
            )
        )


def test_far_more_severe_on_a_stacked_setting_walks_back_one_step(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approve_directly(repository, (40, 4), decision_id="t_lower", days_ago=3)
    _approve_directly(repository, (45, 4), previous=(40, 4), decision_id="t_upper", days_ago=2)
    _deeper_declines(monkeypatch)
    opening = _until_case(client)
    [revert] = _reverts(repository)
    assert revert["revert_trigger"] == "far_more_severe"
    assert revert["ends_approval_id"] == "t_upper"
    assert revert["after"] == {"severity_pct": 40, "persistence_days": 4}
    assert opening["created_case"] is not None
    _advance(client, "recovery")
    state = _state(repository)
    assert state["live"] == {"severity_pct": 40, "persistence_days": 4}
    assert state["live_decision_id"] == "t_lower"


def test_a_severe_case_after_the_checking_period_does_not_revert(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approve_directly(repository, (45, 3), days_ago=CHECKING_PERIOD_DAYS + 2)
    _deeper_declines(monkeypatch)
    opening = _until_case(client)
    assert opening["state"]["signal"]["delta_percent"] <= -FAR_MORE_SEVERE_PCT
    assert _reverts(repository) == []


def test_when_the_shadow_check_and_far_more_severe_fire_the_same_day_the_shadow_clear_wins(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two cannot both fire on the synthetic personas (a case at 60% for three days is the
    floor's, not the shadow check's), so far-more-severe is forced true for this ordering test."""
    import silverloop.sql_repository as sql_repository

    _approve_directly(repository, (45, 3), decision_id="t_lower", days_ago=3)
    _approve_directly(repository, (45, 4), previous=(45, 3), decision_id="t_upper", days_ago=2)
    monkeypatch.setattr(sql_repository, "far_more_severe", lambda *_, **__: True)
    shadow_day = _until_case(client, "rain_explains_decline")
    assert shadow_day["state"]["decided_by_gate"] == "shadow_check"
    reverts = _reverts(repository)
    assert {item["revert_trigger"] for item in reverts} == {"shadow_check"}
    assert {item["ends_approval_id"] for item in reverts} == {"t_lower", "t_upper"}
    [superseded] = [
        event
        for event in _events(repository)
        if event["event_type"] == "review_threshold_far_more_severe_superseded"
    ]
    assert superseded["detail"]["live_approval_id"] == "t_upper"
    assert superseded["detail"]["trigger_case_id"] == shadow_day["created_case"]["case_id"]
    assert set(superseded["detail"]["shadow_revert_ids"]) == {
        item["decision_id"] for item in reverts
    }
    _advance(client, "recovery")
    assert _state(repository)["live"] == {"severity_pct": 40, "persistence_days": 3}
    run = _active_run(repository)
    with repository.sessions() as session:
        facts = repository._threshold_facts(session, run.run_id)
    assert {ReviewThreshold(45, 3), ReviewThreshold(45, 4)} <= blocked_threshold_values(facts)


def test_fourteen_quiet_days_close_the_check_as_confirmed(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    # Decided 13 days ago, effective 12 days ago: the period closes in two simulated days.
    _approve_directly(repository, (40, 4), days_ago=13)
    state = _state(repository)
    closes = date.fromisoformat(state["current_day"]) + timedelta(days=2)
    _close_after(client, 1)
    assert [i for i in _state(repository)["decisions"] if i["kind"].startswith("check_")] == []
    _close_after(client, 1)
    state = _state(repository)
    [closed] = [item for item in state["decisions"] if item["kind"] == "check_confirmed"]
    assert closed["affects_decision_id"] == "threshold_decision_fixture"
    assert closed["decided_on_day"] == closes.isoformat()
    # It changes nothing about the live value, and is never written twice.
    assert state["live"] == {"severity_pct": 40, "persistence_days": 4}
    _close_after(client, 2)
    kinds = [item["kind"] for item in _state(repository)["decisions"]]
    assert kinds.count("check_confirmed") == 1 and "check_unresolved" not in kinds
    [event] = [e for e in _events(repository) if e["event_type"] == "review_threshold_check_closed"]
    assert event["detail"]["false_alarms_since"] == 0
    assert event["detail"]["trigger_fired"] is False


def test_nothing_changed_means_no_check(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    for _ in range(CHECKING_PERIOD_DAYS + 1):
        _advance(client, "recovery")
    assert _state(repository)["decisions"] == []


def test_a_shadow_clear_records_every_approval_it_ends(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (45, 3), decision_id="t_lower", days_ago=3)
    _approve_directly(repository, (45, 4), previous=(45, 3), decision_id="t_upper", days_ago=2)
    for _ in range(8):
        state = _advance(client, "rain_explains_decline")["state"]
        if state["decided_by_gate"] == "shadow_check":
            break
    assert state["decided_by_gate"] == "shadow_check"
    reverts = [item for item in _state(repository)["decisions"] if item["kind"] == "reverted"]
    assert {item["ends_approval_id"] for item in reverts} == {"t_lower", "t_upper"}
    assert {item["revert_trigger"] for item in reverts} == {"shadow_check"}
    assert all(item["after"] == {"severity_pct": 40, "persistence_days": 3} for item in reverts)
    run = _active_run(repository)
    with repository.sessions() as session:
        facts = repository._threshold_facts(session, run.run_id)
    assert {ReviewThreshold(45, 3), ReviewThreshold(45, 4)} <= blocked_threshold_values(facts)
    assert (
        approval_stack(
            facts,
            today=date.fromisoformat(state["current_day"]) + timedelta(days=1),
            decided_at=facts[-1].decided_at,
        )
        == ()
    )
    notice = client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["review_threshold_notice"]
    assert notice is not None and notice["kind"] == "sooner"


def test_a_lapsed_live_period_never_reads_as_checking_and_closes_on_the_next_advance(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (40, 4), days_ago=20)
    _advance(client, "recovery")
    _advance(client, "recovery")
    closes = [item for item in _state(repository)["decisions"] if item["kind"] == "check_confirmed"]
    assert len(closes) == 1
    assert closes[0]["affects_decision_id"] == "threshold_decision_fixture"


def test_the_shadow_revert_skip_audit_names_its_trigger(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    import silverloop.sql_repository as sql_repository

    _approve_directly(repository, (45, 3))
    monkeypatch.setattr(sql_repository, "never_later", lambda *_: False)
    shadow_day = _until_case(client, "rain_explains_decline")
    assert shadow_day["state"]["decided_by_gate"] == "shadow_check"
    [skipped] = [
        e for e in _events(repository) if e["event_type"] == "review_threshold_revert_skipped"
    ]
    assert skipped["detail"]["revert_trigger"] == "shadow_check"
    assert skipped["detail"]["reason"] == "starting_setting_asks_later"
    assert _reverts(repository) == []


def test_a_multi_row_shadow_clear_owes_one_write_up_per_calibrator_approval(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_with_proposal(
        repository, (45, 3), previous=(40, 3), decision_id="t_lower", days_ago=3, proposer="agent"
    )
    _approve_with_proposal(
        repository,
        (45, 4),
        previous=(45, 3),
        decision_id="t_upper",
        days_ago=2,
        proposer="fixed_rule",
    )
    assert _until_case(client, "rain_explains_decline")["state"]["decided_by_gate"] == (
        "shadow_check"
    )
    reverts = {item["decision_id"]: item for item in _reverts(repository)}
    assert {item["ends_approval_id"] for item in reverts.values()} == {"t_lower", "t_upper"}
    write_ups = _write_ups(_state(repository))
    assert sorted(item["write_up_for_decision_id"] for item in write_ups) == sorted(reverts)
    for item in write_ups:
        assert coordinator_text_violations(item["reasoning"]) == []


def test_the_shadow_clear_ends_an_approval_pending_for_tomorrow_too(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An approval decided for tomorrow while the shadow day's advance sat between its phases
    (simulated by inserting it as the write phase takes the run lock)."""
    from silverloop.db_models import ReviewThresholdDecisionRow
    from silverloop.sql_repository import _utcnow

    _approve_directly(repository, (45, 3), decision_id="t_live", days_ago=3)
    original = SqlAlchemyRepository._lock_active_run
    inserted: list[str] = []

    def lock_then_race(self: SqlAlchemyRepository, session: Any, run_id: str) -> Any:
        run = original(self, session, run_id)
        state, _ = self._resolve_decision_state(session, run)
        if state.decided_by_gate.value == "shadow_check" and not inserted:
            session.add(
                ReviewThresholdDecisionRow(
                    decision_id="t_pending",
                    run_id=run.run_id,
                    person_id=DEMO_PERSON_ID,
                    kind="approved",
                    previous_severity_pct=45,
                    previous_persistence_days=3,
                    severity_pct=45,
                    persistence_days=4,
                    decided_by="coordinator",
                    replay_json=None,
                    decided_on_day=run.current_day,
                    effective_from_day=run.current_day + timedelta(days=1),
                    decided_at=_utcnow(),
                )
            )
            session.flush()
            inserted.append("t_pending")
        return run

    monkeypatch.setattr(SqlAlchemyRepository, "_lock_active_run", lock_then_race)
    shadow_day = _until_case(client, "rain_explains_decline")
    assert shadow_day["state"]["decided_by_gate"] == "shadow_check"
    assert inserted == ["t_pending"]
    reverts = _reverts(repository)
    assert {item["ends_approval_id"] for item in reverts} == {"t_live", "t_pending"}
    assert {item["revert_trigger"] for item in reverts} == {"shadow_check"}
    monkeypatch.setattr(SqlAlchemyRepository, "_lock_active_run", original)
    _advance(client, "recovery")
    assert _state(repository)["live"] == {"severity_pct": 40, "persistence_days": 3}
    run = _active_run(repository)
    with repository.sessions() as session:
        facts = repository._threshold_facts(session, run.run_id)
    assert {ReviewThreshold(45, 3), ReviewThreshold(45, 4)} <= blocked_threshold_values(facts)


def test_a_shadow_day_with_nothing_left_to_clear_audits_the_skip(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    from silverloop.db_models import ReviewThresholdDecisionRow
    from silverloop.sql_repository import _utcnow

    _approve_directly(repository, (45, 3), decision_id="t_live", days_ago=3)
    original = SqlAlchemyRepository._lock_active_run

    def lock_then_end(self: SqlAlchemyRepository, session: Any, run_id: str) -> Any:
        run = original(self, session, run_id)
        state, _ = self._resolve_decision_state(session, run)
        if state.decided_by_gate.value == "shadow_check" and not session.get(
            ReviewThresholdDecisionRow, "t_already_ended"
        ):
            session.add(
                ReviewThresholdDecisionRow(
                    decision_id="t_already_ended",
                    run_id=run.run_id,
                    person_id=DEMO_PERSON_ID,
                    kind="reverted",
                    ends_approval_id="t_live",
                    revert_trigger="reached_too_late",
                    previous_severity_pct=45,
                    previous_persistence_days=3,
                    severity_pct=40,
                    persistence_days=3,
                    decided_by="system",
                    replay_json=None,
                    decided_on_day=run.current_day,
                    effective_from_day=run.current_day + timedelta(days=1),
                    decided_at=_utcnow(),
                )
            )
            session.flush()
        return run

    monkeypatch.setattr(SqlAlchemyRepository, "_lock_active_run", lock_then_end)
    shadow_day = _until_case(client, "rain_explains_decline")
    assert shadow_day["state"]["decided_by_gate"] == "shadow_check"
    assert {item["revert_trigger"] for item in _reverts(repository)} == {"reached_too_late"}
    [skipped] = [
        e for e in _events(repository) if e["event_type"] == "review_threshold_revert_skipped"
    ]
    assert skipped["detail"]["reason"] == "nothing_to_clear"
    assert skipped["detail"]["revert_trigger"] == "shadow_check"
    assert skipped["detail"]["day"] == shadow_day["state"]["current_day"]


def test_a_revert_skip_outside_the_period_is_not_a_trigger(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    from silverloop.db_models import AuditEventRow
    from silverloop.sql_repository import _utcnow

    _approve_directly(repository, (40, 4), days_ago=13)
    run = _active_run(repository)
    with repository.sessions.begin() as session:
        for day in (run.current_day - timedelta(days=20), None):
            detail: dict[str, Any] = {"live_approval_id": "threshold_decision_fixture"}
            if day is not None:
                detail["day"] = day.isoformat()
            session.add(
                AuditEventRow(
                    event_id=f"evt_skip_{'undated' if day is None else 'early'}",
                    run_id=run.run_id,
                    person_id=DEMO_PERSON_ID,
                    event_type="review_threshold_revert_skipped",
                    actor="system",
                    decision=None,
                    detail_json=detail,
                    recorded_at=_utcnow(),
                )
            )
    _advance(client, "recovery")
    _advance(client, "recovery")
    kinds = [item["kind"] for item in _state(repository)["decisions"]]
    assert "check_confirmed" in kinds and "check_unresolved" not in kinds
    [event] = [e for e in _events(repository) if e["event_type"] == "review_threshold_check_closed"]
    assert event["detail"]["false_alarms_since"] == 0


# ── Closing a checking period unresolved ──────────────────────────────────────────────────────
#
# A coordinator's review used to be recorded through `POST /v1/cases/{id}/review` (removed in
# step 7); it is written here as the row that route stored (`tests/row_fixtures.py`). What is under
# test is the close `advance` writes over the period.


def _today(repository: SqlAlchemyRepository) -> date:
    return date.fromisoformat(_state(repository)["current_day"])


def _checks(repository: SqlAlchemyRepository) -> list[dict[str, Any]]:
    return [item for item in _state(repository)["decisions"] if item["kind"].startswith("check_")]


def _closed_events(repository: SqlAlchemyRepository) -> list[dict[str, Any]]:
    return [e for e in _events(repository) if e["event_type"] == "review_threshold_check_closed"]


def _false_alarm_review(
    repository: SqlAlchemyRepository, case_id: str, reason: OverrideReason
) -> None:
    record_case_review(
        repository,
        case_id,
        CaseStatus.RESOLVED,
        "Her usual week-to-week swing.",
        human_action=HumanAction.OVERRIDE,
        override_reason=reason,
    )


def _advance_until(client: TestClient, repository: SqlAlchemyRepository, day: date) -> None:
    while _today(repository) < day:
        _advance(client, "recovery")


def test_a_false_alarm_in_the_checking_period_closes_it_as_unresolved(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (40, 4), days_ago=5)
    closes = _today(repository) + timedelta(days=10)
    case_id = _until_case(client)["created_case"]["case_id"]
    _false_alarm_review(repository, case_id, OverrideReason.NOT_A_CONCERN)
    assert _today(repository) < closes
    _advance_until(client, repository, closes)
    [closed] = _checks(repository)
    assert closed["kind"] == "check_unresolved"
    assert closed["affects_decision_id"] == "threshold_decision_fixture"
    assert closed["decided_on_day"] == closes.isoformat()
    [event] = _closed_events(repository)
    assert (event["detail"]["false_alarms_since"], event["detail"]["trigger_fired"]) == (1, False)
    _advance(client, "recovery")
    assert len(_checks(repository)) == 1


def test_a_known_context_override_in_the_period_counts_as_a_false_alarm(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (40, 4), days_ago=5)
    closes = _today(repository) + timedelta(days=10)
    case_id = _until_case(client)["created_case"]["case_id"]
    _false_alarm_review(repository, case_id, OverrideReason.KNOWN_CONTEXT)
    _advance_until(client, repository, closes)
    assert [item["kind"] for item in _checks(repository)] == ["check_unresolved"]
    [event] = _closed_events(repository)
    assert event["detail"]["false_alarms_since"] == 1


def test_a_trigger_alone_closes_the_period_unresolved(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shadow check fires but the revert is skipped (audited by the advance itself); with no
    false alarm in the period the close is still unresolved, because a trigger fired."""
    import silverloop.sql_repository as sql_repository

    _approve_directly(repository, (45, 3), days_ago=3)
    closes = _today(repository) + timedelta(days=CHECKING_PERIOD_DAYS - 2)
    with monkeypatch.context() as patch:
        patch.setattr(sql_repository, "never_later", lambda *_: False)
        shadow_day = _until_case(client, "rain_explains_decline")
    assert shadow_day["state"]["decided_by_gate"] == "shadow_check"
    assert [e for e in _events(repository) if e["event_type"] == "review_threshold_revert_skipped"]
    assert _reverts(repository) == []
    _advance_until(client, repository, closes)
    [closed] = _checks(repository)
    assert closed["kind"] == "check_unresolved"
    [event] = _closed_events(repository)
    assert (event["detail"]["false_alarms_since"], event["detail"]["trigger_fired"]) == (0, True)


def test_a_case_opened_on_the_close_day_is_outside_the_period(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case opens on the close day and is reviewed as a false alarm before any close runs
    (the close is held back for those advances); the next advance closes over
    `[effective, checking_until)`, which does not include that day."""
    _approve_directly(repository, (40, 4), days_ago=11)
    closes = _today(repository) + timedelta(days=4)
    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyRepository, "_close_checking_period", lambda *_: [])
        case_id = _until_case(client)["created_case"]["case_id"]
        assert _today(repository) == closes
        _false_alarm_review(repository, case_id, OverrideReason.KNOWN_CONTEXT)
        assert _checks(repository) == []
    _advance(client, "recovery")
    assert [item["kind"] for item in _checks(repository)] == ["check_confirmed"]
    [event] = _closed_events(repository)
    assert event["detail"]["false_alarms_since"] == 0


def test_a_closed_check_keeps_its_frozen_count_after_a_later_false_alarm(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    # Effective 9 days ago: the period is [D-9, D+5); a case opens inside it and is only reviewed
    # after the close on D+5.
    _approve_directly(repository, (40, 4), days_ago=10)
    closes = _today(repository) + timedelta(days=5)
    case_id = _until_case(client)["created_case"]["case_id"]
    assert _today(repository) < closes
    while _today(repository) < closes:
        _advance(client, "activity_declines")
    assert [item["kind"] for item in _checks(repository)] == ["check_confirmed"]
    _false_alarm_review(repository, case_id, OverrideReason.NOT_A_CONCERN)
    _advance(client, "activity_declines")
    assert [item["kind"] for item in _checks(repository)] == ["check_confirmed"]
    [event] = _closed_events(repository)
    assert event["detail"]["false_alarms_since"] == 0


def test_a_covered_lower_approval_closes_its_own_period_once_it_is_live_again(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1 45%/3 days ran out its period under A2 45%/4 days; a far-more-severe case ends A2 only,
    and A1 is closed on the first advance it is live, over its own period."""
    _approve_directly(repository, (45, 3), decision_id="t_a1", days_ago=20)
    _approve_directly(repository, (45, 4), previous=(45, 3), decision_id="t_a2", days_ago=5)
    _deeper_declines(monkeypatch)
    _until_case(client)
    [revert] = _reverts(repository)
    assert revert["ends_approval_id"] == "t_a2"
    assert revert["after"] == {"severity_pct": 45, "persistence_days": 3}
    assert _checks(repository) == []
    _advance(client, "recovery")
    state = _state(repository)
    assert state["live_decision_id"] == "t_a1"
    [closed] = _checks(repository)
    assert closed["kind"] == "check_confirmed"
    assert closed["affects_decision_id"] == "t_a1"
    _advance(client, "recovery")
    assert len(_checks(repository)) == 1


# ── Write-ups the advance owes for a revert it made ───────────────────────────────────────────


def _write_up_rows(repository: SqlAlchemyRepository) -> list[ReviewThresholdProposalRow]:
    with repository.sessions() as session:
        return list(
            session.scalars(
                select(ReviewThresholdProposalRow).where(
                    ReviewThresholdProposalRow.output_kind == "write_up"
                )
            )
        )


def test_a_shadow_revert_of_a_fixed_rule_approval_yields_exactly_one_template_write_up(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_with_proposal(
        repository,
        (45, 3),
        previous=(40, 3),
        decision_id="t_live",
        days_ago=3,
        proposer="fixed_rule",
    )
    shadow_day = _until_case(client, "rain_explains_decline")
    assert shadow_day["state"]["decided_by_gate"] == "shadow_check"
    [revert] = _reverts(repository)
    assert revert["ends_approval_id"] == "t_live"
    assert (
        revert["decision_id"]
        in (shadow_day["audit_event"]["detail"]["review_threshold_decision_ids"])
    )

    [write_up] = _write_up_rows(repository)
    assert write_up.write_up_for_decision_id == revert["decision_id"]
    assert write_up.proposer == "fixed_rule"
    assert write_up.proposed_severity_pct is None and write_up.proposed_persistence_days is None
    assert write_up.cause is None
    assert write_up.reasoning == fixed_write_up_text(
        trigger=ReviewThresholdRevertTrigger.SHADOW_CHECK,
        previous=ReviewThreshold(45, 3),
        restored=ReviewThreshold(40, 3),
    )
    assert coordinator_text_violations(write_up.reasoning) == []
    assert list(write_up.cited_evidence_ids) == [revert["decision_id"], "t_live"]
    run = write_up.agent_run_json
    assert run is not None
    assert (run["task"], run["mode"], run["cause"]) == ("write_up", "fallback_disabled", None)
    assert (
        run["fallback_reason"] == "LLM_ENABLED is false, so the fixed write-up template was used."
    )

    # Idempotent: a second attempt for the same revert, or a later advance, writes nothing.
    repository._write_up_revert(_active_run(repository).run_id, revert["decision_id"])
    _advance(client, "recovery")
    assert len(_write_up_rows(repository)) == 1
    [audit] = [
        e for e in _events(repository) if e["event_type"] == "review_threshold_write_up_recorded"
    ]
    assert audit["detail"]["write_up_for_decision_id"] == revert["decision_id"]
    assert write_up.reasoning not in str(_events(repository))


def test_a_failing_write_up_is_abandoned_after_three_attempts(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("write-up exploded")

    monkeypatch.setattr(SqlAlchemyRepository, "_write_up_revert", broken)
    _approve_with_proposal(
        repository,
        (45, 3),
        previous=(40, 3),
        decision_id="t_live",
        days_ago=3,
        proposer="fixed_rule",
    )
    assert _until_case(client, "rain_explains_decline")["state"]["decided_by_gate"] == (
        "shadow_check"
    )
    [revert] = _reverts(repository)
    for _ in range(4):
        _advance(client, "recovery")
    events = _events(repository)
    discarded = [e for e in events if e["event_type"] == "review_threshold_write_up_discarded"]
    abandoned = [e for e in events if e["event_type"] == "review_threshold_write_up_abandoned"]
    assert len(discarded) == WRITE_UP_MAX_ATTEMPTS == 3
    assert {e["detail"]["write_up_for_decision_id"] for e in discarded} == {revert["decision_id"]}
    assert len(abandoned) == 1
    assert abandoned[0]["detail"]["attempts"] == 3
    assert "exploded" not in str(events)
    assert _write_up_rows(repository) == []
