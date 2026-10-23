"""What changed on a review case since a human last looked at it (UX audit P1-6).

The Care Team case detail needs a "Since your last review" section, and a browser that assembles
one out of a case's history is guessing: it cannot tell a day decided after a review from one
decided before it without re-implementing the anchor rule, and it would have to string-match
stored prose to say anything about context. So the delta is produced here, on the server, as a
pure function of plain facts the repository reads from append-only rows.

The anchor
----------
"Since" is the most recent review a human recorded on the case (any reviewer but `system`). With
no human review yet it is the moment the case opened, and the payload says so
(`anchor_kind = case_opened`) so the surface can caption it "since this case opened" rather than
claim a review that never happened.

Two clocks, each used for what it can honestly order:

- Days the policy decided are simulated days. A review has no simulated day of its own, so its
  `anchor_day` is the latest decided day recorded at or before it -- the day the coordinator was
  looking at. For an opening anchor it is the stored `opened_day`. Days strictly after the anchor
  day are "new"; the anchor day itself was already on screen.
- Things written between advances -- a senior's response, a review-setting proposal or decision --
  have only a wall-clock timestamp, and are "new" when recorded strictly after the anchor's.

What is never reported
----------------------
Nothing the person told Care+: no stated explanation (not even that one exists or ended), no
disputed day, no decline reason, no baseline confirmation -- the standing rule of every
coordinator surface (`docs/care-priorities.md`). No review note. No step count, percentage or
score: day readings are reported as counts of days, below or not below the person's own usual
range, the same "low day" test `analytics._sustained_low_days` applies. Every sentence is a fixed
template filled with counts and days written the way a person reads them ("Thu, 20 Aug"); the
machine-readable date stays on `SinceLastReviewItem.day`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from silverloop.models import (
    Decision,
    OutcomeKind,
    ReviewThresholdDecisionKind,
    SinceLastReview,
    SinceLastReviewAnchorKind,
    SinceLastReviewItem,
    SinceLastReviewKind,
)

SYSTEM_REVIEWER = "system"


@dataclass(frozen=True)
class ReviewFact:
    """One stored review of the case (`case_reviews`)."""

    review_id: str
    reviewer: str
    recorded_at: datetime


@dataclass(frozen=True)
class DecidedDayFact:
    """One stored daily decision in the case's run (`decision_evidence`)."""

    day: date
    decision_evidence_id: str
    recorded_at: datetime


@dataclass(frozen=True)
class DayReadingFact:
    """One stored day's reading (`daily_metrics`), with the two judgements the ladder made of it.

    `usable` is the wear-time gate (`quality.assess_data_quality.safe_to_interpret`);
    `below_usual_range` is the low-day test on that day's recomputed signal
    (`sustained_low_days >= 1`), false whenever `usable` is. `rainy` and `holiday` are the day's
    stored context.
    """

    day: date
    wearable_evidence_id: str
    usable: bool
    below_usual_range: bool
    rainy: bool
    holiday: bool


@dataclass(frozen=True)
class OutreachFact:
    """One offer Care+ made in the run (`interventions`, never a withdrawn one)."""

    intervention_id: str
    decision: Decision
    day: date


@dataclass(frozen=True)
class OfferResponseFact:
    """One stored response to an offer (`intervention_outcomes`)."""

    outcome_id: str
    intervention_id: str
    decision: Decision
    offered_day: date
    outcome: str
    recorded_at: datetime


@dataclass(frozen=True)
class ReviewTimingFact:
    """One stored review-setting event for the person (ADR 0008).

    `event` is `"proposal"` for an agent or fixed-rule proposal row, or a
    `ReviewThresholdDecisionKind` value for a decision row.
    """

    evidence_id: str
    event: str
    day: date
    recorded_at: datetime


@dataclass(frozen=True)
class CaseAnchor:
    kind: SinceLastReviewAnchorKind
    day: date | None
    recorded_at: datetime


PROPOSAL_EVENT = "proposal"


