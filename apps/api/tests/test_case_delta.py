"""The "since your last review" derivation, as a pure function (UX audit P1-6).

Every branch is driven from plain facts rather than through the repository: the anchor rule, the
day counts, context that started or ended, outreach and responses, review-timing events, and the
wording every template produces.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pytest

from silverloop.agent.guardrails import coordinator_text_violations
from silverloop.case_delta import (
    PROPOSAL_EVENT,
    CaseAnchor,
    DayReadingFact,
    DecidedDayFact,
    OfferResponseFact,
    OutreachFact,
    ReviewFact,
    ReviewTimingFact,
    resolve_anchor,
    since_last_review,
)
from silverloop.models import (
    Decision,
    OutcomeKind,
    ReviewThresholdDecisionKind,
    SinceLastReview,
    SinceLastReviewAnchorKind,
    SinceLastReviewKind,
)

D0 = date(2026, 8, 21)
T0 = datetime(2026, 9, 16, 9, 0, tzinfo=UTC)


def _day(offset: int) -> date:
    return D0 + timedelta(days=offset)


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _decided(offset: int, minutes: int | None = None) -> DecidedDayFact:
    return DecidedDayFact(
        day=_day(offset),
        decision_evidence_id=f"decision_{offset}",
        recorded_at=_at(offset * 10 if minutes is None else minutes),
    )


def _reading(
    offset: int,
    *,
    usable: bool = True,
    below: bool = True,
    rainy: bool = False,
    holiday: bool = False,
) -> DayReadingFact:
    return DayReadingFact(
        day=_day(offset),
        wearable_evidence_id=f"wearable_{offset}",
        usable=usable,
        below_usual_range=usable and below,
        rainy=rainy,
        holiday=holiday,
    )


def _anchor(day_offset: int | None = 0, minutes: int = 5) -> CaseAnchor:
    return CaseAnchor(
        kind=SinceLastReviewAnchorKind.LAST_REVIEW,
        day=None if day_offset is None else _day(day_offset),
        recorded_at=_at(minutes),
    )


def _derive(
    anchor: CaseAnchor,
    *,
    decided: list[DecidedDayFact] | None = None,
    readings: list[DayReadingFact] | None = None,
    outreach: list[OutreachFact] | None = None,
    responses: list[OfferResponseFact] | None = None,
    timing: list[ReviewTimingFact] | None = None,
) -> SinceLastReview:
    return since_last_review(
        anchor,
        decided_days=decided or [],
        readings=readings or [],
        outreach=outreach or [],
        responses=responses or [],
        review_timing=timing or [],
    )


def _kinds(result: SinceLastReview) -> list[SinceLastReviewKind]:
    return [item.kind for item in result.items]


# ── The anchor ────────────────────────────────────────────────────────────────────────────────


def test_no_review_anchors_on_the_case_opening() -> None:
    anchor = resolve_anchor(
        opened_at=_at(1), opened_day=D0, reviews=[], decided_days=[_decided(0, 0)]
    )

    assert anchor == CaseAnchor(SinceLastReviewAnchorKind.CASE_OPENED, D0, _at(1))


def test_a_system_review_is_never_an_anchor() -> None:
    anchor = resolve_anchor(
        opened_at=_at(1),
        opened_day=D0,
        reviews=[ReviewFact("review_sys", "system", _at(50))],
        decided_days=[_decided(0, 0), _decided(1, 20)],
    )

    assert anchor.kind is SinceLastReviewAnchorKind.CASE_OPENED
    assert anchor.recorded_at == _at(1)


def test_the_latest_human_review_is_the_anchor_and_its_day_is_the_day_on_screen() -> None:
    decided = [_decided(0, 0), _decided(1, 20), _decided(2, 40)]
    reviews = [
        ReviewFact("review_a", "coord-1", _at(5)),
        ReviewFact("review_b", "coord-2", _at(25)),
        ReviewFact("review_sys", "system", _at(45)),
    ]

    anchor = resolve_anchor(opened_at=_at(1), opened_day=D0, reviews=reviews, decided_days=decided)

    assert anchor.kind is SinceLastReviewAnchorKind.LAST_REVIEW
    assert anchor.recorded_at == _at(25)
    # Recorded after day 1's decision and before day 2's: the coordinator was looking at day 1.
    assert anchor.day == _day(1)


def test_a_legacy_case_without_an_opening_day_derives_it_from_the_decisions() -> None:
    anchor = resolve_anchor(
        opened_at=_at(21),
        opened_day=None,
        reviews=[],
        decided_days=[_decided(0, 0), _decided(1, 20), _decided(2, 40)],
    )
    assert anchor.day == _day(1)

    nothing_before = resolve_anchor(
        opened_at=_at(-5), opened_day=None, reviews=[], decided_days=[_decided(0, 0)]
    )
    assert nothing_before.day is None


# ── Day counts ────────────────────────────────────────────────────────────────────────────────


def test_nothing_after_the_anchor_is_nothing_new() -> None:
    result = _derive(_anchor(0), decided=[_decided(0)], readings=[_reading(0)])

    assert result.nothing_new is True
    assert result.items == []
    assert result.anchor_day == D0
    assert result.anchor_kind is SinceLastReviewAnchorKind.LAST_REVIEW


def test_days_after_the_anchor_day_are_counted_and_the_anchor_day_is_not() -> None:
    decided = [_decided(offset) for offset in range(-1, 4)]
    readings = [
        _reading(-1),
        _reading(0),
        _reading(1, below=True),
        _reading(2, usable=False),
        _reading(3, below=False),
    ]

    result = _derive(_anchor(0), decided=decided, readings=readings)

    assert result.nothing_new is False
    days, usable, below = result.items[:3]
    assert days.kind is SinceLastReviewKind.DAYS_RECORDED
    assert days.count == 3
    assert days.evidence_ids == ["decision_1", "decision_2", "decision_3"]
    assert days.text == "Care+ recorded and decided 3 more days."
    assert usable.kind is SinceLastReviewKind.USABLE_DATA_DAYS
    assert usable.count == 2
    assert usable.evidence_ids == ["wearable_1", "wearable_3"]
    assert usable.text == "Tracker data was usable on 2 of those 3 days."
    assert below.kind is SinceLastReviewKind.BELOW_USUAL_RANGE_DAYS
    assert below.count == 1
    assert below.evidence_ids == ["wearable_1"]
    assert below.text == (
        "Activity was below their usual range on 1 of the 2 days with usable tracker data."
    )


def test_no_usable_day_reports_no_below_range_count() -> None:
    result = _derive(
        _anchor(0),
        decided=[_decided(1), _decided(2)],
        readings=[_reading(1, usable=False), _reading(2, usable=False)],
    )

    assert _kinds(result) == [
        SinceLastReviewKind.DAYS_RECORDED,
        SinceLastReviewKind.USABLE_DATA_DAYS,
    ]
    assert result.items[1].count == 0
    assert result.items[1].evidence_ids == []


@pytest.mark.parametrize(
    ("usable", "below", "usable_text", "below_text"),
    [
        (
            True,
            True,
            "Tracker data was usable that day.",
            "Activity was below their usual range on the day with usable tracker data.",
        ),
        (
            True,
            False,
            "Tracker data was usable that day.",
            "Activity was not below their usual range on the day with usable tracker data.",
        ),
        (False, False, "Tracker data was not usable that day.", None),
    ],
)
def test_one_new_day_reads_naturally(
    usable: bool, below: bool, usable_text: str, below_text: str | None
) -> None:
    result = _derive(
        _anchor(0), decided=[_decided(1)], readings=[_reading(1, usable=usable, below=below)]
    )

    assert result.items[0].text == "Care+ recorded and decided 1 more day."
    assert result.items[1].text == usable_text
    texts = [item.text for item in result.items]
    if below_text is None:
        assert len(texts) == 2
    else:
        assert texts[2] == below_text


def test_a_decided_day_without_a_reading_counts_as_recorded_but_not_usable() -> None:
    result = _derive(_anchor(0), decided=[_decided(1)], readings=[])

    assert result.items[0].count == 1
    assert result.items[1].count == 0


def test_an_anchor_without_a_day_counts_every_decided_day() -> None:
    result = _derive(
        _anchor(None), decided=[_decided(0), _decided(1)], readings=[_reading(0), _reading(1)]
    )

    assert result.items[0].count == 2


# ── Context that started or ended ─────────────────────────────────────────────────────────────


def test_rain_that_starts_and_ends_after_the_anchor_is_reported_on_its_days() -> None:
    result = _derive(
        _anchor(0),
        decided=[_decided(1), _decided(2), _decided(3)],
        readings=[_reading(0), _reading(1, rainy=True), _reading(2, rainy=True), _reading(3)],
    )

    context = [item for item in result.items if item.day is not None]
    assert [(item.kind, item.day, item.evidence_ids) for item in context] == [
        (SinceLastReviewKind.RAIN_STARTED, _day(1), ["wearable_1"]),
        (SinceLastReviewKind.RAIN_ENDED, _day(3), ["wearable_3"]),
    ]


def test_rain_already_on_the_anchor_day_only_ends() -> None:
    result = _derive(
        _anchor(0),
        decided=[_decided(1), _decided(2)],
        readings=[_reading(0, rainy=True), _reading(1, rainy=True), _reading(2)],
    )

    assert [item.kind for item in result.items if item.day is not None] == [
        SinceLastReviewKind.RAIN_ENDED
    ]


def test_holiday_start_and_end_are_reported() -> None:
    result = _derive(
        _anchor(0),
        decided=[_decided(1), _decided(2)],
        readings=[_reading(0), _reading(1, holiday=True), _reading(2)],
    )

    assert [item.kind for item in result.items if item.day is not None] == [
        SinceLastReviewKind.HOLIDAY_STARTED,
        SinceLastReviewKind.HOLIDAY_ENDED,
    ]


def test_context_before_the_anchor_is_not_news() -> None:
    result = _derive(
        _anchor(1),
        decided=[_decided(0), _decided(1)],
        readings=[_reading(0, rainy=True), _reading(1)],
    )

    assert result.nothing_new is True


# ── Outreach and responses ────────────────────────────────────────────────────────────────────


def _offer(intervention_id: str, decision: Decision, offset: int) -> OutreachFact:
    return OutreachFact(intervention_id, decision, _day(offset))


def _response(
    outcome_id: str, outcome: OutcomeKind, minutes: int, offset: int = -1
) -> OfferResponseFact:
    return OfferResponseFact(
        outcome_id=outcome_id,
        intervention_id=f"int_{outcome_id}",
        decision=Decision.PROGRAMME_SUGGESTION,
        offered_day=_day(offset),
        outcome=outcome.value,
        recorded_at=_at(minutes),
    )


def test_only_offers_made_after_the_anchor_day_are_reported() -> None:
    result = _derive(
        _anchor(0),
        outreach=[
            _offer("int_before", Decision.GENTLE_NUDGE, -1),
            _offer("int_same", Decision.GENTLE_NUDGE, 0),
            _offer("int_after", Decision.GENTLE_NUDGE, 2),
        ],
    )

    assert [(item.kind, item.evidence_ids, item.text) for item in result.items] == [
        (
            SinceLastReviewKind.OUTREACH_OFFERED,
            ["int_after"],
            "Care+ offered a check-in on Sun, 23 Aug.",
        )
    ]


def test_responses_recorded_after_the_anchor_are_reported_whatever_day_the_offer_was() -> None:
    result = _derive(
        _anchor(0, minutes=5),
        responses=[
            _response("before", OutcomeKind.DECLINED, minutes=4),
            _response("accepted", OutcomeKind.ACCEPTED, minutes=6),
            _response("declined", OutcomeKind.DECLINED, minutes=7),
            _response("deferred", OutcomeKind.DEFERRED, minutes=8),
            _response("silence", OutcomeKind.NO_RESPONSE, minutes=9),
            _response("recovered", OutcomeKind.ACTIVITY_RECOVERED, minutes=10),
        ],
    )

    offered = "Thu, 20 Aug"
    assert [(item.kind, item.text, item.evidence_ids[0]) for item in result.items] == [
        (
            SinceLastReviewKind.OUTREACH_ACCEPTED,
            f"They asked to see more about the suggestion offered on {offered}.",
            "accepted",
        ),
        (
            SinceLastReviewKind.OUTREACH_DECLINED,
            f"They declined the suggestion offered on {offered}.",
            "declined",
        ),
        (
            SinceLastReviewKind.OUTREACH_DEFERRED,
            f"They chose to leave the suggestion offered on {offered} for later.",
            "deferred",
        ),
        (
            SinceLastReviewKind.OUTREACH_NO_RESPONSE,
            f"No reply was recorded to the suggestion offered on {offered}. "
            "Silence is not a refusal.",
            "silence",
        ),
    ]
    assert all(item.day == _day(-1) for item in result.items)


def test_silence_is_not_a_refusal_is_said_once_however_many_offers_went_unanswered() -> None:
    result = _derive(
        _anchor(0, minutes=5),
        responses=[
            _response("silence_one", OutcomeKind.NO_RESPONSE, minutes=6, offset=-2),
            _response("silence_two", OutcomeKind.NO_RESPONSE, minutes=7, offset=-1),
        ],
    )

    assert [item.text for item in result.items] == [
        "No reply was recorded to the suggestion offered on Wed, 19 Aug. Silence is not a refusal.",
        "No reply was recorded to the suggestion offered on Thu, 20 Aug.",
    ]


# ── Review timing ─────────────────────────────────────────────────────────────────────────────


def test_review_timing_changes_after_the_anchor_are_reported_and_checks_are_not() -> None:
    events = [
        (PROPOSAL_EVENT, SinceLastReviewKind.REVIEW_TIMING_PROPOSED),
        (ReviewThresholdDecisionKind.APPROVED.value, SinceLastReviewKind.REVIEW_TIMING_APPROVED),
        (ReviewThresholdDecisionKind.REJECTED.value, SinceLastReviewKind.REVIEW_TIMING_REJECTED),
        (ReviewThresholdDecisionKind.REVERTED.value, SinceLastReviewKind.REVIEW_TIMING_REVERTED),
        (ReviewThresholdDecisionKind.EXPIRED.value, SinceLastReviewKind.REVIEW_TIMING_EXPIRED),
    ]
    timing = [
        ReviewTimingFact(f"timing_{index}", event, _day(1), _at(10 + index))
        for index, (event, _) in enumerate(events)
    ]
    timing += [
        ReviewTimingFact("before", PROPOSAL_EVENT, D0, _at(5)),
        ReviewTimingFact("check", ReviewThresholdDecisionKind.CHECK_CONFIRMED.value, D0, _at(30)),
        ReviewTimingFact(
            "unresolved", ReviewThresholdDecisionKind.CHECK_UNRESOLVED.value, D0, _at(31)
        ),
        ReviewTimingFact("reconfirm", ReviewThresholdDecisionKind.RECONFIRMED.value, D0, _at(32)),
    ]

    result = _derive(_anchor(0, minutes=5), timing=timing)

    assert _kinds(result) == [kind for _, kind in events]
    assert all(item.day == _day(1) for item in result.items)


# ── Wording ───────────────────────────────────────────────────────────────────────────────────


def _every_kind() -> SinceLastReview:
    anchor = _anchor(0, minutes=5)
    return _derive(
        anchor,
        decided=[_decided(1), _decided(2), _decided(3)],
        readings=[
            _reading(0),
            _reading(1, rainy=True, holiday=True),
            _reading(2, usable=False),
            _reading(3),
        ],
        outreach=[
            _offer("int_nudge", Decision.GENTLE_NUDGE, 1),
            _offer("int_suggestion", Decision.PROGRAMME_SUGGESTION, 2),
        ],
        responses=[
            _response(outcome.value, outcome, minutes=10 + index)
            for index, outcome in enumerate(
                (
                    OutcomeKind.ACCEPTED,
                    OutcomeKind.DECLINED,
                    OutcomeKind.DEFERRED,
                    OutcomeKind.NO_RESPONSE,
                )
            )
        ],
        timing=[
            ReviewTimingFact(event, event, _day(2), _at(20 + index))
            for index, event in enumerate(
                (
                    PROPOSAL_EVENT,
                    ReviewThresholdDecisionKind.APPROVED.value,
                    ReviewThresholdDecisionKind.REJECTED.value,
                    ReviewThresholdDecisionKind.REVERTED.value,
                    ReviewThresholdDecisionKind.EXPIRED.value,
                )
            )
        ],
    )


def test_every_kind_is_reachable() -> None:
    assert set(_kinds(_every_kind())) == set(SinceLastReviewKind)


def test_every_template_passes_the_coordinator_wording_guardrail() -> None:
    for item in _every_kind().items:
        assert coordinator_text_violations(item.text) == [], item.text
        # No percentages or figures about the person: only counts of days and readable days.
        assert "%" not in item.text
        # A day in a sentence is written for a person ("Thu, 20 Aug"), never as an ISO date.
        assert re.search(r"\d{4}-\d{2}-\d{2}", item.text) is None, item.text
        assert "step" not in item.text.lower()
        assert item.evidence_ids, item.kind


def test_accepted_is_never_reported_as_having_done_anything() -> None:
    accepted = [
        item for item in _every_kind().items if item.kind is SinceLastReviewKind.OUTREACH_ACCEPTED
    ]
    assert len(accepted) == 1
    for word in ("accepted", "completed", "attended", "joined", "success"):
        assert word not in accepted[0].text.lower()
