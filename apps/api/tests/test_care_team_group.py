"""Care Team workflow placement is decided on the server, with the follow-up window, never apart.

`triage.py` places every board row in one `CareTeamGroup` for one `CareTeamGroupReason`, from the
same facts that set the row's follow-up window. A client maps the enums to labels; it never joins
cases, outreach history and proposals to re-derive the placement. These tests pin each group and
reason, the one "due back" rule (including a case with no recorded review day), and the property
that a row's group never contradicts its window.
"""

from __future__ import annotations

import itertools
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from silverloop.models import (
    CareTeamGroup,
    CareTeamGroupReason,
    CaseStatus,
    Decision,
    FollowUpWindow,
    PersonState,
    PolicyGate,
    PriorityHold,
)
from silverloop.sql_repository import SqlAlchemyRepository
from silverloop.triage import CareContext, build_board, case_due_back
from tests.test_review_threshold_api import _proposal_after_two_false_alarms
from tests.test_triage import _only, _state

GROUP_OF_REASON: dict[CareTeamGroupReason, CareTeamGroup] = {
    CareTeamGroupReason.OPEN_CASE: CareTeamGroup.NEEDS_JUDGEMENT,
    CareTeamGroupReason.MONITORING_DUE_BACK: CareTeamGroup.NEEDS_JUDGEMENT,
    CareTeamGroupReason.MONITORING_UNTIL_REVIEW_DAY: CareTeamGroup.SILVERLOOP_HANDLING,
    CareTeamGroupReason.KEEP_AN_EYE_ON: CareTeamGroup.SILVERLOOP_HANDLING,
    CareTeamGroupReason.CHECK_IN_SUGGESTED: CareTeamGroup.NEEDS_JUDGEMENT,
    CareTeamGroupReason.AWAITING_REPLY: CareTeamGroup.WAITING_FOR_SENIOR,
    CareTeamGroupReason.CONSENT_WITHDRAWN: CareTeamGroup.NO_ATTENTION_NEEDED,
    CareTeamGroupReason.TRACKER_UNCLEAR: CareTeamGroup.NO_ATTENTION_NEEDED,
    CareTeamGroupReason.NOTHING_NEEDED: CareTeamGroup.NO_ATTENTION_NEEDED,
}
REVIEW = dict(decision=Decision.COORDINATOR_REVIEW, gate=PolicyGate.SEVERITY_PERSISTENCE)


@pytest.fixture(scope="module")
def base_state() -> PersonState:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    try:
        return repository.person_state()
    finally:
        repository.close()


def test_every_reason_belongs_to_exactly_one_group() -> None:
    assert set(GROUP_OF_REASON) == set(CareTeamGroupReason)
    assert set(GROUP_OF_REASON.values()) == set(CareTeamGroup)


# ── Each group and reason ─────────────────────────────────────────────────────────────────────


def test_an_open_case_needs_judgement(base_state: PersonState) -> None:
    today = base_state.current_day
    state = _state(base_state, delta=-45, sustained=3, **REVIEW)
    context = CareContext(
        open_case_id="case-1",
        open_case_status=CaseStatus.OPEN,
        review_by_day=today + timedelta(days=5),
        awaiting_reply_until=today + timedelta(days=1),
    )
    row = _only(state, context)
    assert (row.care_team_group, row.care_team_group_reason) == (
        CareTeamGroup.NEEDS_JUDGEMENT,
        CareTeamGroupReason.OPEN_CASE,
    )
    assert row.follow_up_window == FollowUpWindow.REACH_OUT_TODAY
    assert row.open_case_id == "case-1"
    assert row.review_back_on_day == today + timedelta(days=5)
    # The offer is still a fact on the row, but the case decides the group.
    assert row.awaiting_reply_until == today + timedelta(days=1)


def test_an_open_case_held_back_today_still_needs_judgement(base_state: PersonState) -> None:
    state = _state(base_state, gate=PolicyGate.RAIN_CONTEXT, delta=-45, sustained=3)
    row = _only(state, CareContext(open_case_id="case-1", open_case_status=CaseStatus.OPEN))
    assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert row.care_team_group == CareTeamGroup.NEEDS_JUDGEMENT
    assert row.care_team_group_reason == CareTeamGroupReason.OPEN_CASE