def resolve_anchor(
    *,
    opened_at: datetime,
    opened_day: date | None,
    reviews: Sequence[ReviewFact],
    decided_days: Sequence[DecidedDayFact],
) -> CaseAnchor:
    """The latest human review, or the case opening. See the module docstring."""
    human = [review for review in reviews if review.reviewer != SYSTEM_REVIEWER]
    if human:
        latest = max(human, key=lambda review: (review.recorded_at, review.review_id))
        return CaseAnchor(
            kind=SinceLastReviewAnchorKind.LAST_REVIEW,
            day=_latest_day_recorded_by(decided_days, latest.recorded_at),
            recorded_at=latest.recorded_at,
        )
    return CaseAnchor(
        kind=SinceLastReviewAnchorKind.CASE_OPENED,
        day=(
            opened_day
            if opened_day is not None
            else _latest_day_recorded_by(decided_days, opened_at)
        ),
        recorded_at=opened_at,
    )


def _latest_day_recorded_by(decided_days: Sequence[DecidedDayFact], at: datetime) -> date | None:
    days = [fact.day for fact in decided_days if fact.recorded_at <= at]
    return max(days) if days else None


_OUTREACH_NOUNS: dict[Decision, str] = {
    Decision.GENTLE_NUDGE: "the check-in",
    Decision.PROGRAMME_SUGGESTION: "the suggestion",
}

_OUTREACH_OFFERED_NOUNS: dict[Decision, str] = {
    Decision.GENTLE_NUDGE: "a check-in",
    Decision.PROGRAMME_SUGGESTION: "a suggestion",
}

_RESPONSE_KINDS: dict[str, SinceLastReviewKind] = {
    OutcomeKind.ACCEPTED.value: SinceLastReviewKind.OUTREACH_ACCEPTED,
    OutcomeKind.DECLINED.value: SinceLastReviewKind.OUTREACH_DECLINED,
    OutcomeKind.DEFERRED.value: SinceLastReviewKind.OUTREACH_DEFERRED,
    OutcomeKind.NO_RESPONSE.value: SinceLastReviewKind.OUTREACH_NO_RESPONSE,
}

_RESPONSE_TEMPLATES: dict[SinceLastReviewKind, str] = {
    # `accepted` is only "show me more" -- never reported as having done anything.
    SinceLastReviewKind.OUTREACH_ACCEPTED: "They asked to see more about {noun} offered on {day}.",
    SinceLastReviewKind.OUTREACH_DECLINED: "They declined {noun} offered on {day}.",
    SinceLastReviewKind.OUTREACH_DEFERRED: "They chose to leave {noun} offered on {day} for later.",
    SinceLastReviewKind.OUTREACH_NO_RESPONSE: "No reply was recorded to {noun} offered on {day}.",
}

# Said once per delta, on the first unanswered offer: repeated on every one it reads as boilerplate.
_SILENCE_IS_NOT_A_REFUSAL = " Silence is not a refusal."


def _day_text(day: date) -> str:
    """A day as a coordinator reads it, e.g. "Thu, 20 Aug" -- never an ISO date in a sentence."""
    return f"{day:%a}, {day.day} {day:%b}"


_TIMING_KINDS: dict[str, SinceLastReviewKind] = {
    PROPOSAL_EVENT: SinceLastReviewKind.REVIEW_TIMING_PROPOSED,
    ReviewThresholdDecisionKind.APPROVED.value: SinceLastReviewKind.REVIEW_TIMING_APPROVED,
    ReviewThresholdDecisionKind.REJECTED.value: SinceLastReviewKind.REVIEW_TIMING_REJECTED,
    ReviewThresholdDecisionKind.REVERTED.value: SinceLastReviewKind.REVIEW_TIMING_REVERTED,
    ReviewThresholdDecisionKind.EXPIRED.value: SinceLastReviewKind.REVIEW_TIMING_EXPIRED,
}

