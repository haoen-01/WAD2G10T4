"""The care-priority board orders people for a caregiver without ever outranking the policy.

The load-bearing property is the ceiling in `triage.py`: a follow-up window that suggests a person
contact a senior is reachable only from a decision `policy.decide` already returned. The first
group of tests checks that against the real ladder across a grid of signals, so a future change to
either module that lets the board suggest contact past a gate fails here, not in a demo.
"""

from __future__ import annotations

import itertools
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from silverloop.context_explanation import StatedExplanation
from silverloop.models import (
    CaseStatus,
    ContextSignal,
    Decision,
    FollowUpWindow,
    PersonState,
    PolicyGate,
    PriorityHold,
    StatedContextExplanation,
)
from silverloop.policy import decide
from silverloop.review_threshold import ALLOWED_THRESHOLDS
from silverloop.sql_repository import SqlAlchemyRepository
from silverloop.triage import MAX_TOP_K, THRESHOLD_REFERENCES, CareContext, build_board

CONTACT_WINDOWS = {FollowUpWindow.REACH_OUT_TODAY, FollowUpWindow.CHECK_IN_WITHIN_48H}
OUTREACH_DECISIONS = {
    Decision.COORDINATOR_REVIEW,
    Decision.PROGRAMME_SUGGESTION,
    Decision.GENTLE_NUDGE,
}
# The most pressure the repository can put on a person without a case: every recent message
# ignored or declined. None of it may lift a window past the gate.
PRESSURED = CareContext(recent_no_reply=2, recent_declined=2, tracker_not_synced_days=2)


@pytest.fixture(scope="module")
def base_state() -> PersonState:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    try:
        return repository.person_state()
    finally:
        repository.close()


def _state(
    base: PersonState,
    *,
    person_id: str = "p-1",
    name: str = "Person One",
    decision: Decision = Decision.NO_ACTION,
    gate: PolicyGate = PolicyGate.WITHIN_RANGE,
    consent: bool = True,
    delta: float = 0.0,
    reference_delta: float | None = None,
    sustained: int = 0,
    baseline_steps: float = 6_000,
    current_steps: int | None = None,
    safe: bool = True,
    confidence: float = 0.9,
    rainy: bool = False,
    conflict: bool = False,
) -> PersonState:
    current = (
        current_steps if current_steps is not None else int(baseline_steps * (1 + delta / 100))
    )
    quality = base.signal.quality.model_copy(
        update={"safe_to_interpret": safe, "self_reported_conflict": conflict}
    )
    signal = base.signal.model_copy(
        update={
            "current_steps": current,
            "delta_percent": delta,
            "reference_delta_percent": delta if reference_delta is None else reference_delta,
            "baseline_median_steps": baseline_steps,
            "sustained_low_days": sustained,
            "confidence": confidence,
            "context": ContextSignal(rainy=rainy),
            "quality": quality,
        }
    )
    baseline = base.baseline.model_copy(
        update={"median_steps": baseline_steps, "reference_steps": baseline_steps}
    )
    return base.model_copy(
        update={
            "person_id": person_id,
            "display_name": name,
            "consent_active": consent,
            "signal": signal,
            "baseline": baseline,
            "last_decision": decision,
            "decided_by_gate": gate,
        }
    )


def _only(state: PersonState, context: CareContext | None = None):  # type: ignore[no-untyped-def]
    return build_board([(state, context or CareContext())]).people[0]


# ── The ceiling, against the real policy ladder ───────────────────────────────────────────────