def test_an_acknowledged_case_not_yet_due_is_silverloop_monitoring(
    base_state: PersonState,
) -> None:
    """The board used to say "reach out today" here while the web said Care+ was handling it.
    A coordinator chose to keep monitoring; until the case is due back nobody is asked again."""
    back_on = base_state.current_day + timedelta(days=3)
    state = _state(base_state, delta=-45, sustained=4, **REVIEW)
    board = build_board(
        [
            (
                state,
                CareContext(
                    open_case_id="case-1",
                    open_case_status=CaseStatus.ACKNOWLEDGED,
                    review_by_day=back_on,
                    recent_no_reply=2,
                ),
            )
        ]
    )
    row = board.people[0]
    assert (row.care_team_group, row.care_team_group_reason) == (
        CareTeamGroup.SILVERLOOP_HANDLING,
        CareTeamGroupReason.MONITORING_UNTIL_REVIEW_DAY,
    )
    assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert board.follow_up_first == []
    assert row.review_back_on_day == back_on
    assert row.open_case_id == "case-1"
    assert "monitoring" in row.headline
    assert "come back to the queue" not in " ".join(note.text for note in row.take_note)


@pytest.mark.parametrize("days_past", [0, 2])
def test_an_acknowledged_case_due_back_needs_judgement_again(
    base_state: PersonState, days_past: int
) -> None:
    due = base_state.current_day - timedelta(days=days_past)
    state = _state(base_state, delta=-45, sustained=4, **REVIEW)
    board = build_board(
        [
            (
                state,
                CareContext(
                    open_case_id="case-1",
                    open_case_status=CaseStatus.ACKNOWLEDGED,
                    review_by_day=due,
                ),
            )
        ]
    )
    row = board.people[0]
    assert (row.care_team_group, row.care_team_group_reason) == (
        CareTeamGroup.NEEDS_JUDGEMENT,
        CareTeamGroupReason.MONITORING_DUE_BACK,
    )
    assert row.follow_up_window == FollowUpWindow.REACH_OUT_TODAY
    assert board.follow_up_first == [row]
    assert row.review_back_on_day == due
    assert "come back to the queue" in row.headline


def test_an_acknowledged_case_due_back_but_held_today_needs_judgement_without_contact(
    base_state: PersonState,
) -> None:
    state = _state(base_state, gate=PolicyGate.CONTACT_CAP, decision=Decision.SUPPRESS, delta=-45)
    context = CareContext(
        open_case_id="case-1",
        open_case_status=CaseStatus.ACKNOWLEDGED,
        review_by_day=base_state.current_day,
    )
    row = _only(state, context)
    assert row.care_team_group_reason == CareTeamGroupReason.MONITORING_DUE_BACK
    assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON


def test_a_case_with_no_recorded_review_day_is_never_due_back(base_state: PersonState) -> None:
    """The one rule for a case that predates the case clock: no recorded day is not a day passed.
    An open one still needs judgement; an acknowledged one stays monitored, with no invented day,
    and the board's headline, notes and order all agree with that."""
    assert case_due_back(None, base_state.current_day) is False
    assert case_due_back(base_state.current_day, base_state.current_day) is True
    assert case_due_back(base_state.current_day + timedelta(days=1), base_state.current_day) is (
        False
    )

    state = _state(base_state, delta=-45, sustained=3, **REVIEW)
    acknowledged = _only(
        state, CareContext(open_case_id="case-1", open_case_status=CaseStatus.ACKNOWLEDGED)
    )
    assert (acknowledged.care_team_group, acknowledged.care_team_group_reason) == (
        CareTeamGroup.SILVERLOOP_HANDLING,
        CareTeamGroupReason.MONITORING_UNTIL_REVIEW_DAY,
    )
    assert acknowledged.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert acknowledged.review_back_on_day is None
    assert "until it is resolved" in acknowledged.headline

    opened = _only(state, CareContext(open_case_id="case-2", open_case_status=CaseStatus.OPEN))
    assert opened.care_team_group_reason == CareTeamGroupReason.OPEN_CASE
    assert opened.follow_up_window == FollowUpWindow.REACH_OUT_TODAY
    assert opened.review_back_on_day is None
    assert "come back to the queue" not in opened.headline
    assert all("come back to the queue" not in note.text for note in opened.take_note)