_TIMING_TEMPLATES: dict[SinceLastReviewKind, str] = {
    SinceLastReviewKind.REVIEW_TIMING_PROPOSED: (
        "A change to when Care+ asks the care team about them was proposed on {day}. "
        "Nothing changes unless a coordinator approves it."
    ),
    SinceLastReviewKind.REVIEW_TIMING_APPROVED: (
        "A change to when Care+ asks the care team about them was approved on {day}. "
        "It applies from the next simulated day."
    ),
    SinceLastReviewKind.REVIEW_TIMING_REJECTED: (
        "A proposed change to when Care+ asks the care team about them was closed without "
        "approval on {day}."
    ),
    SinceLastReviewKind.REVIEW_TIMING_REVERTED: (
        "A change to when Care+ asks the care team about them was reversed on {day}."
    ),
    SinceLastReviewKind.REVIEW_TIMING_EXPIRED: (
        "A temporary change to when Care+ asks the care team about them ended on {day}."
    ),
}

_CONTEXT_TEMPLATES: dict[SinceLastReviewKind, str] = {
    SinceLastReviewKind.RAIN_STARTED: (
        "Rain was recorded on {day}, which can explain a quieter day."
    ),
    SinceLastReviewKind.RAIN_ENDED: (
        "No rain was recorded on {day}, so rain no longer explains a quieter day."
    ),
    SinceLastReviewKind.HOLIDAY_STARTED: "{day} was a public holiday, when routines often change.",
    SinceLastReviewKind.HOLIDAY_ENDED: (
        "{day} was not a public holiday, so a holiday no longer explains a change."
    ),
}


def _usable_text(usable: int, recorded: int) -> str:
    if recorded == 1:
        return f"Tracker data was {'usable' if usable else 'not usable'} that day."
    return f"Tracker data was usable on {usable} of those {recorded} days."


def _below_text(below: int, usable: int) -> str:
    if usable == 1:
        return (
            f"Activity was {'below' if below else 'not below'} their usual range on the day with "
            "usable tracker data."
        )
    return (
        f"Activity was below their usual range on {below} of the {usable} days with usable "
        "tracker data."
    )


def _after_day(day: date, anchor: CaseAnchor) -> bool:
    return anchor.day is None or day > anchor.day