def test_no_contact_window_is_ever_reached_without_the_policy_permitting_outreach(
    base_state: PersonState,
) -> None:
    """Every combination of gate inputs, fed through `decide`, then through the board with maximum
    outreach pressure. A contact window may only follow a decision that is itself outreach."""
    explanation = StatedExplanation(
        value="away",
        rationale="They said they were away.",
        stated_on=date(2026, 8, 1),
        explains_through=date(2026, 8, 10),
    )
    grid = itertools.product(
        (True, False),  # consent
        (True, False),  # safe to interpret
        (0.3, 0.9),  # confidence
        (None, explanation),  # stated explanation
        (True, False),  # rainy
        (300.0, 6_000.0),  # baseline steps
        (0.0, -12.0, -22.0, -30.0, -45.0),  # delta
        (0, 1, 2, 3, 4),  # sustained low days
        (0, 2),  # interventions in the last 7 days
        (None, 1),  # days since last accepted
    )
    checked = 0
    for (
        consent,
        safe,
        confidence,
        stated,
        rainy,
        baseline,
        delta,
        sustained,
        weekly,
        accepted,
    ) in grid:
        state = _state(
            base_state,
            consent=consent,
            safe=safe,
            confidence=confidence,
            rainy=rainy,
            baseline_steps=baseline,
            delta=delta,
            sustained=sustained,
        )
        result = decide(
            state.signal,
            consent_active=consent,
            interventions_last_7_days=weekly,
            days_since_last_accepted=accepted,
            stated_explanation=stated,
        )
        assert result.decided_by is not None
        state = state.model_copy(
            update={"last_decision": result.decision, "decided_by_gate": result.decided_by}
        )
        row = _only(state, PRESSURED)
        if row.follow_up_window in CONTACT_WINDOWS:
            assert result.decision in OUTREACH_DECISIONS, (result, row)
        if row.follow_up_window == FollowUpWindow.REACH_OUT_TODAY:
            assert result.decision == Decision.COORDINATOR_REVIEW, (result, row)
        checked += 1
    assert checked > 1_000


def test_personal_review_setting_never_lifts_the_board_past_the_ladder(
    base_state: PersonState,
) -> None:
    """The review-threshold calibrator (ADR 0008) reaches the board only through the decision the
    ladder recorded. Across every allowed review setting, with and without a shadow-check date, the
    board keeps the same ceiling as the grid above: a contact window follows only an outreach
    decision, and "Reach out today" only a coordinator review -- or a case one already opened."""
    open_case = CareContext(
        open_case_id="case-1",
        open_case_status=CaseStatus.OPEN,
        recent_no_reply=2,
        recent_declined=2,
        tracker_not_synced_days=2,
    )
    grid = itertools.product(
        ALLOWED_THRESHOLDS,
        (None, base_state.current_day),  # shadow check asked since
        (-35.0, -45.0, -62.0),  # delta
        (2, 3, 4, 5),  # sustained low days
        (True, False),  # consent
        (False, True),  # open case
    )
    checked = 0
    gates_seen: set[PolicyGate] = set()
    for threshold, shadow_since, delta, sustained, consent, has_case in grid:
        state = _state(base_state, consent=consent, delta=delta, sustained=sustained)
        result = decide(
            state.signal,
            consent_active=consent,
            interventions_last_7_days=0,
            review_threshold=threshold,
            shadow_review_since=shadow_since,
        )
        assert result.decided_by is not None
        gates_seen.add(result.decided_by)
        state = state.model_copy(
            update={"last_decision": result.decision, "decided_by_gate": result.decided_by}
        )
        row = _only(state, open_case if has_case else PRESSURED)
        context = (threshold, shadow_since, delta, sustained, consent, has_case, result, row)
        if not consent:
            assert row.follow_up_window == FollowUpWindow.NO_ACTION_NEEDED, context
            assert row.hold == PriorityHold.CONSENT_WITHDRAWN, context
        elif has_case:
            # A waiting case keeps its place whatever today's rung, as it does without a setting.
            assert row.follow_up_window == FollowUpWindow.REACH_OUT_TODAY, context
            if result.decision == Decision.COORDINATOR_REVIEW:
                # Plain language for a caregiver: what happened, not which rule routed it.
                assert row.headline == (
                    "Activity has stayed well below their usual for several days."
                ), context
        else:
            if row.follow_up_window in CONTACT_WINDOWS:
                assert result.decision in OUTREACH_DECISIONS, context
            if row.follow_up_window == FollowUpWindow.REACH_OUT_TODAY:
                assert result.decision == Decision.COORDINATOR_REVIEW, context
            if result.decision == Decision.COORDINATOR_REVIEW:
                assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON, context
        checked += 1
    assert checked == 14 * 2 * 3 * 4 * 2 * 2
    # Every review rung was reached, so the ceiling was checked against each of them.
    assert {
        PolicyGate.SEVERITY_PERSISTENCE,
        PolicyGate.REVIEW_FLOOR,
        PolicyGate.SHADOW_CHECK,
    } <= gates_seen