def test_an_offer_waiting_for_a_reply_is_waiting_for_the_senior(base_state: PersonState) -> None:
    until = base_state.current_day + timedelta(days=2)
    state = _state(base_state, decision=Decision.GENTLE_NUDGE, gate=PolicyGate.SEVERITY_PERSISTENCE)
    row = _only(state, CareContext(awaiting_reply_until=until))
    assert (row.care_team_group, row.care_team_group_reason) == (
        CareTeamGroup.WAITING_FOR_SENIOR,
        CareTeamGroupReason.AWAITING_REPLY,
    )
    assert row.awaiting_reply_until == until
    assert row.review_back_on_day is None
    assert any("waiting for their reply" in note.text for note in row.take_note)


def test_an_acknowledged_case_outranks_an_offer_waiting_for_a_reply(
    base_state: PersonState,
) -> None:
    today = base_state.current_day
    state = _state(base_state, delta=-45, sustained=3, **REVIEW)
    row = _only(
        state,
        CareContext(
            open_case_id="case-1",
            open_case_status=CaseStatus.ACKNOWLEDGED,
            review_by_day=today + timedelta(days=4),
            awaiting_reply_until=today + timedelta(days=1),
        ),
    )
    assert row.care_team_group_reason == CareTeamGroupReason.MONITORING_UNTIL_REVIEW_DAY
    assert row.awaiting_reply_until == today + timedelta(days=1)


def test_watching_is_silverloop_handling_and_a_suggested_check_in_needs_judgement(
    base_state: PersonState,
) -> None:
    """A suggested check-in asks a person to contact the senior within two days, which Care+
    cannot do for them, so it needs a person's judgement even with no case open."""
    watching = _only(_state(base_state, delta=-12, baseline_steps=8_000))
    assert watching.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert (watching.care_team_group, watching.care_team_group_reason) == (
        CareTeamGroup.SILVERLOOP_HANDLING,
        CareTeamGroupReason.KEEP_AN_EYE_ON,
    )

    suggestion = _state(
        base_state,
        decision=Decision.PROGRAMME_SUGGESTION,
        gate=PolicyGate.SEVERITY_PERSISTENCE,
        delta=-30,
        sustained=2,
    )
    check_in = _only(suggestion)
    assert check_in.follow_up_window == FollowUpWindow.CHECK_IN_WITHIN_48H
    assert (check_in.care_team_group, check_in.care_team_group_reason) == (
        CareTeamGroup.NEEDS_JUDGEMENT,
        CareTeamGroupReason.CHECK_IN_SUGGESTED,
    )
    assert check_in.open_case_id is None


def test_within_range_needs_no_attention(base_state: PersonState) -> None:
    row = _only(_state(base_state))
    assert row.follow_up_window == FollowUpWindow.NO_ACTION_NEEDED
    assert (row.care_team_group, row.care_team_group_reason) == (
        CareTeamGroup.NO_ATTENTION_NEEDED,
        CareTeamGroupReason.NOTHING_NEEDED,
    )
    assert row.review_timing_proposal_waiting is False
    assert row.awaiting_reply_until is None
    assert row.review_back_on_day is None


def test_withdrawn_consent_needs_no_attention_and_carries_no_workflow_items(
    base_state: PersonState,
) -> None:
    today = base_state.current_day
    state = _state(
        base_state, consent=False, gate=PolicyGate.CONSENT, decision=Decision.SUPPRESS, delta=-50
    )
    row = _only(
        state,
        CareContext(
            open_case_id="case-1",
            open_case_status=CaseStatus.ACKNOWLEDGED,
            review_by_day=today,
            awaiting_reply_until=today + timedelta(days=1),
            review_timing_proposal_waiting=True,
        ),
    )
    assert (row.care_team_group, row.care_team_group_reason) == (
        CareTeamGroup.NO_ATTENTION_NEEDED,
        CareTeamGroupReason.CONSENT_WITHDRAWN,
    )
    assert row.open_case_id is None
    assert row.review_back_on_day is None
    assert row.awaiting_reply_until is None
    assert row.review_timing_proposal_waiting is False


