"""Stage 3 of the review-threshold calibrator: checking afterwards (ADR 0008, spec section 7).

Offline (`LLM_ENABLED=false`), through the real repository and HTTP contract:

- a case opened within the checking period at the far-more-severe bar reverts the loosening;
- the checking period closes `check_confirmed` or `check_unresolved`, and the card shows it;
- every revert of an agent or fixed-rule approval yields exactly one write-up that passes the
  coordinator wording rule and shows in the card's history; reverted values are never re-proposed;
- "this should have reached me sooner" with nothing loosened starts a one-step-sooner proposal;
- a shadow-check revert records every approval it clears.

The calibration agent's write-up and tightening tasks are exercised with fake transports in
`test_threshold_planner.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from silverloop.agent.guardrails import coordinator_text_violations
from silverloop.db_models import ReviewThresholdProposalRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import DailyMetric, ReviewThresholdDecisionKind, ReviewThresholdRevertTrigger
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
from silverloop.sql_repository import SqlAlchemyRepository
from tests.test_review_threshold_api import (
    _active_run,
    _advance,
    _approve,
    _approve_directly,
    _decline_until_case,
    _events,
    _loosened_and_live,
    _mark_too_late,
    _proposal_after_two_false_alarms,
    _reject,
    _review,
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


# ── far_more_severe ───────────────────────────────────────────────────────────────────────────


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


def _reverts(client: TestClient) -> list[dict[str, Any]]:
    return [item for item in _state(client)["decisions"] if item["kind"] == "reverted"]


def test_a_real_sixty_percent_case_within_the_checking_period_reverts_and_is_written_up(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = _loosened_and_live(client)
    _deeper_declines(monkeypatch)
    opening = _until_case(client)
    assert opening["state"]["signal"]["delta_percent"] <= -FAR_MORE_SEVERE_PCT
    [revert] = _reverts(client)
    assert revert["revert_trigger"] == "far_more_severe"
    assert revert["ends_approval_id"] == live["live_decision_id"]
    assert revert["after"] == {"severity_pct": 40, "persistence_days": 3}
    assert revert["trigger_case_id"] == opening["created_case"]["case_id"]
    assert revert["trigger_review_id"] is None
    assert (
        revert["effective_from_day"]
        == (date.fromisoformat(opening["state"]["current_day"]) + timedelta(days=1)).isoformat()
    )
    assert (
        revert["decision_id"] in opening["audit_event"]["detail"]["review_threshold_decision_ids"]
    )
    # The advance wrote the fixed-rule approval's write-up after its commit.
    [write_up] = _write_ups(_state(client))
    assert write_up["write_up_for_decision_id"] == revert["decision_id"]
    assert write_up["reasoning"] == fixed_write_up_text(
        trigger=ReviewThresholdRevertTrigger.FAR_MORE_SEVERE,
        previous=ReviewThreshold(40, 4),
        restored=ReviewThreshold(40, 3),
    )
    # Written once: the case refreshes on later days, it is not created again.
    _advance(client, "activity_declines")
    assert len(_reverts(client)) == 1
    assert len(_write_ups(_state(client))) == 1
    check = _state(client)["check"]
    assert check["status"] == "reverted"
    assert check["approval_decision_id"] == live["live_decision_id"]


def test_far_more_severe_on_a_stacked_setting_walks_back_one_step(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approve_directly(repository, (40, 4), decision_id="t_lower", days_ago=3)
    _approve_directly(repository, (45, 4), previous=(40, 4), decision_id="t_upper", days_ago=2)
    _deeper_declines(monkeypatch)
    opening = _until_case(client)
    [revert] = _reverts(client)
    assert revert["revert_trigger"] == "far_more_severe"
    assert revert["ends_approval_id"] == "t_upper"
    assert revert["after"] == {"severity_pct": 40, "persistence_days": 4}
    assert opening["created_case"] is not None
    _advance(client, "recovery")
    state = _state(client)
    assert state["live"] == {"severity_pct": 40, "persistence_days": 4}
    assert state["live_decision_id"] == "t_lower"


def test_a_severe_case_after_the_checking_period_does_not_revert(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approve_directly(repository, (45, 3), days_ago=CHECKING_PERIOD_DAYS + 2)
    _deeper_declines(monkeypatch)
    opening = _until_case(client)
    assert opening["state"]["signal"]["delta_percent"] <= -FAR_MORE_SEVERE_PCT
    assert _reverts(client) == []


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
    reverts = _reverts(client)
    assert {item["revert_trigger"] for item in reverts} == {"shadow_check"}
    assert {item["ends_approval_id"] for item in reverts} == {"t_lower", "t_upper"}
    [superseded] = [
        event
        for event in _events(client)
        if event["event_type"] == "review_threshold_far_more_severe_superseded"
    ]
    assert superseded["detail"]["live_approval_id"] == "t_upper"
    assert superseded["detail"]["trigger_case_id"] == shadow_day["created_case"]["case_id"]
    assert set(superseded["detail"]["shadow_revert_ids"]) == {
        item["decision_id"] for item in reverts
    }
    _advance(client, "recovery")
    assert _state(client)["live"] == {"severity_pct": 40, "persistence_days": 3}
    run = _active_run(repository)
    with repository.sessions() as session:
        facts = repository._threshold_facts(session, run.run_id)
    assert {ReviewThreshold(45, 3), ReviewThreshold(45, 4)} <= blocked_threshold_values(facts)


# ── The checking period ───────────────────────────────────────────────────────────────────────


def _close_after(client: TestClient, days: int, event: str = "recovery") -> None:
    for _ in range(days):
        _advance(client, event)


def test_fourteen_quiet_days_close_the_check_as_confirmed(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    # Decided 13 days ago, effective 12 days ago: the period closes in two simulated days.
    _approve_directly(repository, (40, 4), days_ago=13)
    state = _state(client)
    check = state["check"]
    assert check["status"] == "checking"
    closes = date.fromisoformat(state["current_day"]) + timedelta(days=2)
    assert check["checking_until_day"] == closes.isoformat()
    assert check["false_alarms_since"] == 0
    _close_after(client, 1)
    assert _state(client)["check"]["status"] == "checking"
    _close_after(client, 1)
    state = _state(client)
    [closed] = [item for item in state["decisions"] if item["kind"] == "check_confirmed"]
    assert closed["affects_decision_id"] == "threshold_decision_fixture"
    assert closed["decided_on_day"] == closes.isoformat()
    assert state["check"]["status"] == "confirmed"
    # It changes nothing about the live value, and is never written twice.
    assert state["live"] == {"severity_pct": 40, "persistence_days": 4}
    _close_after(client, 2)
    kinds = [item["kind"] for item in _state(client)["decisions"]]
    assert kinds.count("check_confirmed") == 1 and "check_unresolved" not in kinds
    [event] = [e for e in _events(client) if e["event_type"] == "review_threshold_check_closed"]
    assert event["detail"]["false_alarms_since"] == 0
    assert event["detail"]["trigger_fired"] is False


def test_a_false_alarm_in_the_checking_period_closes_it_as_unresolved(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (40, 4), days_ago=5)
    closes = date.fromisoformat(_state(client)["current_day"]) + timedelta(days=10)
    case_id = _decline_until_case(client)
    _review(client, case_id, human_action="override", override_reason="not_a_concern")
    assert _state(client)["check"]["false_alarms_since"] == 1
    remaining = (closes - date.fromisoformat(_state(client)["current_day"])).days
    assert remaining > 0
    _close_after(client, remaining)
    state = _state(client)
    assert state["current_day"] == closes.isoformat()
    assert [item["kind"] for item in state["decisions"]].count("check_unresolved") == 1
    assert state["check"] == {
        "approval_decision_id": "threshold_decision_fixture",
        "checking_until_day": closes.isoformat(),
        "false_alarms_since": 1,
        "status": "unresolved",
    }


def test_nothing_changed_means_no_check(client: TestClient) -> None:
    assert _state(client)["check"] is None


# ── Write-ups ─────────────────────────────────────────────────────────────────────────────────


def _write_ups(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in state["proposals"] if item["output_kind"] == "write_up"]


def test_a_revert_of_a_fixed_rule_approval_yields_exactly_one_template_write_up(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    live = _loosened_and_live(client)
    _mark_too_late(client, _decline_until_case(client))
    state = _state(client)
    [revert] = [item for item in state["decisions"] if item["kind"] == "reverted"]
    [write_up] = _write_ups(state)
    assert write_up["write_up_for_decision_id"] == revert["decision_id"]
    assert write_up["proposer"] == "fixed_rule"
    assert write_up["status"] == "not_applicable"
    assert write_up["proposed"] is None and write_up["cause"] is None
    assert write_up["reasoning"] == fixed_write_up_text(
        trigger=ReviewThresholdRevertTrigger.REACHED_TOO_LATE,
        previous=ReviewThreshold(40, 4),
        restored=ReviewThreshold(40, 3),
    )
    assert coordinator_text_violations(write_up["reasoning"]) == []
    assert write_up["cited_evidence_ids"] == [revert["decision_id"], live["live_decision_id"]]
    run = write_up["agent_run"]
    assert (run["task"], run["mode"], run["cause"]) == ("write_up", "fallback_disabled", None)
    assert (
        run["fallback_reason"] == "LLM_ENABLED is false, so the fixed write-up template was used."
    )
    assert state["open_proposal"] is None

    # Idempotent: a second attempt for the same revert writes nothing.
    repository._write_up_revert(_active_run(repository).run_id, revert["decision_id"])
    with repository.sessions() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ReviewThresholdProposalRow)
            .where(ReviewThresholdProposalRow.output_kind == "write_up")
        )
    assert count == 1
    [audit] = [
        e for e in _events(client) if e["event_type"] == "review_threshold_write_up_recorded"
    ]
    assert audit["detail"]["write_up_for_decision_id"] == revert["decision_id"]
    assert write_up["reasoning"] not in str(_events(client))


def test_a_revert_of_a_directly_set_approval_owes_no_write_up(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (40, 4))
    _mark_too_late(client, _decline_until_case(client))
    state = _state(client)
    assert [item["kind"] for item in state["decisions"]].count("reverted") == 1
    assert _write_ups(state) == []


def test_a_reverted_value_is_never_proposed_again(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _loosened_and_live(client)
    _mark_too_late(client, _decline_until_case(client))
    for _ in range(8):  # past the cooldown
        _advance(client, "recovery")
    for _ in range(2):
        _review(
            client,
            _decline_until_case(client),
            human_action="override",
            override_reason="not_a_concern",
        )
        _advance(client, "recovery")
    proposed = [
        item["proposed"]
        for item in _state(client)["proposals"]
        if item["output_kind"] == "proposal" and item["status"] == "open"
    ]
    assert {"severity_pct": 40, "persistence_days": 4} not in proposed
    run = _active_run(repository)
    with repository.sessions() as session:
        facts = repository._threshold_facts(session, run.run_id)
    assert ReviewThreshold(40, 4) in blocked_threshold_values(facts)


# ── Tightening ────────────────────────────────────────────────────────────────────────────────


def test_a_late_review_with_nothing_loosened_proposes_one_step_sooner(
    client: TestClient,
) -> None:
    _mark_too_late(client, _decline_until_case(client))
    state = _state(client)
    proposal = state["open_proposal"]
    assert proposal is not None
    assert proposal["proposer"] == "fixed_rule"
    assert proposal["previous"] == {"severity_pct": 40, "persistence_days": 3}
    assert proposal["proposed"] == {"severity_pct": 35, "persistence_days": 3}
    assert proposal["cause"] is None
    assert proposal["agent_run"]["task"] == "tighten"
    assert state["decisions"] == []
    assert state["live"] == {"severity_pct": 40, "persistence_days": 3}
    # Normal approval: a tightening needs no confirmed cause and no cooldown.
    approved = _approve(
        client, proposal["proposal_id"], state["current_day"], cause_confirmed=False
    )
    assert approved.status_code == 200, approved.text
    _advance(client, "recovery")
    assert _state(client)["live"] == {"severity_pct": 35, "persistence_days": 3}


def test_rejecting_a_tightening_ends_its_round(client: TestClient) -> None:
    _mark_too_late(client, _decline_until_case(client))
    proposal = _state(client)["open_proposal"]
    assert proposal is not None
    assert _reject(client, proposal["proposal_id"], "prefer_other_change").status_code == 200
    state = _state(client)
    assert state["open_proposal"] is None
    assert [item["output_kind"] for item in state["proposals"]] == ["proposal"]


# ── Shadow check clears every approval, on record ─────────────────────────────────────────────


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
    reverts = [item for item in _state(client)["decisions"] if item["kind"] == "reverted"]
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


# ── Review fixes: lapsed closes, reverted counting, supersede, tighten preference, catch-up ─────


def test_a_lapsed_live_period_never_reads_as_checking_and_closes_on_the_next_advance(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (40, 4), days_ago=20)
    state = _state(client)
    ended = date.fromisoformat(state["current_day"]) - timedelta(days=5)
    assert state["check"] == {
        "approval_decision_id": "threshold_decision_fixture",
        "checking_until_day": ended.isoformat(),
        "false_alarms_since": 0,
        "status": "confirmed",
    }
    _advance(client, "recovery")
    _advance(client, "recovery")
    closes = [item for item in _state(client)["decisions"] if item["kind"] == "check_confirmed"]
    assert len(closes) == 1
    assert _state(client)["check"]["status"] == "confirmed"


def test_a_covered_lower_approval_closes_its_own_period_once_it_is_live_again(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    """A1 45%/3 days ran out its period under A2 45%/4 days; a late mark ends A2 only, and A1 is
    closed on the first advance it is live, over its own period."""
    _approve_directly(repository, (45, 3), decision_id="t_a1", days_ago=20)
    _approve_directly(repository, (45, 4), previous=(45, 3), decision_id="t_a2", days_ago=5)
    state = _state(client)
    assert state["check"]["approval_decision_id"] == "t_a2"
    assert state["check"]["status"] == "checking"
    a1_until = date.fromisoformat(state["current_day"]) - timedelta(days=5)
    _mark_too_late(client, _decline_until_case(client))
    [revert] = _reverts(client)
    assert revert["ends_approval_id"] == "t_a2"
    assert revert["after"] == {"severity_pct": 45, "persistence_days": 3}
    assert [item for item in _state(client)["decisions"] if item["kind"].startswith("check_")] == []
    _advance(client, "recovery")
    state = _state(client)
    assert state["live_decision_id"] == "t_a1"
    [closed] = [item for item in state["decisions"] if item["kind"].startswith("check_")]
    assert closed["kind"] == "check_confirmed"
    assert closed["affects_decision_id"] == "t_a1"
    assert state["check"] == {
        "approval_decision_id": "t_a1",
        "checking_until_day": a1_until.isoformat(),
        "false_alarms_since": 0,
        "status": "confirmed",
    }
    _advance(client, "recovery")
    assert [item["kind"] for item in _state(client)["decisions"]].count("check_confirmed") == 1


def test_a_trigger_alone_closes_the_period_unresolved(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    import silverloop.sql_repository as sql_repository
    from silverloop.review_threshold import RevertSkipped

    _approve_directly(repository, (40, 4), days_ago=5)
    closes = date.fromisoformat(_state(client)["current_day"]) + timedelta(days=10)
    case_id = _decline_until_case(client)
    with monkeypatch.context() as patch:
        patch.setattr(
            sql_repository,
            "reached_too_late_revert",
            lambda *_, **__: RevertSkipped("no_setting_asks_sooner"),
        )
        _mark_too_late(client, case_id)
    assert _reverts(client) == []
    remaining = (closes - date.fromisoformat(_state(client)["current_day"])).days
    for _ in range(remaining):
        _advance(client, "recovery")
    state = _state(client)
    [closed] = [item for item in state["decisions"] if item["kind"].startswith("check_")]
    assert closed["kind"] == "check_unresolved"
    assert state["check"]["false_alarms_since"] == 0
    assert state["check"]["status"] == "unresolved"
    [event] = [e for e in _events(client) if e["event_type"] == "review_threshold_check_closed"]
    assert event["detail"] == {**event["detail"], "false_alarms_since": 0, "trigger_fired": True}


def test_a_reverted_check_names_the_approval_live_when_reverted(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (45, 3), decision_id="t_lower", days_ago=3)
    _approve_directly(repository, (45, 4), previous=(45, 3), decision_id="t_upper", days_ago=2)
    shadow_day = _until_case(client, "rain_explains_decline")
    assert shadow_day["state"]["decided_by_gate"] == "shadow_check"
    assert len(_reverts(client)) == 2
    # Reverts take effect tomorrow: on the day itself the approval is still live.
    assert _state(client)["check"]["approval_decision_id"] == "t_upper"
    _advance(client, "recovery")
    check = _state(client)["check"]
    assert check["status"] == "reverted"
    assert check["approval_decision_id"] == "t_upper"


def test_a_late_mark_supersedes_an_open_loosening_and_proposes_sooner(client: TestClient) -> None:
    state = _proposal_after_two_false_alarms(client)
    loosening = state["open_proposal"]
    _advance(client, "recovery")
    review = _mark_too_late(client, _decline_until_case(client))
    state = _state(client)
    [superseded] = [
        item for item in state["decisions"] if item["proposal_id"] == loosening["proposal_id"]
    ]
    assert (superseded["kind"], superseded["rejection_reason"]) == ("rejected", "superseded")
    assert superseded["trigger_review_id"] == review["review_evidence_id"]
    proposal = state["open_proposal"]
    assert proposal is not None
    assert proposal["proposed"] == {"severity_pct": 35, "persistence_days": 3}
    assert proposal["agent_run"]["task"] == "tighten"
    assert not [
        e
        for e in _events(client)
        if e["event_type"] == "review_threshold_calibration_skipped"
        and e["detail"]["reason"] == "proposal_open"
    ]


@pytest.mark.parametrize("reason", ["known_context", "data_doubt"])
def test_a_late_mark_prefers_tightening_over_calibrating_a_false_alarm(
    client: TestClient, reason: str
) -> None:
    _review(
        client,
        _decline_until_case(client),
        human_action="override",
        override_reason=reason,
        reached_too_late=True,
    )
    [proposal] = _state(client)["proposals"]
    assert proposal["output_kind"] == "proposal"
    assert proposal["proposed"] == {"severity_pct": 35, "persistence_days": 3}
    assert proposal["agent_run"]["task"] == "tighten"


def test_the_shadow_revert_skip_audit_names_its_trigger(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    import silverloop.sql_repository as sql_repository

    _approve_directly(repository, (45, 3))
    monkeypatch.setattr(sql_repository, "never_later", lambda *_: False)
    shadow_day = _until_case(client, "rain_explains_decline")
    assert shadow_day["state"]["decided_by_gate"] == "shadow_check"
    [skipped] = [e for e in _events(client) if e["event_type"] == "review_threshold_revert_skipped"]
    assert skipped["detail"]["revert_trigger"] == "shadow_check"
    assert skipped["detail"]["reason"] == "starting_setting_asks_later"
    assert _reverts(client) == []


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
    reverts = {item["decision_id"]: item for item in _reverts(client)}
    assert {item["ends_approval_id"] for item in reverts.values()} == {"t_lower", "t_upper"}
    write_ups = _write_ups(_state(client))
    assert sorted(item["write_up_for_decision_id"] for item in write_ups) == sorted(reverts)
    for item in write_ups:
        assert coordinator_text_violations(item["reasoning"]) == []


def test_a_write_up_lost_to_a_crash_is_caught_up_by_the_next_advance(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _loosened_and_live(client)
    case_id = _decline_until_case(client)
    with monkeypatch.context() as patch:
        # The process "dies" between the review's commit and its follow-ups.
        patch.setattr(SqlAlchemyRepository, "_run_threshold_follow_ups", lambda *_: None)
        _mark_too_late(client, case_id)
    assert len(_reverts(client)) == 1
    assert _write_ups(_state(client)) == []
    _advance(client, "recovery")
    [write_up] = _write_ups(_state(client))
    assert write_up["write_up_for_decision_id"] == _reverts(client)[0]["decision_id"]
    _advance(client, "recovery")
    assert len(_write_ups(_state(client))) == 1


def test_a_write_up_lost_to_a_crash_is_caught_up_by_the_next_review(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _loosened_and_live(client)
    case_id = _decline_until_case(client)
    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyRepository, "_run_threshold_follow_ups", lambda *_: None)
        _mark_too_late(client, case_id)
    assert _write_ups(_state(client)) == []
    # Reading state writes nothing.
    assert _write_ups(_state(client)) == []
    _review(client, case_id, status="resolved", human_action="agree", override_reason=None)
    assert len(_write_ups(_state(client))) == 1


# ── Re-check fixes: frozen closes, tomorrow's stack, supersede ids, bounded triggers, retries ───


def test_a_closed_check_keeps_its_frozen_count_after_a_later_false_alarm(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    # Effective 9 days ago: the period is [D-9, D+5); a case opens inside it on D+4 and is only
    # reviewed after the close on D+5.
    _approve_directly(repository, (40, 4), days_ago=10)
    closes = date.fromisoformat(_state(client)["current_day"]) + timedelta(days=5)
    case_id = _decline_until_case(client)
    opened = date.fromisoformat(_state(client)["current_day"])
    assert opened < closes
    while date.fromisoformat(_state(client)["current_day"]) < closes:
        _advance(client, "activity_declines")
    state = _state(client)
    assert [item["kind"] for item in state["decisions"]].count("check_confirmed") == 1
    assert (state["check"]["status"], state["check"]["false_alarms_since"]) == ("confirmed", 0)
    _review(client, case_id, human_action="override", override_reason="not_a_concern")
    state = _state(client)
    assert (state["check"]["status"], state["check"]["false_alarms_since"]) == ("confirmed", 0)


def test_a_case_opened_on_the_close_day_is_outside_the_period(
    client: TestClient, repository: SqlAlchemyRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case opens on the close day and is reviewed as a false alarm before any close runs
    (the close is held back for those advances); the next advance closes over
    `[effective, checking_until)`, which does not include that day."""
    _approve_directly(repository, (40, 4), days_ago=11)
    closes = date.fromisoformat(_state(client)["current_day"]) + timedelta(days=4)
    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyRepository, "_close_checking_period", lambda *_: [])
        case_id = _decline_until_case(client)
        assert _state(client)["current_day"] == closes.isoformat()
        _review(client, case_id, human_action="override", override_reason="known_context")
        # Not closed yet: the card still counts only the period, not the close day.
        check = _state(client)["check"]
        assert (check["status"], check["false_alarms_since"]) == ("confirmed", 0)
    _advance(client, "recovery")
    state = _state(client)
    assert [item["kind"] for item in state["decisions"]].count("check_confirmed") == 1
    assert (state["check"]["status"], state["check"]["false_alarms_since"]) == ("confirmed", 0)