@pytest.mark.parametrize(
    "gate",
    [PolicyGate.SEVERITY_PERSISTENCE, PolicyGate.REVIEW_FLOOR, PolicyGate.SHADOW_CHECK],
)
@pytest.mark.parametrize("has_case", [True, False])
def test_every_review_rung_reads_the_same_on_the_board(
    base_state: PersonState, gate: PolicyGate, has_case: bool
) -> None:
    """The floor and the shadow check are review rungs like the personal one: with a waiting case
    the board says reach out today; without one a person has already answered it."""
    state = _state(
        base_state, decision=Decision.COORDINATOR_REVIEW, gate=gate, delta=-62, sustained=3
    )
    context = CareContext(open_case_id="case-1", open_case_status=CaseStatus.OPEN)
    row = _only(state, context if has_case else PRESSURED)
    expected = FollowUpWindow.REACH_OUT_TODAY if has_case else FollowUpWindow.KEEP_AN_EYE_ON
    assert row.follow_up_window == expected


def test_the_reach_out_reference_names_the_review_setting() -> None:
    assert THRESHOLD_REFERENCES[0].rule == (
        "Only while a review case is waiting. Care+'s policy opens one when activity has "
        "stayed below their own usual past their review setting: more than 40% for at least three "
        "valid-wear days, unless a coordinator has approved a change for that person within fixed "
        "bounds, and always at 60% or more for three days."
    )


@pytest.mark.parametrize(
    ("gate", "decision"),
    [
        (PolicyGate.CONSENT, Decision.SUPPRESS),
        (PolicyGate.DATA_QUALITY, Decision.NO_ACTION),
        (PolicyGate.CONFIDENCE, Decision.NO_ACTION),
        (PolicyGate.STATED_EXPLANATION, Decision.NO_ACTION),
        (PolicyGate.RAIN_CONTEXT, Decision.NO_ACTION),
        (PolicyGate.SMALL_BASELINE, Decision.NO_ACTION),
        (PolicyGate.CONTACT_CAP, Decision.SUPPRESS),
        (PolicyGate.ACCEPTED_COOLDOWN, Decision.SUPPRESS),
        (PolicyGate.WITHIN_RANGE, Decision.NO_ACTION),
    ],
)
def test_every_gate_short_of_outreach_keeps_the_board_short_of_contact(
    base_state: PersonState, gate: PolicyGate, decision: Decision
) -> None:
    state = _state(
        base_state,
        gate=gate,
        decision=decision,
        consent=gate != PolicyGate.CONSENT,
        delta=-45,
        sustained=2,
    )
    row = _only(state, PRESSURED)
    assert row.follow_up_window not in CONTACT_WINDOWS


def test_withdrawn_consent_outranks_an_open_case(base_state: PersonState) -> None:
    state = _state(
        base_state,
        consent=False,
        gate=PolicyGate.CONSENT,
        decision=Decision.SUPPRESS,
        delta=-50,
        sustained=4,
    )
    board = build_board(
        [(state, CareContext(open_case_id="case-1", open_case_status=CaseStatus.OPEN))]
    )
    row = board.people[0]
    assert row.hold == PriorityHold.CONSENT_WITHDRAWN
    assert row.follow_up_window == FollowUpWindow.NO_ACTION_NEEDED
    assert row.open_case_id is None
    assert row.take_note == []
    assert board.follow_up_first == []


# ── Windows ───────────────────────────────────────────────────────────────────────────────────


def test_a_review_a_person_already_answered_is_not_asked_again(base_state: PersonState) -> None:
    state = _state(
        base_state,
        decision=Decision.COORDINATOR_REVIEW,
        gate=PolicyGate.SEVERITY_PERSISTENCE,
        delta=-45,
        sustained=3,
    )
    row = _only(state, PRESSURED)
    assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert any(note.kind.value == "case" for note in row.take_note)


@pytest.mark.parametrize(
    ("gate", "decision"),
    [
        (PolicyGate.STATED_EXPLANATION, Decision.NO_ACTION),
        (PolicyGate.RAIN_CONTEXT, Decision.NO_ACTION),
        (PolicyGate.SMALL_BASELINE, Decision.NO_ACTION),
        (PolicyGate.CONTACT_CAP, Decision.SUPPRESS),
        (PolicyGate.ACCEPTED_COOLDOWN, Decision.SUPPRESS),
    ],
)
def test_an_open_case_does_not_override_a_gate_that_holds_contact_back(
    base_state: PersonState, gate: PolicyGate, decision: Decision
) -> None:
    state = _state(base_state, gate=gate, decision=decision, delta=-45, sustained=2)
    row = _only(state, CareContext(open_case_id="case-1", open_case_status=CaseStatus.OPEN))
    assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert row.open_case_id == "case-1"
    assert any(note.kind.value == "case" for note in row.take_note)