def test_an_unreadable_tracker_without_a_case_needs_no_attention(base_state: PersonState) -> None:
    state = _state(base_state, gate=PolicyGate.DATA_QUALITY, safe=False, delta=-60)
    row = _only(state, CareContext(awaiting_reply_until=base_state.current_day))
    assert row.hold == PriorityHold.DATA_NOT_READABLE
    assert (row.care_team_group, row.care_team_group_reason) == (
        CareTeamGroup.NO_ATTENTION_NEEDED,
        CareTeamGroupReason.TRACKER_UNCLEAR,
    )


def test_a_waiting_review_timing_proposal_is_reported_without_moving_the_group(
    base_state: PersonState,
) -> None:
    row = _only(_state(base_state), CareContext(review_timing_proposal_waiting=True))
    assert row.review_timing_proposal_waiting is True
    assert row.care_team_group_reason == CareTeamGroupReason.NOTHING_NEEDED


# ── The group never contradicts the window ────────────────────────────────────────────────────


def test_group_and_follow_up_window_agree_across_every_case_and_gate(
    base_state: PersonState,
) -> None:
    today = base_state.current_day
    gates = [
        (PolicyGate.CONSENT, Decision.SUPPRESS),
        (PolicyGate.DATA_QUALITY, Decision.NO_ACTION),
        (PolicyGate.STATED_EXPLANATION, Decision.NO_ACTION),
        (PolicyGate.RAIN_CONTEXT, Decision.NO_ACTION),
        (PolicyGate.CONTACT_CAP, Decision.SUPPRESS),
        (PolicyGate.ACCEPTED_COOLDOWN, Decision.SUPPRESS),
        (PolicyGate.WITHIN_RANGE, Decision.NO_ACTION),
        (PolicyGate.SEVERITY_PERSISTENCE, Decision.GENTLE_NUDGE),
        (PolicyGate.SEVERITY_PERSISTENCE, Decision.PROGRAMME_SUGGESTION),
        (PolicyGate.SEVERITY_PERSISTENCE, Decision.COORDINATOR_REVIEW),
    ]
    grid = itertools.product(
        gates,
        (None, CaseStatus.OPEN, CaseStatus.ACKNOWLEDGED),
        (None, today - timedelta(days=1), today, today + timedelta(days=3)),  # review_by_day
        (None, today + timedelta(days=1)),  # awaiting_reply_until
        (0, 2),  # recent no reply
        (-12.0, -45.0),  # delta
    )
    checked = 0
    reasons_seen: set[CareTeamGroupReason] = set()
    for (gate, decision), status, review_by, awaiting, no_reply, delta in grid:
        state = _state(
            base_state,
            gate=gate,
            decision=decision,
            consent=gate != PolicyGate.CONSENT,
            safe=gate != PolicyGate.DATA_QUALITY,
            delta=delta,
            sustained=3,
            baseline_steps=8_000,
        )
        context = CareContext(
            open_case_id="case-1" if status else None,
            open_case_status=status,
            review_by_day=review_by if status else None,
            awaiting_reply_until=awaiting,
            recent_no_reply=no_reply,
        )
        row = _only(state, context)
        facts = (gate, decision, status, review_by, awaiting, no_reply, delta, row)
        group, reason, window = (
            row.care_team_group,
            row.care_team_group_reason,
            row.follow_up_window,
        )

        assert GROUP_OF_REASON[reason] == group, facts
        reasons_seen.add(reason)
        # "Reach out today" belongs only to a case that needs judgement.
        if window == FollowUpWindow.REACH_OUT_TODAY:
            assert group == CareTeamGroup.NEEDS_JUDGEMENT, facts
        # Monitoring and waiting never sit beside a same-day contact window.
        if group in {CareTeamGroup.SILVERLOOP_HANDLING, CareTeamGroup.WAITING_FOR_SENIOR}:
            assert window != FollowUpWindow.REACH_OUT_TODAY, facts
        # Care+ never claims to be handling a row that asks a person to make contact.
        if group == CareTeamGroup.SILVERLOOP_HANDLING:
            assert window not in {
                FollowUpWindow.REACH_OUT_TODAY,
                FollowUpWindow.CHECK_IN_WITHIN_48H,
            }, facts
        # A suggested check-in with no unresolved case and no reply awaited needs judgement.
        if (
            window == FollowUpWindow.CHECK_IN_WITHIN_48H
            and row.open_case_id is None
            and row.awaiting_reply_until is None
            and row.hold is None
        ):
            assert reason == CareTeamGroupReason.CHECK_IN_SUGGESTED, facts
        if reason == CareTeamGroupReason.MONITORING_UNTIL_REVIEW_DAY:
            assert window == FollowUpWindow.KEEP_AN_EYE_ON, facts
            assert not case_due_back(row.review_back_on_day, today), facts
        if group == CareTeamGroup.NO_ATTENTION_NEEDED:
            assert window == FollowUpWindow.NO_ACTION_NEEDED, facts
        # Judgement is about the unresolved case, except a suggested check-in, which has none.
        if group == CareTeamGroup.NEEDS_JUDGEMENT:
            if reason == CareTeamGroupReason.CHECK_IN_SUGGESTED:
                assert row.open_case_id is None, facts
                assert window == FollowUpWindow.CHECK_IN_WITHIN_48H, facts
            else:
                assert row.open_case_id == "case-1", facts
        if row.hold is not None:
            assert group == CareTeamGroup.NO_ATTENTION_NEEDED, facts
        # The group reads only facts on the row: a client never has to join anything else.
        if row.open_case_id is not None:
            assert row.review_back_on_day == review_by, facts
        checked += 1
    assert checked == 10 * 3 * 4 * 2 * 2 * 2
    assert CareTeamGroupReason.CHECK_IN_SUGGESTED in reasons_seen