def since_last_review(
    anchor: CaseAnchor,
    *,
    decided_days: Sequence[DecidedDayFact],
    readings: Sequence[DayReadingFact],
    outreach: Sequence[OutreachFact],
    responses: Sequence[OfferResponseFact],
    review_timing: Sequence[ReviewTimingFact],
) -> SinceLastReview:
    """Every reportable fact recorded after `anchor`, as fixed sentences. Pure and total.

    `readings` should cover the anchor day (for context comparison) and every decided day after
    it; a decided day with no reading counts as recorded but not usable, and takes no part in
    context comparison.
    """
    items: list[SinceLastReviewItem] = []

    new_days = sorted(
        (fact for fact in decided_days if _after_day(fact.day, anchor)),
        key=lambda fact: (fact.day, fact.decision_evidence_id),
    )
    reading_by_day = {reading.day: reading for reading in readings}

    if new_days:
        day_readings = [reading_by_day[fact.day] for fact in new_days if fact.day in reading_by_day]
        usable = [reading for reading in day_readings if reading.usable]
        below = [reading for reading in usable if reading.below_usual_range]
        items.append(
            SinceLastReviewItem(
                kind=SinceLastReviewKind.DAYS_RECORDED,
                text=(
                    f"Care+ recorded and decided {len(new_days)} more "
                    f"{'day' if len(new_days) == 1 else 'days'}."
                ),
                count=len(new_days),
                evidence_ids=[fact.decision_evidence_id for fact in new_days],
            )
        )
        items.append(
            SinceLastReviewItem(
                kind=SinceLastReviewKind.USABLE_DATA_DAYS,
                text=_usable_text(len(usable), len(new_days)),
                count=len(usable),
                evidence_ids=[reading.wearable_evidence_id for reading in usable],
            )
        )
        if usable:
            items.append(
                SinceLastReviewItem(
                    kind=SinceLastReviewKind.BELOW_USUAL_RANGE_DAYS,
                    text=_below_text(len(below), len(usable)),
                    count=len(below),
                    evidence_ids=[reading.wearable_evidence_id for reading in below],
                )
            )

    # The event items follow the day counts: context changes (they frame the days), then offers,
    # then responses, then review timing -- each group in the order it happened. Grouped rather
    # than interleaved by day because a response has no simulated day of its own: its `day` is
    # the day the offer was made, which can precede the anchor.
    events: list[SinceLastReviewItem] = []

    # Context that started or ended, day over day, starting from the anchor day's own reading.
    previous = reading_by_day.get(anchor.day) if anchor.day is not None else None
    previous_rainy = previous.rainy if previous is not None else False
    previous_holiday = previous.holiday if previous is not None else False
    for fact in new_days:
        reading = reading_by_day.get(fact.day)
        if reading is None:
            continue
        for now_on, was_on, started, ended in (
            (
                reading.rainy,
                previous_rainy,
                SinceLastReviewKind.RAIN_STARTED,
                SinceLastReviewKind.RAIN_ENDED,
            ),
            (
                reading.holiday,
                previous_holiday,
                SinceLastReviewKind.HOLIDAY_STARTED,
                SinceLastReviewKind.HOLIDAY_ENDED,
            ),
        ):
            if now_on == was_on:
                continue
            kind = started if now_on else ended
            events.append(
                SinceLastReviewItem(
                    kind=kind,
                    text=_CONTEXT_TEMPLATES[kind].format(day=_day_text(reading.day)),
                    day=reading.day,
                    evidence_ids=[reading.wearable_evidence_id],
                )
            )
        previous_rainy = reading.rainy
        previous_holiday = reading.holiday

    for offer in sorted(outreach, key=lambda fact: (fact.day, fact.intervention_id)):
        if not _after_day(offer.day, anchor):
            continue
        noun = _OUTREACH_OFFERED_NOUNS.get(offer.decision, "an offer")
        events.append(
            SinceLastReviewItem(
                kind=SinceLastReviewKind.OUTREACH_OFFERED,
                text=f"Care+ offered {noun} on {_day_text(offer.day)}.",
                day=offer.day,
                evidence_ids=[offer.intervention_id],
            )
        )

    silence_explained = False
    for response in sorted(responses, key=lambda fact: (fact.recorded_at, fact.outcome_id)):
        if response.recorded_at <= anchor.recorded_at:
            continue
        kind = _RESPONSE_KINDS.get(response.outcome)
        if kind is None:
            # `activity_recovered` / `coordinator_resolved` are not a person's response.
            continue
        text = _RESPONSE_TEMPLATES[kind].format(
            noun=_OUTREACH_NOUNS.get(response.decision, "the offer"),
            day=_day_text(response.offered_day),
        )
        if kind == SinceLastReviewKind.OUTREACH_NO_RESPONSE and not silence_explained:
            text += _SILENCE_IS_NOT_A_REFUSAL
            silence_explained = True
        events.append(
            SinceLastReviewItem(
                kind=kind,
                text=text,
                day=response.offered_day,
                evidence_ids=[response.outcome_id, response.intervention_id],
            )
        )

    for timing in sorted(
        review_timing, key=lambda fact: (fact.recorded_at, fact.day, fact.evidence_id)
    ):
        if timing.recorded_at <= anchor.recorded_at:
            continue
        kind = _TIMING_KINDS.get(timing.event)
        if kind is None:
            # Checks and reconfirmations change nothing about when a human is asked.
            continue
        events.append(
            SinceLastReviewItem(
                kind=kind,
                text=_TIMING_TEMPLATES[kind].format(day=_day_text(timing.day)),
                day=timing.day,
                evidence_ids=[timing.evidence_id],
            )
        )

    items.extend(events)
    return SinceLastReview(
        anchor_kind=anchor.kind,
        anchor_day=anchor.day,
        anchor_recorded_at=anchor.recorded_at,
        nothing_new=not items,
        items=items,
    )