def test_nothing_the_senior_told_silverloop_reaches_the_board(base_state: PersonState) -> None:
    """A stated explanation and a disputed day stay on the senior's own surface: not their content,
    and not the fact that the person said anything at all."""
    told = _state(
        base_state,
        gate=PolicyGate.STATED_EXPLANATION,
        delta=-15,
        baseline_steps=8_000,
        conflict=True,
    ).model_copy(
        update={
            "stated_explanation": StatedContextExplanation(
                value="away",
                label="Away",
                rationale="They said they were away.",
                stated_on=base_state.current_day,
                explains_through=base_state.current_day,
            )
        }
    )
    for context in (CareContext(), CareContext(open_case_id="c", open_case_status=CaseStatus.OPEN)):
        row = _only(told, context)
        text = " ".join([row.headline, row.suggested_approach, *(n.text for n in row.take_note)])
        for leak in ("told", "explain", "away", "said"):
            assert leak not in text.lower(), (leak, text)
        assert "decided_by_gate" not in row.model_dump()


def test_an_open_case_stays_at_the_top_on_a_day_that_cannot_be_read(
    base_state: PersonState,
) -> None:
    state = _state(base_state, gate=PolicyGate.DATA_QUALITY, safe=False, delta=-60, sustained=0)
    row = _only(state, CareContext(open_case_id="case-1", open_case_status=CaseStatus.OPEN))
    assert row.follow_up_window == FollowUpWindow.REACH_OUT_TODAY
    # Nothing about the unreadable day is described as a change.
    assert all(note.kind.value not in {"change", "activity_level"} for note in row.take_note)


def test_an_unreadable_day_without_a_case_is_set_aside_not_ranked(
    base_state: PersonState,
) -> None:
    state = _state(base_state, gate=PolicyGate.DATA_QUALITY, safe=False, delta=-60)
    row = _only(state, CareContext(tracker_not_synced_days=3))
    assert row.hold == PriorityHold.DATA_NOT_READABLE
    assert any(note.kind.value == "tracker" for note in row.take_note)


def test_a_programme_suggestion_is_a_check_in_within_two_days(base_state: PersonState) -> None:
    state = _state(
        base_state,
        decision=Decision.PROGRAMME_SUGGESTION,
        gate=PolicyGate.SEVERITY_PERSISTENCE,
        delta=-30,
        sustained=2,
    )
    assert _only(state).follow_up_window == FollowUpWindow.CHECK_IN_WITHIN_48H


def test_a_nudge_is_left_to_silverloop_until_its_messages_stop_landing(
    base_state: PersonState,
) -> None:
    state = _state(
        base_state, decision=Decision.GENTLE_NUDGE, gate=PolicyGate.SEVERITY_PERSISTENCE, delta=-21
    )
    assert _only(state).follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    landed_nowhere = _only(state, CareContext(recent_no_reply=1))
    assert landed_nowhere.follow_up_window == FollowUpWindow.CHECK_IN_WITHIN_48H
    assert any(note.kind.value == "outreach_history" for note in landed_nowhere.take_note)


def test_the_sensitive_thresholds_need_a_meaningful_step_change(base_state: PersonState) -> None:
    meaningful = _state(base_state, delta=-12, baseline_steps=7_000)  # 840 steps lower
    assert _only(meaningful).follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    too_small = _state(base_state, delta=-12, baseline_steps=3_000)  # 360 steps lower
    assert _only(too_small).follow_up_window == FollowUpWindow.NO_ACTION_NEEDED


def test_a_drift_from_the_anchored_reference_is_watched(base_state: PersonState) -> None:
    state = _state(base_state, delta=-5, reference_delta=-25, baseline_steps=6_000)
    state = state.model_copy(
        update={"baseline": state.baseline.model_copy(update={"reference_steps": 8_000})}
    )
    row = _only(state)
    assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert "first learned their routine" in row.headline


def test_a_disputed_day_is_watched_without_being_called_within_range(
    base_state: PersonState,
) -> None:
    state = _state(base_state, delta=-15, baseline_steps=7_000, conflict=True)
    row = _only(state)
    assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert "usual range" not in row.headline


# ── Order and top-k ───────────────────────────────────────────────────────────────────────────


