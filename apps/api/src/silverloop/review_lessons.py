"""What each coordinator review teaches Care+ (docs/calibration-trust-spec.md, section A).

A coordinator's action is not ground truth. This module makes visible what one review can and
cannot teach, without storing anything new beyond the optional context-gap category:

- `classify_review`, a pure function of the stored review;
- `build_receipt`, which reviews counted toward a review setting and which were excluded and why;
- `tally_context_gaps`, known-context overrides for one person, by category.

Pure and read-only. It may import `review_threshold` for the fixed counting rule's constants and
the live-setting fold, but `policy`, `review_threshold` and `agent.*` must never import this module:
nothing here may change a decision, a proposal or a review setting.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from silverloop.models import (
    CaseStatus,
    ContextGapCategory,
    ContextGapCount,
    ContextGapTally,
    HumanAction,
    OverrideReason,
    ReviewLesson,
    ReviewLessonKind,
    ReviewLessonReason,
    ReviewReceiptEntry,
    ReviewReceiptExclusion,
    ReviewReceiptStatus,
    ReviewSettingReceipt,
    ReviewThresholdDecisionKind,
    ReviewThresholdProposer,
)
from silverloop.review_threshold import (
    FIXED_RULE_FALSE_ALARMS,
    FIXED_RULE_WINDOW_DAYS,
    ThresholdDecisionFact,
    resolve_live_threshold,
)

ReceiptSubject = Literal["open_proposal", "live_setting", "next_proposal"]
ReceiptDirection = Literal["looser", "sooner", "no_change"]

# Only the calibrator's own proposals are made by counting reviews. A coordinator's manual set and
# the starting-setting confirmation are recorded as proposals too, but no review counted toward
# them.
_COUNTING_PROPOSERS = frozenset({ReviewThresholdProposer.AGENT, ReviewThresholdProposer.FIXED_RULE})

SYSTEM_REVIEWER = "system"

# Fixed template text, one per reason. Never the coordinator's note, never an activity figure.
LESSON_SUMMARIES: dict[ReviewLessonReason, str] = {
    ReviewLessonReason.REACHED_TOO_LATE: (
        "Marked as a case that should have reached the care team sooner. Care+ counts this "
        "toward asking sooner for this person, and a coordinator approves any change."
    ),
    ReviewLessonReason.NOT_A_CONCERN: (
        "Resolved as ordinary for this person. Care+ counts this toward waiting a little "
        "longer before asking, and a coordinator approves any change."
    ),
    ReviewLessonReason.KNOWN_CONTEXT: (
        "Resolved because of context the care team already knew. Care+ records this as "
        "context it could not see; the review setting did not change."
    ),
    ReviewLessonReason.AGREED: (
        "The coordinator agreed with the suggestion. Agreement does not change when Care+ "
        "asks for a human."
    ),
    ReviewLessonReason.ON_HOLD: (
        "The coordinator put this on hold. A hold is not a judgement either way, so nothing "
        "changes."
    ),
    ReviewLessonReason.DATA_DOUBT: (
        "Overruled because the tracker readings looked unreliable. Doubtful readings do not change "
        "when Care+ asks for a human."
    ),
    ReviewLessonReason.RECENT_CONTACT: (
        "Overruled because the care team was recently in contact. That does not change when "
        "Care+ asks for a human."
    ),
    ReviewLessonReason.OTHER_REASON: (
        "Overruled for another reason. An unspecified reason cannot be counted, so nothing changes."
    ),
    ReviewLessonReason.NOT_RESOLVED: (
        "Marked as ordinary for this person without resolving the case. Only resolved reviews are "
        "counted, so nothing changes yet."
    ),
    ReviewLessonReason.NO_STRUCTURED_CHOICE: (
        "No structured choice was recorded with this review, so there is nothing to count."
    ),
    ReviewLessonReason.SYSTEM_CLOSURE: (
        "Care+ closed this case itself. No coordinator judgement was recorded, so there is "
        "nothing to learn."
    ),
}

_TEACHES_NOTHING_BY_OVERRIDE: dict[OverrideReason, ReviewLessonReason] = {
    OverrideReason.DATA_DOUBT: ReviewLessonReason.DATA_DOUBT,
    OverrideReason.RECENT_CONTACT: ReviewLessonReason.RECENT_CONTACT,
    OverrideReason.OTHER: ReviewLessonReason.OTHER_REASON,
    # Reached only when the case was not resolved (resolved ones count, earlier in precedence).
    OverrideReason.NOT_A_CONCERN: ReviewLessonReason.NOT_RESOLVED,
}

CONTEXT_GAP_DISCLOSURE = (
    "Known-context reviews for this person in the current story. Shown to the care team only; "
    "they change no decision, proposal or review setting."
)

RECEIPT_RULE = (
    "A review counts toward waiting longer before asking only when a coordinator resolved it as "
    "ordinary for this person, its case opened within the last "
    f"{FIXED_RULE_WINDOW_DAYS} days, and the current review setting was already in place when the "
    f"case opened. Care+ suggests waiting longer once {FIXED_RULE_FALSE_ALARMS} reviews "
    "count. A review marked as one that should have reached the care team sooner counts toward "
    "asking sooner instead. A coordinator approves any change."
)


@dataclass(frozen=True)
class ReceiptReview:
    """One stored review, as the receipt needs it: no reviewer, no note."""

    review_id: str
    case_id: str
    # The reviewed case's opening day; `None` for a case opened before the case clock existed.
    opened_day: date | None
    recorded_at: datetime
    lesson: ReviewLesson


@dataclass(frozen=True)
class ReceiptProposal:
    """One stored calibrator output (proposal, no-change or write-up)."""

    proposal_id: str
    # Whether it is the open proposal a coordinator can still approve or reject.
    is_open: bool
    proposed_on_day: date
    proposed_at: datetime
    # Real evidence ids: the agent's aliases are resolved before a proposal is stored, and a
    # `review:N` alias resolves to exactly that review's id.
    cited_evidence_ids: tuple[str, ...]
    trigger_review_ids: tuple[str, ...]
    # Which way the proposal moves the setting: `looser` asks later, `sooner` asks sooner, and
    # `no_change` is an output that proposes nothing (a no-change, a write-up or a confirmation).
    direction: ReceiptDirection
    proposer: ReviewThresholdProposer

    @property
    def counts_toward_loosening(self) -> bool:
        """Whether reviews counted toward this proposal: a looser one the calibrator made."""
        return self.direction == "looser" and self.proposer in _COUNTING_PROPOSERS


@dataclass(frozen=True)
class ReceiptDecision:
    """One stored review-setting decision, for what a review led to.

    `proposal_id` is the decided proposal, when there was one (a coordinator's approval or
    rejection; some decision kinds, like a shadow-check revert, decide no proposal). When it names
    a stored proposal, every review in that proposal's `trigger_review_ids` led to this decision,
    not only the single review `trigger_review_id` names -- the fixed rule's own counting rule can
    reach the same approval from more than one of the reviews that fed it.
    """

    decision_id: str
    decided_at: datetime
    trigger_review_id: str | None
    proposal_id: str | None = None


def context_gap_is_allowed(
    human_action: HumanAction | str | None, override_reason: OverrideReason | str | None
) -> bool:
    """Whether a context-gap category may accompany this choice: only an override for
    `known_context`. The same rule as `ReviewRequest`, enforced again by the repository."""
    return (
        human_action is not None
        and HumanAction(human_action) == HumanAction.OVERRIDE
        and override_reason is not None
        and OverrideReason(override_reason) == OverrideReason.KNOWN_CONTEXT
    )


def classify_review(
    *,
    review_id: str,
    status: CaseStatus | str,
    reviewer: str,
    human_action: HumanAction | str | None,
    override_reason: OverrideReason | str | None,
    reached_too_late: bool | None,
    context_gap_category: ContextGapCategory | str | None = None,
) -> ReviewLesson:
    """What one stored review teaches. Precedence (spec section A):

    1. `reached_too_late` -> counts toward the review setting (reached too late);
    2. resolved `OVERRIDE` for `not_a_concern` -> counts toward the review setting;
    3. `OVERRIDE` for `known_context` -> records a context gap;
    4. otherwise teaches nothing, with the reason why.

    `context_gap_category` is carried only beside an `OVERRIDE` for `known_context`, the one
    combination it may describe (`context_gap_is_allowed`); on any other stored row it is reported
    as `None`, so a malformed row can never be presented as known context Care+ missed.
    """
    action = HumanAction(human_action) if human_action is not None else None
    reason = OverrideReason(override_reason) if override_reason is not None else None
    category = (
        ContextGapCategory(context_gap_category)
        if context_gap_category and context_gap_is_allowed(action, reason)
        else None
    )

    kind: ReviewLessonKind
    lesson_reason: ReviewLessonReason
    if reviewer == SYSTEM_REVIEWER:
        # A system closure never carries a human choice; checked first so a malformed row can
        # never be presented as a coordinator judgement.
        kind, lesson_reason = ReviewLessonKind.TEACHES_NOTHING, ReviewLessonReason.SYSTEM_CLOSURE
    elif reached_too_late:
        kind = ReviewLessonKind.COUNTS_TOWARD_REVIEW_SETTING
        lesson_reason = ReviewLessonReason.REACHED_TOO_LATE
    elif (
        CaseStatus(status) == CaseStatus.RESOLVED
        and action == HumanAction.OVERRIDE
        and reason == OverrideReason.NOT_A_CONCERN
    ):
        kind = ReviewLessonKind.COUNTS_TOWARD_REVIEW_SETTING
        lesson_reason = ReviewLessonReason.NOT_A_CONCERN
    elif action == HumanAction.OVERRIDE and reason == OverrideReason.KNOWN_CONTEXT:
        kind, lesson_reason = ReviewLessonKind.RECORDS_CONTEXT_GAP, ReviewLessonReason.KNOWN_CONTEXT
    else:
        kind = ReviewLessonKind.TEACHES_NOTHING
        if action is None:
            lesson_reason = ReviewLessonReason.NO_STRUCTURED_CHOICE
        elif action == HumanAction.AGREE:
            lesson_reason = ReviewLessonReason.AGREED
        elif action == HumanAction.HOLD:
            lesson_reason = ReviewLessonReason.ON_HOLD
        elif reason is None:
            lesson_reason = ReviewLessonReason.NO_STRUCTURED_CHOICE
        else:
            lesson_reason = _TEACHES_NOTHING_BY_OVERRIDE[reason]

    return ReviewLesson(
        review_id=review_id,
        kind=kind,
        reason=lesson_reason,
        context_gap_category=category,
        summary=LESSON_SUMMARIES[lesson_reason],
    )


def build_receipt(
    *,
    reviews: Sequence[ReceiptReview],
    proposals: Sequence[ReceiptProposal],
    facts: Sequence[ThresholdDecisionFact],
    decisions: Sequence[ReceiptDecision],
    today: date,
) -> ReviewSettingReceipt:
    """Which reviews counted toward the review setting on screen, which were excluded and why.

    Subject: the open proposal (as of its `proposed_on_day`), else the proposal behind the live
    approval (as of its `proposed_on_day`), else an approval already made but not yet in force
    (as of its `proposed_on_day`, reported the same way as the live setting), else the next
    proposal as of `today`. Only a looser proposal the calibrator made (agent or fixed rule) can
    be the subject, because the receipt reports reviews "counted toward loosening": an open or
    live proposal that asks sooner, or a coordinator's manual set, was not reached by counting
    reviews, so the receipt describes the next proposal instead. For a proposal, only decisions
    recorded before it was made are folded, so the counting matches what the calibrator saw when
    it proposed.

    The pending-approval case matters on the day a proposal is approved: it takes effect the next
    day (`effective_from_day = decided_on_day + 1`), so `resolve_live_threshold(facts, today)`
    still reports the setting it replaces. Without this, the receipt would fall through to "the
    next proposal as of today" and fold every decision fact recorded so far -- including the
    just-made approval -- re-counting the same reviews that already fed it, unbounded by any
    proposal's `proposed_at`. Reporting the pending approval's proposal as the subject instead
    (like the live setting, once it is live) shows those reviews as already spent, honestly, one
    day early.

    Per review, in order: recorded after the proposal -> excluded (`after_proposal`); a lesson
    other than `not_a_concern` -> `asked_sooner` for `reached_too_late`, else excluded
    (`not_eligible_to_loosen`); then excluded for `no_opening_day`, `before_current_setting`
    (case opened before the setting in force took effect) or `outside_window` (case opened outside
    the `FIXED_RULE_WINDOW_DAYS` days ending on the as-of day); otherwise counted. This mirrors the
    repository's `_threshold_episode_context` and `fixed_rule_output`, pinned by an equivalence
    test rather than shared code, so the calibrator's own path stays untouched.

    `led_to_decision_id` is the earliest decision that changed review timing (an approval or a
    put-back with the value it moved to) among the decisions a review fed, else the earliest
    decision it fed: a rejected proposal passes its reviews to the retry in the same round, and
    the retry's approval is what those reviews led to.

    Entries are most recent first, like the threshold history.
    """
    subject: ReceiptSubject
    proposal = _latest(item for item in proposals if item.is_open)
    if proposal is not None and proposal.counts_toward_loosening:
        subject = "open_proposal"
    else:
        live_approval_id = resolve_live_threshold(facts, today).approval_id
        proposal = _counting_proposal_for_approval(proposals, facts, live_approval_id)
        if proposal is None:
            # Not live yet as of `today`, but it may already be decided, effective tomorrow.
            tomorrow = today + timedelta(days=1)
            pending_approval_id = resolve_live_threshold(facts, tomorrow).approval_id
            if pending_approval_id != live_approval_id:
                proposal = _counting_proposal_for_approval(proposals, facts, pending_approval_id)
        subject = "live_setting" if proposal is not None else "next_proposal"

    if proposal is not None:
        as_of = proposal.proposed_on_day
        seen = [fact for fact in facts if fact.decided_at <= proposal.proposed_at]
    else:
        as_of = today
        seen = list(facts)
    counted_from = resolve_live_threshold(seen, as_of).effective_from_day
    window_start = as_of - timedelta(days=FIXED_RULE_WINDOW_DAYS - 1)
    cited = frozenset(proposal.cited_evidence_ids) if proposal is not None else frozenset()

    led_to_proposal: dict[str, str] = {}
    for item in sorted(proposals, key=lambda row: (row.proposed_at, row.proposal_id)):
        for review_id in item.trigger_review_ids:
            led_to_proposal.setdefault(review_id, item.proposal_id)
    proposal_by_id = {item.proposal_id: item for item in proposals}
    changed_timing = frozenset(fact.decision_id for fact in facts if _fact_changed_timing(fact))
    # Per review: the earliest decision that changed review timing, else the earliest decision.
    # A rejection feeds the same reviews into the next proposal of its round, so a review can reach
    # a rejection first and the approval of the retry later; the change is what it led to.
    led_to_decision: dict[str, str] = {}
    led_to_change: set[str] = set()
    for decision in sorted(decisions, key=lambda row: (row.decided_at, row.decision_id)):
        decided_proposal = proposal_by_id.get(decision.proposal_id)
        if decided_proposal is not None:
            review_ids: tuple[str, ...] = decided_proposal.trigger_review_ids
        elif decision.trigger_review_id is not None:
            review_ids = (decision.trigger_review_id,)
        else:
            review_ids = ()
        is_change = decision.decision_id in changed_timing
        for review_id in review_ids:
            if review_id in led_to_change:
                continue
            if is_change:
                led_to_decision[review_id] = decision.decision_id
                led_to_change.add(review_id)
            else:
                led_to_decision.setdefault(review_id, decision.decision_id)

    entries: list[ReviewReceiptEntry] = []
    for review in sorted(reviews, key=lambda row: (row.recorded_at, row.review_id), reverse=True):
        status, exclusion = _receipt_standing(
            review,
            proposed_at=proposal.proposed_at if proposal is not None else None,
            counted_from=counted_from,
            window_start=window_start,
            as_of=as_of,
        )
        entries.append(
            ReviewReceiptEntry(
                review_id=review.review_id,
                case_id=review.case_id,
                opened_day=review.opened_day,
                recorded_at=review.recorded_at,
                lesson=review.lesson,
                status=status,
                exclusion=exclusion,
                cited=review.review_id in cited,
                led_to_proposal_id=led_to_proposal.get(review.review_id),
                led_to_decision_id=led_to_decision.get(review.review_id),
            )
        )
    return ReviewSettingReceipt(
        subject=subject,
        proposal_id=proposal.proposal_id if proposal is not None else None,
        as_of_day=as_of,
        counted_from_day=counted_from,
        window_start_day=window_start,
        needed=FIXED_RULE_FALSE_ALARMS,
        counted=sum(
            1 for entry in entries if entry.status == ReviewReceiptStatus.COUNTED_TOWARD_LOOSENING
        ),
        entries=entries,
        rule=RECEIPT_RULE,
    )


def _fact_changed_timing(fact: ThresholdDecisionFact) -> bool:
    """An approval or a put-back with the value it moved to: a decision that changed review timing.
    A rejection records the value it turned down, which never applied."""
    return (
        fact.kind in (ReviewThresholdDecisionKind.APPROVED, ReviewThresholdDecisionKind.REVERTED)
        and fact.after is not None
    )


def _latest(candidates: Iterable[ReceiptProposal]) -> ReceiptProposal | None:
    return max(candidates, key=lambda row: (row.proposed_at, row.proposal_id), default=None)


def _counting_proposal_for_approval(
    proposals: Sequence[ReceiptProposal],
    facts: Sequence[ThresholdDecisionFact],
    approval_id: str | None,
) -> ReceiptProposal | None:
    """The stored proposal behind `approval_id`, if it is one reviews counted toward."""
    proposal_id = next(
        (fact.proposal_id for fact in facts if fact.decision_id == approval_id), None
    )
    proposal = _latest(item for item in proposals if item.proposal_id == proposal_id)
    return proposal if proposal is not None and proposal.counts_toward_loosening else None


def _receipt_standing(
    review: ReceiptReview,
    *,
    proposed_at: datetime | None,
    counted_from: date | None,
    window_start: date,
    as_of: date,
) -> tuple[ReviewReceiptStatus, ReviewReceiptExclusion | None]:
    excluded = ReviewReceiptStatus.EXCLUDED
    if proposed_at is not None and review.recorded_at > proposed_at:
        return excluded, ReviewReceiptExclusion.AFTER_PROPOSAL
    if review.lesson.reason != ReviewLessonReason.NOT_A_CONCERN:
        if review.lesson.reason == ReviewLessonReason.REACHED_TOO_LATE:
            return ReviewReceiptStatus.ASKED_SOONER, None
        return excluded, ReviewReceiptExclusion.NOT_ELIGIBLE_TO_LOOSEN
    if review.opened_day is None:
        return excluded, ReviewReceiptExclusion.NO_OPENING_DAY
    if counted_from is not None and review.opened_day < counted_from:
        return excluded, ReviewReceiptExclusion.BEFORE_CURRENT_SETTING
    if not window_start <= review.opened_day <= as_of:
        return excluded, ReviewReceiptExclusion.OUTSIDE_WINDOW
    return ReviewReceiptStatus.COUNTED_TOWARD_LOOSENING, None


def tally_context_gaps(lessons: Sequence[ReviewLesson]) -> ContextGapTally:
    """Count the lessons that record a context gap, by category.

    Categories appear in `ContextGapCategory` order with a non-zero count only; known-context
    reviews recorded without a category are counted last under `category=None`.
    """
    gaps = [lesson for lesson in lessons if lesson.kind == ReviewLessonKind.RECORDS_CONTEXT_GAP]
    counts = Counter(lesson.context_gap_category for lesson in gaps)
    ordered: list[ContextGapCategory | None] = [*ContextGapCategory, None]
    return ContextGapTally(
        total=len(gaps),
        by_category=[
            ContextGapCount(category=category, count=counts[category])
            for category in ordered
            if counts[category]
        ],
        disclosure=CONTEXT_GAP_DISCLOSURE,
    )