# ── Through the repository and the API ────────────────────────────────────────────────────────


def test_a_decline_moves_through_the_groups_as_it_is_reviewed(
    repository: SqlAlchemyRepository,
) -> None:
    """Waiting for the senior while a nudge is open, judgement once a case opens, monitoring once a
    coordinator acknowledges it, and judgement again on the day the case comes back."""
    seen = []
    for index in range(3):
        repository.advance("activity_declines", event_id=f"group-decline-{index}")
        row = repository.care_priorities().people[0]
        seen.append((row.care_team_group_reason, row.awaiting_reply_until))
        # The board and the person's own outreach history agree on when waiting ends.
        waiting = [
            summary.awaiting_reply_until
            for summary in repository.list_outreach_summaries()
            if summary.awaiting_reply_until is not None
        ]
        assert waiting, "each declining day leaves an offer open"
        assert row.awaiting_reply_until == max(waiting)
    assert [reason for reason, _ in seen] == [
        CareTeamGroupReason.AWAITING_REPLY,
        CareTeamGroupReason.AWAITING_REPLY,
        CareTeamGroupReason.OPEN_CASE,
    ]

    case = repository.list_cases()[0]
    assert case.review_by_day is not None
    repository.review_case(case.case_id, CaseStatus.ACKNOWLEDGED, "Keep monitoring for now.")
    row = repository.care_priorities().people[0]
    assert row.care_team_group_reason == CareTeamGroupReason.MONITORING_UNTIL_REVIEW_DAY
    assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert row.open_case_id == case.case_id
    assert row.review_back_on_day == case.review_by_day

    index = 0
    while row.as_of_day < case.review_by_day:
        repository.advance("activity_declines", event_id=f"group-monitor-{index}")
        row = repository.care_priorities().people[0]
        if row.as_of_day < case.review_by_day:
            assert row.care_team_group_reason == CareTeamGroupReason.MONITORING_UNTIL_REVIEW_DAY
        index += 1
        assert index < 15, "the case never came back to the queue"
    assert row.care_team_group_reason == CareTeamGroupReason.MONITORING_DUE_BACK
    assert row.follow_up_window == FollowUpWindow.REACH_OUT_TODAY


def test_a_waiting_review_timing_proposal_reaches_the_board(client: TestClient) -> None:
    _proposal_after_two_false_alarms(client)
    [row] = client.get("/v1/coordinator/priorities").json()["people"]
    assert row["review_timing_proposal_waiting"] is True


def test_the_route_serialises_the_group_fields(client: TestClient) -> None:
    client.post("/v1/demo/reset")
    [row] = client.get("/v1/coordinator/priorities").json()["people"]
    assert row["care_team_group"] == "no_attention_needed"
    assert row["care_team_group_reason"] == "nothing_needed"
    assert row["review_back_on_day"] is None
    assert row["awaiting_reply_until"] is None
    assert row["review_timing_proposal_waiting"] is False