def test_reading_order_follows_named_facts(base_state: PersonState) -> None:
    today = base_state.current_day
    review = dict(decision=Decision.COORDINATOR_REVIEW, gate=PolicyGate.SEVERITY_PERSISTENCE)
    overdue = _state(base_state, person_id="a", name="Zed", delta=-45, sustained=3, **review)
    longer = _state(base_state, person_id="b", name="Yan", delta=-45, sustained=5, **review)
    lower = _state(
        base_state, person_id="c", name="Xu", delta=-45, sustained=3, current_steps=2_000, **review
    )
    # 5,500 steps today: above both activity-level lines, so only the name is left to separate it.
    plain = _state(
        base_state,
        person_id="d",
        name="Wu",
        delta=-45,
        sustained=3,
        baseline_steps=10_000,
        **review,
    )
    watch = _state(base_state, person_id="e", name="Abe", delta=-12, baseline_steps=8_000)
    open_case = CareContext(open_case_id="c", open_case_status=CaseStatus.OPEN)

    board = build_board(
        [
            (watch, CareContext()),
            (plain, open_case),
            (lower, open_case),
            (longer, open_case),
            (
                overdue,
                CareContext(
                    open_case_id="c",
                    open_case_status=CaseStatus.OPEN,
                    review_by_day=today - timedelta(days=1),
                ),
            ),
        ],
        top_k=3,
    )

    assert [row.person_id for row in board.people] == ["a", "b", "c", "d", "e"]
    assert [row.position for row in board.people] == [1, 2, 3, 4, 5]
    assert [row.person_id for row in board.follow_up_first] == ["a", "b", "c"]


def test_top_k_never_pads_with_people_who_are_only_being_watched(base_state: PersonState) -> None:
    watch = _state(base_state, delta=-12, baseline_steps=8_000)
    board = build_board([(watch, CareContext())], top_k=5)
    assert board.follow_up_first == []
    assert build_board([], top_k=99).top_k == MAX_TOP_K


# ── What the board may say about a person ─────────────────────────────────────────────────────


def test_no_step_count_or_percentage_about_the_person_appears(base_state: PersonState) -> None:
    state = _state(
        base_state,
        decision=Decision.COORDINATOR_REVIEW,
        gate=PolicyGate.SEVERITY_PERSISTENCE,
        delta=-47.3,
        sustained=3,
        baseline_steps=6_234,
        current_steps=3_287,
    )
    row = _only(state, CareContext(open_case_id="c", open_case_status=CaseStatus.OPEN))
    text = " ".join([row.headline, row.suggested_approach, *(n.text for n in row.take_note)])
    for figure in ("3287", "3,287", "6234", "6,234", "47", "2947", "2,947"):
        assert figure not in text
    assert set(row.model_dump()) == {
        "position",
        "person_id",
        "display_name",
        "follow_up_window",
        "hold",
        "headline",
        "suggested_approach",
        "take_note",
        "open_case_id",
        "as_of_day",
        "evidence_ids",
        "care_team_group",
        "care_team_group_reason",
        "review_back_on_day",
        "awaiting_reply_until",
        "review_timing_proposal_waiting",
    }


def test_every_board_carries_the_boundary_note(base_state: PersonState) -> None:
    board = build_board([(_state(base_state), CareContext())])
    assert "Not an emergency or medical service" in board.boundary_note
    assert "995" in board.boundary_note
    assert board.thresholds


# ── Through the repository and the API ────────────────────────────────────────────────────────


def test_a_sustained_decline_reaches_the_top_with_its_case(
    repository: SqlAlchemyRepository,
) -> None:
    for index in range(3):
        repository.advance("activity_declines", event_id=f"triage-decline-{index}")
    case_id = repository.list_cases()[0].case_id

    board = repository.care_priorities()

    row = board.follow_up_first[0]
    assert row.follow_up_window == FollowUpWindow.REACH_OUT_TODAY
    assert row.open_case_id == case_id
    assert any(note.kind.value == "case" for note in row.take_note)


def test_revoked_consent_is_held_through_the_repository(repository: SqlAlchemyRepository) -> None:
    for index in range(3):
        repository.advance("activity_declines", event_id=f"triage-consent-{index}")
    repository.advance("consent_revoked", event_id="triage-consent-revoked")

    board = repository.care_priorities()

    assert board.follow_up_first == []
    assert board.people[0].hold == PriorityHold.CONSENT_WITHDRAWN