def test_a_known_context_override_in_the_period_counts_as_a_false_alarm(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    _approve_directly(repository, (40, 4), days_ago=5)
    closes = date.fromisoformat(_state(client)["current_day"]) + timedelta(days=10)
    _review(
        client,
        _decline_until_case(client),
        human_action="override",
        override_reason="known_context",
    )
    assert _state(client)["check"]["false_alarms_since"] == 1
    while date.fromisoformat(_state(client)["current_day"]) < closes:
        _advance(client, "recovery")
    check = _state(client)["check"]
    assert (check["status"], check["false_alarms_since"]) == ("unresolved", 1)


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
    reverts = _reverts(client)
    assert {item["ends_approval_id"] for item in reverts} == {"t_live", "t_pending"}
    assert {item["revert_trigger"] for item in reverts} == {"shadow_check"}
    monkeypatch.setattr(SqlAlchemyRepository, "_lock_active_run", original)
    _advance(client, "recovery")
    assert _state(client)["live"] == {"severity_pct": 40, "persistence_days": 3}
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
    assert {item["revert_trigger"] for item in _reverts(client)} == {"reached_too_late"}
    [skipped] = [e for e in _events(client) if e["event_type"] == "review_threshold_revert_skipped"]
    assert skipped["detail"]["reason"] == "nothing_to_clear"
    assert skipped["detail"]["revert_trigger"] == "shadow_check"
    assert skipped["detail"]["day"] == shadow_day["state"]["current_day"]


def test_proposals_superseded_by_a_late_mark_revert_carry_the_mark(
    client: TestClient, repository: SqlAlchemyRepository
) -> None:
    from tests.test_review_threshold_api import _insert_agent_proposal

    _loosened_and_live(client)
    proposal_id = _insert_agent_proposal(
        repository, previous=(40, 4), proposed=(40, 5), round_id="round-later"
    )
    case_id = _decline_until_case(client)
    review = _mark_too_late(client, case_id)
    [superseded] = [
        item for item in _state(client)["decisions"] if item["proposal_id"] == proposal_id
    ]
    assert superseded["rejection_reason"] == "superseded"
    assert superseded["trigger_case_id"] == case_id
    assert superseded["trigger_review_id"] == review["review_evidence_id"]


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
    check = _state(client)["check"]
    assert (check["status"], check["false_alarms_since"]) == ("confirmed", 0)


def test_a_failing_write_up_is_abandoned_after_three_attempts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("write-up exploded")

    monkeypatch.setattr(SqlAlchemyRepository, "_write_up_revert", broken)
    _loosened_and_live(client)
    _mark_too_late(client, _decline_until_case(client))
    for _ in range(4):
        _advance(client, "recovery")
    events = _events(client)
    discarded = [e for e in events if e["event_type"] == "review_threshold_write_up_discarded"]
    abandoned = [e for e in events if e["event_type"] == "review_threshold_write_up_abandoned"]
    assert len(discarded) == 3
    assert len(abandoned) == 1
    assert abandoned[0]["detail"]["attempts"] == 3
    assert "exploded" not in str(events)
    assert _write_ups(_state(client)) == []