def test_the_board_reads_the_decision_that_was_recorded_each_day(
    repository: SqlAlchemyRepository,
) -> None:
    """Re-running the ladder at read time counts the day's own intervention against the weekly
    cap, so a programme suggestion that was sent would read as `contact_cap`."""
    windows = []
    for index in range(3):
        repository.advance("activity_declines", event_id=f"triage-recorded-{index}")
        windows.append(repository.care_priorities().people[0].follow_up_window)
    assert windows == [
        FollowUpWindow.KEEP_AN_EYE_ON,
        FollowUpWindow.CHECK_IN_WITHIN_48H,
        FollowUpWindow.REACH_OUT_TODAY,
    ]


def test_a_decision_downgraded_by_the_persons_mutes_is_not_a_contact_window(
    repository: SqlAlchemyRepository,
) -> None:
    """Every nudge muted means `advance` records `NO_ACTION`. A read-time re-run of the ladder
    skips that downgrade and would have offered the caregiver a check-in the person opted out of."""
    repository.advance("public_holiday", event_id="triage-mute-0")
    for preference in repository.list_candidate_preferences():
        if preference.candidate_key.startswith("gentle_nudge:"):
            repository.set_candidate_preference(
                preference.candidate_key, True, None, actor="senior"
            )
    for index in (1, 2):
        repository.advance("public_holiday", event_id=f"triage-mute-{index}")
        row = repository.care_priorities().people[0]
        assert row.follow_up_window not in CONTACT_WINDOWS, row
        assert "sending a gentle nudge" not in row.headline


def test_accepting_the_suggestion_that_day_holds_the_board_back(
    repository: SqlAlchemyRepository,
) -> None:
    """The recorded decision is a programme suggestion, but the person accepted it afterwards: the
    cooldown that now applies must win over the decision recorded before it."""
    for index in range(2):
        repository.advance("activity_declines", event_id=f"triage-accept-{index}")
    assert (
        repository.care_priorities().people[0].follow_up_window
        == FollowUpWindow.CHECK_IN_WITHIN_48H
    )
    latest = repository.list_interventions()[0]
    repository.record_outcome(latest.intervention_id, "accepted")

    row = repository.care_priorities().people[0]

    assert row.follow_up_window not in CONTACT_WINDOWS


def test_a_recent_uptake_holds_back_even_a_recorded_suggestion(base_state: PersonState) -> None:
    state = _state(
        base_state,
        decision=Decision.PROGRAMME_SUGGESTION,
        gate=PolicyGate.SEVERITY_PERSISTENCE,
        delta=-30,
        sustained=2,
    )
    row = _only(state, CareContext(accepted_recently=True, recent_no_reply=1))
    assert row.follow_up_window == FollowUpWindow.KEEP_AN_EYE_ON
    assert any(note.kind.value == "space" for note in row.take_note)


def test_an_open_case_on_a_lower_rung_does_not_claim_a_sustained_decline(
    base_state: PersonState,
) -> None:
    state = _state(
        base_state,
        decision=Decision.GENTLE_NUDGE,
        gate=PolicyGate.SEVERITY_PERSISTENCE,
        delta=-25,
        sustained=1,
    )
    row = _only(state, CareContext(open_case_id="c", open_case_status=CaseStatus.OPEN))
    assert row.follow_up_window == FollowUpWindow.REACH_OUT_TODAY
    assert "several days" not in row.headline


def test_reading_the_board_writes_nothing(repository: SqlAlchemyRepository) -> None:
    for index in range(3):
        repository.advance("activity_declines", event_id=f"triage-readonly-{index}")
    events_before = len(repository.list_events())
    cases_before = repository.list_cases()

    repository.care_priorities()
    repository.care_priorities(top_k=1)

    assert len(repository.list_events()) == events_before
    assert repository.list_cases() == cases_before


def test_the_priorities_route_returns_the_board(client: TestClient) -> None:
    client.post("/v1/demo/reset")
    response = client.get("/v1/coordinator/priorities", params={"top_k": 2})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["top_k"] == 2
    assert body["people"], "the seeded person must be on the board"
    assert client.get("/v1/coordinator/priorities", params={"top_k": 0}).status_code == 422
    too_many = client.get("/v1/coordinator/priorities", params={"top_k": MAX_TOP_K + 1})
    assert too_many.status_code == 422
