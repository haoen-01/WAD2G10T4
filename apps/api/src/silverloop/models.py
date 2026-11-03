from __future__ import annotations

from datetime import date, datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from silverloop.ontology import ActivityFamily, ActivityType, Format


class AuthRole(StrEnum):
    SENIOR = "senior"
    COORDINATOR = "coordinator"
    DEMO_OPERATOR = "demo_operator"
    FAMILY = "family"


class CurrentUser(BaseModel):
    sub: str
    role: AuthRole
    person_id: str | None = None


class AttentionBand(StrEnum):
    STABLE = "stable"
    WATCH = "watch"
    REVIEW = "review"


class Decision(StrEnum):
    NO_ACTION = "no_action"
    GENTLE_NUDGE = "gentle_nudge"
    PROGRAMME_SUGGESTION = "programme_suggestion"
    COORDINATOR_REVIEW = "coordinator_review"
    SUPPRESS = "suppress"


class PolicyGate(StrEnum):
    """Which rung of `policy.decide`'s ladder produced the decision.

    A report, never an interpretation. The ladder returns at the first guard clause that matches,
    and this names that clause -- so `SUPPRESS` appears under two gates (the weekly contact cap
    and the accepted-outreach cooldown, which share a rung, a decision and a support priority) and
    `NO_ACTION` under six. Without it, every consumer wanting to caption a decision had to
    reconstruct the ladder from `PersonState` and drifted: the evaluator surface captioned a
    cooldown suppression as "Weekly contact cap reached", which is factually wrong for the person
    who was left alone precisely because they had just taken a suggestion up.

    Adding this changed no decision. `decide` returns exactly what it returned before, with one
    more field describing the return it already made.
    """

    CONSENT = "consent"
    DATA_QUALITY = "data_quality"
    CONFIDENCE = "confidence"
    STATED_EXPLANATION = "stated_explanation"
    RAIN_CONTEXT = "rain_context"
    SMALL_BASELINE = "small_baseline"
    SEVERITY_PERSISTENCE = "severity_persistence"
    # The two rungs the review-threshold calibrator adds after `SEVERITY_PERSISTENCE` (ADR 0008).
    # Both return `COORDINATOR_REVIEW`, and under the starting setting neither is reachable: the
    # absolute floor sits inside the default threshold, and the shadow check runs only for a person
    # whose own setting is looser than the default.
    REVIEW_FLOOR = "review_floor"
    SHADOW_CHECK = "shadow_check"
    CONTACT_CAP = "contact_cap"
    ACCEPTED_COOLDOWN = "accepted_cooldown"
    WITHIN_RANGE = "within_range"


class CaseStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class CaseResolution(StrEnum):
    """Why a review case ended. Set once, at the moment it closes, and never inferred.

    A case has exactly three endings and nothing else may close one: the person's activity came
    back, they withdrew consent, or a coordinator answered the question the case was asking. The
    reason used to live only in the prose of a `CaseReviewRow.note` written by `reviewer="system"`,
    which meant anything wanting to act on it had to string-match an English sentence -- and a
    coordinator reading the card saw "Resolved" with no reason attached at all.
    """

    RECOVERED = "recovered"
    CONSENT_WITHDRAWN = "consent_withdrawn"
    COORDINATOR_DECISION = "coordinator_decision"


class HumanAction(StrEnum):
    """What the coordinator decided to do about Care+'s recommendation.

    Three values, not a menu of care actions: the case card asks one question -- do you agree with
    what this system suggested? -- and this answers it. `HOLD` is deliberately distinct from both:
    "I am not acting on this yet" is neither agreement nor disagreement, and collapsing it into
    either would overstate how often a human endorsed or overruled the system.

    Nothing on the activity learning or ranking path reads this. One combination is read: a
    resolved `OVERRIDE` with a false-alarm `OverrideReason` is what the review-threshold calibrator
    counts, and it may only *propose* a per-person review threshold change for a coordinator to
    approve -- see ADR 0008 (`docs/adr/0008-coordinator-calibrated-review-threshold.md`).
    """

    AGREE = "agree"
    HOLD = "hold"
    OVERRIDE = "override"


class OverrideReason(StrEnum):
    """Why a coordinator did not do what Care+ suggested.

    A closed vocabulary rather than free text, because the point of recording it is to be able to
    count it: "the system keeps flagging people whose trackers are unreliable" is a finding, and
    fifty distinct sentences saying that are not. The optional note beside it carries the detail
    and stays on the review row -- it never reaches the operator-readable audit trail, which
    records only that a note exists.
    """

    KNOWN_CONTEXT = "known_context"
    DATA_DOUBT = "data_doubt"
    RECENT_CONTACT = "recent_contact"
    OTHER = "other"
    # "This pattern is ordinary for this person." The only structured reason that can unlock a
    # proposal to loosen their review threshold (ADR 0008) -- never inferred from the note.
    NOT_A_CONCERN = "not_a_concern"


# ── The review-threshold calibrator (ADR 0008) ────────────────────────────────────────────────
#
# A coordinator's structured false-alarm judgement may tune, per person and inside fixed bounds,
# the point at which Care+ asks a human. Never the baseline, never any other gate. The enums
# live here beside `OverrideReason` because they are part of the same review contract; the pure
# rules live in `review_threshold.py`, which imports these and is never imported back.


class ReviewThresholdCause(StrEnum):
    """Why a false alarm happened. Only `TOO_TIGHT_FOR_PERSON` can justify loosening; the other
    three are expected to end in no change."""

    TOO_TIGHT_FOR_PERSON = "too_tight_for_person"
    ONE_OFF_EVENT = "one_off_event"
    BAD_DATA = "bad_data"
    WORKED_AS_INTENDED = "worked_as_intended"


class ReviewThresholdProposer(StrEnum):
    AGENT = "agent"
    FIXED_RULE = "fixed_rule"
    COORDINATOR = "coordinator"
    STARTING_SETTING = "starting_setting"


class ReviewThresholdOutputKind(StrEnum):
    PROPOSAL = "proposal"
    NO_CHANGE = "no_change"
    WRITE_UP = "write_up"


class ReviewThresholdDecisionKind(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REVERTED = "reverted"
    EXPIRED = "expired"
    RECONFIRMED = "reconfirmed"
    CHECK_CONFIRMED = "check_confirmed"
    CHECK_UNRESOLVED = "check_unresolved"


class ReviewThresholdRevertTrigger(StrEnum):
    SHADOW_CHECK = "shadow_check"
    REACHED_TOO_LATE = "reached_too_late"
    FAR_MORE_SEVERE = "far_more_severe"


class ReviewThresholdRejectionReason(StrEnum):
    """Why a proposal was not approved.

    `CONSENT_WITHDRAWN` and `SUPERSEDED` are written only by the system -- the first when a person
    withdraws consent mid-round, the second when a revert or expiry changed the value a proposal
    was made against -- and a coordinator request carrying either is refused. Neither counts as a
    coordinator's rejection: not toward a round, and not as a value that may not be proposed again.
    """

    CAUSE_DISPUTED = "cause_disputed"
    NEED_MORE_EVIDENCE = "need_more_evidence"
    PREFER_OTHER_CHANGE = "prefer_other_change"
    OTHER = "other"
    CONSENT_WITHDRAWN = "consent_withdrawn"
    SUPERSEDED = "superseded"


class ReviewThresholdNoticeKind(StrEnum):
    """Which way the senior-facing notice points: Care+ now waits a little `LATER`, or lets
    the care team know a little `SOONER` again."""

    LATER = "later"
    SOONER = "sooner"


# ── Calibration trust: what each review teaches (docs/calibration-trust-spec.md) ──────────────
#
# A coordinator's action is not ground truth. `ContextGapCategory` is what a review stored about
# known context; the lesson read from it went with the review route in step 7. Nothing in
# `policy.py`, `review_threshold.py` or `agent/` reads it.


class ContextGapCategory(StrEnum):
    """What kind of known context explained a review, when a coordinator chose to say.

    Optional, and allowed only beside an `OVERRIDE` for `KNOWN_CONTEXT`. It is tallied per person so
    a care team can see which context Care+ keeps missing; it never changes a decision, a
    proposal or a review setting. `ALREADY_IN_TOUCH` (in touch through another service or family)
    is deliberately distinct from `OverrideReason.RECENT_CONTACT`, which is outreach the care team
    already made.
    """

    AWAY = "away"
    ALREADY_IN_TOUCH = "already_in_touch"
    RESTING_OR_RECOVERING = "resting_or_recovering"
    OTHER_KNOWN = "other_known"


class TraceStatus(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    PENDING = "pending"
    NOT_APPLICABLE = "not_applicable"


class OutcomeKind(StrEnum):
    """How a person responded to one piece of outreach.

    `ACCEPTED` means only "show me more" -- it is consent to continue, not evidence that anything
    helped. What actually happened afterwards is `FollowThrough`, recorded separately, and the two
    must never be collapsed: a system that treats a tap as success is optimising engagement, which
    is the exact failure mode this product exists to avoid.

    `DEFERRED` and `NO_RESPONSE` are also deliberately distinct. "Maybe later" is an active reply
    from someone who read the message; `NO_RESPONSE` is silence. Filing the first as the second
    both overstates how many people ignore Care+ and, before this split, scored an explicit
    deferral as harshly as a refusal.
    """

    ACCEPTED = "accepted"
    DECLINED = "declined"
    DEFERRED = "deferred"
    NO_RESPONSE = "no_response"
    ACTIVITY_RECOVERED = "activity_recovered"
    COORDINATOR_RESOLVED = "coordinator_resolved"


class DeclineReason(StrEnum):
    """Optional, one-tap, always skippable context on a decline.

    `ALREADY_ACTIVE` is the valuable one: it is a person telling us the sensor is wrong, which is
    ground truth no wearable produces on its own and which feeds the data-quality assessment.
    """

    NOT_FOR_ME = "not_for_me"
    BAD_DAY = "bad_day"
    ALREADY_ACTIVE = "already_active"
    # Added with the dimensional learner. These four are the reasons that carry information
    # about a *kind* of activity rather than about one listing, and each maps to a
    # `PreferenceDimension`. `BAD_DAY` deliberately maps to nothing: "just not today" is not
    # evidence about the suggestion, and scoring it as though it were is the mistake this
    # expansion exists to stop.
    TOO_FAR = "too_far"
    TOO_TIRING = "too_tiring"
    BAD_TIMING = "bad_timing"
    PREFER_SOMETHING_ELSE = "prefer_something_else"


class FollowThrough(StrEnum):
    """What happened after someone accepted -- the signal `ACCEPTED` was standing in for.

    `UNABLE` is recorded as a poor fit for *this option*, never as a fact about the person. It
    ranks the candidate down so something else is offered next time; it is not a capability
    judgement, is never shown to a coordinator as one, and can never raise a decision rung.
    """

    COMPLETED = "completed"
    PARTIAL = "partial"
    NOT_THIS_TIME = "not_this_time"
    UNABLE = "unable"


class DailyMetric(BaseModel):
    day: date
    steps: int = Field(ge=0)
    active_minutes: int = Field(ge=0)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    wear_hours: float = Field(ge=0, le=24)
    source: str = "synthetic"


class ContextSignal(BaseModel):
    rainy: bool = False
    air_quality: str = "normal"
    holiday: bool = False
    note: str | None = None


class BaselineSummary(BaseModel):
    window_days: int
    median_steps: float
    mad_steps: float
    data_quality: float = Field(ge=0, le=1)
    # The anchored reference: the median over the EARLIEST valid days on record, as opposed to
    # `median_steps`, which is a rolling median over the most recent window.
    #
    # They exist separately because a rolling median has no memory. A person whose activity falls
    # and stays down drags their own baseline down with them, and within about a month the system
    # reports them as normal -- measured at day 17 for a 56% decline. The rolling median is still
    # the right instrument for "is today unusual for them lately"; the reference answers "is this
    # person living the life they were when we started", which is the question a rolling median
    # structurally cannot answer.
    #
    # Honest limitation: if observation began while the person was already declining, the
    # reference anchors to that. It is a reference, not a statement of health.
    reference_steps: float = 0
    reference_window_days: int = 0
    # The value the policy actually reasons about: the rolling median, floored so it cannot sit
    # more than a fixed fraction below the anchored reference. See `BASELINE_DRIFT_FLOOR`.
    #
    # `median_steps` stays the honest rolling number and is what the UI shows as "a typical day".
    # This is the one the ladder uses, because a baseline that has followed a person down is no
    # longer a description of them.
    effective_median_steps: float = 0


class DataQualityAssessment(BaseModel):
    evidence_id: str
    assessed_at: datetime
    source: str
    confidence: float = Field(ge=0, le=1)
    safe_to_interpret: bool
    reasons: list[str]
    device_suspected: bool = False
    device_suspected_reason: str | None = None
    # Set when the person has told us a day we read as quiet was not, either by disputing the day
    # or by declining with "already active". It is the only input to this assessment that does not
    # come from a sensor, so it is flagged separately rather than folded into `reasons`.
    self_reported_conflict: bool = False
    self_reported_conflict_note: str | None = None


class SignalSummary(BaseModel):
    current_steps: int
    delta_percent: float
    # Deviation from the anchored reference rather than the rolling baseline. Stays meaningful
    # after a sustained decline has been absorbed into `delta_percent`, which is exactly when the
    # person most needs someone to notice.
    reference_delta_percent: float = 0
    # `BaselineSummary.effective_median_steps`, carried here so `policy.decide` can tell a
    # genuinely tiny baseline from a large one without taking a second argument. A percentage
    # deviation from three steps a day is arithmetic, not evidence.
    baseline_median_steps: float = 0
    robust_z: float
    sustained_low_days: int
    confidence: float = Field(ge=0, le=1)
    context: ContextSignal
    quality: DataQualityAssessment


class StatedContextExplanation(BaseModel):
    """The person's own account of a quiet stretch, while it is still in force.

    Exposed as structured fields rather than left implicit in `rationale` because the web's
    Decision Audit panel captions the `stated_explanation` gate (`decided_by_gate`) from these
    fields, and is explicitly forbidden from string-matching the free-text rationale to do it (see
    `apps/web/lib/view-models.ts`).

    `explains_through` is a *simulated* day, like `stated_on` -- see `context_explanation.py` for
    why a wall-clock window would never expire in a demo.
    """

    value: str
    label: str
    rationale: str
    stated_on: date
    explains_through: date


class PersonState(BaseModel):
    person_id: str
    display_name: str
    preferred_language: str
    age: int | None = None
    context_note: str | None = None
    consent_active: bool
    current_day: date
    attention_band: AttentionBand
    baseline: BaselineSummary
    signal: SignalSummary
    last_decision: Decision
    rationale: list[str]
    # Which rung of the ladder produced `last_decision` -- see `PolicyGate`. Reported rather than
    # reconstructed: `rationale` is free text a consumer must never parse, and the pair
    # (decision, signal) is not enough to recover the gate, because the weekly contact cap and the
    # accepted-outreach cooldown share a rung and return an identical `SUPPRESS`.
    decided_by_gate: PolicyGate
    permitted_actions: list[Decision]
    # At most one, and only when the missing fact would change the decision. Never a queue.
    pending_question: ContextQuestion | None = None
    # At most one, and only when a sustained clamp plausibly means the person's life has changed.
    # See `BaselineConfirmationQuestion` and `baseline_confirmation.py`.
    pending_baseline_confirmation: BaselineConfirmationQuestion | None = None
    # Set only while the person's own explanation of a quiet stretch is still in force, and only
    # when it is an answer that explains anything -- "I would rather not say" never appears here.
    stated_explanation: StatedContextExplanation | None = None
    # Set for seven simulated days after this person's review threshold changed in a way the
    # senior should hear about (a loosening approved, or a revert/expiry back to sooner). Fixed
    # wording from `review_threshold.py`; no number, no internal vocabulary. See ADR 0008.
    review_threshold_notice: ReviewThresholdNotice | None = None


class Intervention(BaseModel):
    intervention_id: str
    person_id: str
    decision: Decision
    title: str
    message: str
    created_at: datetime
    status: str = "proposed"
    outcome: str | None = None
    # What happened after acceptance, once the person has told us. `None` covers both "not asked
    # yet" and "asked, chose not to say" -- the UI must not read silence here as a failure.
    follow_through: str | None = None
    # Whether it was any good, once they have said. Distinct from `follow_through`: someone can
    # attend something dutifully and not enjoy it, and ranking must be able to tell those apart.
    enjoyment: str | None = None
    # Already present inside `evidence`, lifted out because every consumer that groups or labels
    # outreach needs it and none of them should be parsing an untyped dict to get it.
    candidate_key: str | None = None
    # The first simulated day on which this offer, still unanswered, is recorded as silence
    # (`no_response`) by the response clock -- see `RESPONSE_WINDOW_DAYS` in `sql_repository.py`.
    # `None` once an outcome exists or the offer was withdrawn. A statement about when Care+
    # stops waiting, never a deadline shown to the person: the senior surface must not render it.
    awaiting_reply_until: date | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class ReviewAction(BaseModel):
    review_evidence_id: str
    status: CaseStatus
    reviewer: str
    note: str
    recorded_at: datetime
    # What Care+ suggested, as it read at the moment of this review -- a frozen copy, not a
    # reference to the live case, so a later refresh cannot retroactively change what the human
    # was looking at when they decided.
    agent_recommendation: str | None = None
    # What the human chose, and why they did not follow the suggestion. `None` on a review
    # recorded before the structured choice existed, and on the automatic closures the system
    # writes for itself (recovery, consent withdrawal) -- no human acted there, so claiming one
    # agreed would be a fabricated fact.
    human_action: HumanAction | None = None
    override_reason: OverrideReason | None = None
    # "This should have reached me sooner." `None` on reviews recorded before the question existed
    # and on system closures, for the same reason `human_action` is: nobody was asked.
    reached_too_late: bool | None = None
    # What kind of known context explained the review, when the coordinator said. Only ever set
    # beside an override for `known_context`.
    context_gap_category: ContextGapCategory | None = None


class PriorOutreach(BaseModel):
    """One thing Care+ already did about this concern, before it asked for a human.

    The case card could not answer "what have you tried?" at all: the day-one nudge and day-two
    suggestion lived on a separate per-person card that defaulted to one persona regardless of
    whose case was on screen, so a coordinator read "activity is 56% below across 4 days" with no
    idea whether anything had been offered or whether the person had replied.

    `outcome` and `follow_through` are the same enums the outreach history uses, and `None` means
    "nothing recorded" -- never "no" and never "ignored". A tap is not success and silence is not
    refusal; both distinctions are already load-bearing elsewhere and must not be flattened here.
    """

    intervention_id: str
    decision: Decision
    title: str
    day: date
    outcome: str | None = None
    follow_through: str | None = None


class ReviewCase(BaseModel):
    case_id: str
    person_id: str
    title: str
    status: CaseStatus
    priority: int = Field(ge=1, le=5)
    opened_at: datetime
    summary: str
    evidence: list[str]
    recommendation: str
    reviewer_note: str | None = None
    decision_evidence_id: str
    consent_active: bool
    action_history: list[ReviewAction]
    # ── The case clock ────────────────────────────────────────────────────────────────────────
    # Counted in simulated days, the same clock the response window uses. Wall time says nothing
    # here: nothing advances except `POST /v1/simulation/advance`, so a case "three days old" by
    # the calendar may have seen no new reading at all. `opened_at` above stays as it was -- it
    # records when the row was written, which is a different (and much less useful) fact.
    #
    # `None` only for a case opened before this clock existed; every case the current code creates
    # stores its opening day.
    opened_day: date | None = None
    # Inclusive: the day a case opens is day one of its review, because a coordinator reading
    # "0 days" about a case on their screen right now would be reading a falsehood. Counted to the
    # latest day that refreshed the case, not to today -- a case nothing has re-confirmed has not
    # quietly aged.
    days_in_review: int | None = None
    # When Care+ will put this back in front of a human if it is still open. `None` once the
    # case is closed, and never shown to a senior: this is a promise Care+ makes to the care
    # team about its own queue, not a deadline anyone is being held to.
    review_by_day: date | None = None
    # The most recent human (or `system`) action on the case, lifted out of `action_history` so a
    # card can show "who, when" without the caller re-deriving it. `None` until someone acts.
    last_reviewed_at: datetime | None = None
    reviewer: str | None = None
    # Why it closed. `None` while it is open or acknowledged -- acknowledging is not an ending.
    resolution: CaseResolution | None = None
    # ── What Care+ already did ───────────────────────────────────────────────────────────
    # Every piece of outreach in this run up to and including the day the case opened, oldest
    # first. Derived on read from rows that already exist; nothing new is stored.
    prior_outreach: list[PriorOutreach] = Field(default_factory=list)
    # Why this needed a person, in one sentence, authored from two facts the case already has:
    # which rung of the ladder stopped, and what was tried before it. A deterministic template in
    # `sql_repository._why_human`, never model-written -- an LLM-authored case summary would mean
    # a reviewer could no longer be sure they were reading policy output rather than a model's
    # paraphrase of it, on the one surface where that certainty matters most.
    why_human: str = ""


class Programme(BaseModel):
    programme_id: str
    name: str
    venue: str
    distance_km: float
    next_session: datetime
    accessibility: list[str]
    evidence_source: str = "synthetic fixture"


class AuditEvent(BaseModel):
    event_id: str
    at: datetime
    event_type: str
    actor: str
    person_id: str | None = None
    decision: Decision | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class AdvanceRequest(BaseModel):
    event: str = Field(
        default="activity_declines",
        description=(
            "activity_declines, rain_explains_decline, rain_clears_activity_low, recovery, "
            "low_wear, consent_revoked, public_holiday, programme_becomes_full, or "
            "weather_turns"
        ),
    )
    event_id: str | None = Field(
        default=None,
        min_length=4,
        max_length=96,
        description="Optional client idempotency key scoped to the active scenario run.",
    )
    person_id: str | None = Field(
        default=None,
        max_length=64,
        description="Optional target person. Defaults to the demo person when omitted.",
    )


class AdvanceResponse(BaseModel):
    state: PersonState
    created_intervention: Intervention | None = None
    created_case: ReviewCase | None = None
    audit_event: AuditEvent
    loop_trace: list[DecisionTraceStep]


class DecisionTraceStep(BaseModel):
    order: int = Field(ge=1)
    stage: str
    status: TraceStatus
    title: str
    detail: str
    evidence_id: str | None = None


class OutcomeRequest(BaseModel):
    outcome: OutcomeKind = Field(
        description=(
            "accepted, declined, deferred, no_response, or activity_recovered. `accepted` means "
            "the person asked to see more -- report what they actually did via the follow-through "
            "route, not here."
        )
    )
    reason: DeclineReason | None = Field(
        default=None,
        description=(
            "Optional context, only meaningful alongside `declined`. Always skippable; never "
            "required to submit a response."
        ),
    )


class OutcomeResponse(BaseModel):
    intervention: Intervention
    outcome_evidence_id: str
    outcome: OutcomeKind
    preference_before: float
    preference_after: float
    candidate_key: str
    audit_event: AuditEvent


# ── The follow-through loop ───────────────────────────────────────────────────────────────────
#
# Everything below exists because outreach used to end at the sentence. A person tapped "Yes,
# tell me more", was told nothing more, and the tap was recorded as a success. These models cover
# the three beats that were missing: showing the thing that was offered, asking later whether it
# happened, and looking at the days afterwards to see whether anything changed.


class FollowUpObservation(BaseModel):
    """What the person's activity did in the days after one piece of outreach.

    This is the question the product could not previously answer -- "does reaching out change
    anything?" -- and the data to answer it was already on disk, unread.

    It is deliberately not a claim of cause. One person over a few days cannot establish that a
    suggestion did anything, and `caveat` says so on every single observation rather than in a
    footnote somewhere. Causal comparison belongs to the evaluation harness, across many people;
    this is a description of one person's week and is labelled as one.
    """

    intervention_id: str
    # False while the observation window is still open or has too few valid-wear days. Every
    # numeric field below is meaningless when this is False, and consumers must check it.
    available: bool
    reason_unavailable: str | None = None
    observed_from: date | None = None
    observed_to: date | None = None
    days_observed: int = 0
    valid_days_observed: int = 0
    steps_before: float = 0
    steps_after: float = 0
    change_percent: float = 0
    reference_steps: float = 0
    # Moved back toward the person's own anchored reference, not toward any population target.
    returned_toward_usual: bool = False
    interpretation: str = ""
    caveat: str = ""


class CandidatePreference(BaseModel):
    """A durable, person-owned preference about one kind of suggestion.

    Suppression here is deterministic and separate from the Beta-Bernoulli learner: repeated
    declines remove an option from the permitted set rather than merely ranking it lower. Keeping
    it out of the learner preserves the invariant that learning only ever reorders what policy
    already allowed -- this narrows the set, and narrowing is a safety-preserving direction.

    The person can always reverse it, which is why `suppressed` is writable by the senior and by
    nobody else.
    """

    candidate_key: str
    label: str
    suppressed: bool = False
    suppressed_reason: str | None = None
    declines: int = 0
    times_offered: int = 0
    times_accepted: int = 0
    times_completed: int = 0


class ConsentRequest(BaseModel):
    active: bool
    reason: str = Field(min_length=2, max_length=240)


class ConsentResponse(BaseModel):
    consent_active: bool
    consent_evidence_id: str
    withdrawn_intervention_ids: list[str]
    audit_event: AuditEvent


# ── The review-threshold calibrator: contract (ADR 0008) ──────────────────────────────────────
#
# The bounds below are repeated as literals because this module must never import
# `review_threshold.py` (which imports it). `review_threshold.py` owns the constants; its tests pin
# that these field bounds agree with them.


class ReviewThresholdValue(BaseModel):
    """One point on the allowed grid: review when activity is at least `severity_pct` below the
    personal baseline for at least `persistence_days` valid-wear days.

    Fourteen points: 40..55% in steps of 5 for 3..5 days, plus 30% and 35% at three days only.
    Persistence cannot go below three days, so asking sooner is severity-only, and the "mixed"
    values (30%/35% for four or five days) are refused: every allowed setting stays componentwise
    comparable with the starting setting, so going back can never ask later in either dimension.
    """

    severity_pct: int = Field(ge=30, le=55, multiple_of=5)
    persistence_days: int = Field(ge=3, le=5)

    @model_validator(mode="after")
    def _no_mixed_settings(self) -> ReviewThresholdValue:
        if self.severity_pct < 40 and self.persistence_days != 3:
            raise ValueError(
                "below 40% a review setting must stay at three days (no mixed settings)"
            )
        return self


class ReviewThresholdFloor(BaseModel):
    """The absolute review floor (60% for three days). Not a point on the allowed grid -- no one
    can choose it -- so it is deliberately a separate shape from `ReviewThresholdValue`, whose
    range validation it would fail."""

    severity_pct: int
    persistence_days: int


class ReviewThresholdBounds(BaseModel):
    default: ReviewThresholdValue
    minimum: ReviewThresholdValue
    maximum: ReviewThresholdValue
    floor: ReviewThresholdFloor
    severity_step_pct: int
    persistence_step_days: int
    grace_days: int
    checking_period_days: int
    expiry_days: int
    cooldown_days: int
    weekly_proposal_cap: int
    proposals_per_round: int


class ReviewThresholdNotice(BaseModel):
    """What the senior is told, in fixed wording, after their review threshold changed."""

    notice_id: str
    kind: ReviewThresholdNoticeKind
    message: str
    shown_from_day: date


class ReviewThresholdReplayEpisode(BaseModel):
    first_low_day: date
    # True for the trailing episode that has not recovered by the last stored day. Its `None`
    # review days mean "not yet", never "recovered before asking".
    ongoing: bool = False
    current_review_day: date | None = None
    # `None` on a finished episode when it recovered before the candidate (or its floor/shadow
    # check) asked; on an ongoing episode, only that the candidate has not asked yet.
    candidate_review_day: date | None = None
    # Candidate minus current, in days; negative means sooner.
    days_later: int | None = None
    candidate_reached_via: Literal["threshold", "floor", "shadow_check"] | None = None


class ReviewThresholdReplay(BaseModel):
    """Calculated by code from stored synthetic history; never written by a model.

    `episodes` lists every episode in the window in which either setting asked, the trailing
    unfinished one included (`ongoing=True`). `reviews_with_current` and `reviews_with_candidate`
    count **finished episodes only**: an ongoing episode's missing review is "not yet", so it can
    never be read as a review the candidate would have saved. `max_days_later` likewise reads
    finished episodes only.
    """

    current: ReviewThresholdValue
    candidate: ReviewThresholdValue
    window_start_day: date
    window_end_day: date
    episodes: list[ReviewThresholdReplayEpisode] = Field(default_factory=list)
    reviews_with_current: int = Field(ge=0)
    reviews_with_candidate: int = Field(ge=0)
    max_days_later: int | None = None
    disclosure: str


class ServerErrorCode(StrEnum):
    """How a server-side failure is classified (`error_responses.py`)."""

    # A stored snapshot predates the current contract; resetting the demo recovers.
    STORED_STATE_INCOMPATIBLE = "stored_state_incompatible"
    # Any other server-side failure the API classifies rather than exposing framework text.
    INTERNAL_ERROR = "internal_error"


class ServerErrorBody(BaseModel):
    """The body of every classified 500. `detail` repeats `message` for clients that read
    `detail`, the FastAPI convention the rest of the API follows. Plain language only: no field
    path, stored value or framework text."""

    code: ServerErrorCode
    message: str
    detail: str


class HealthResponse(BaseModel):
    status: str
    version: str
    mode: str
    llm_enabled: bool


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database_backend: str
    runtime_profile: Literal["shared", "offline"]
    database_connected: bool
    migration_revision: str | None
    expected_migration_revision: str
    tables_without_rls: list[str] = Field(
        default_factory=list,
        description=(
            "Public ORM tables whose PostgreSQL row-level security is off. The browser never "
            "reaches these tables directly -- `anon` and `authenticated` are denied by policy -- "
            "and a table with RLS disabled has lost that denial, so any name here makes `status` "
            "`not_ready`. Always empty off PostgreSQL: SQLite has no such flag to report on, and "
            "no Data API to be exposed to."
        ),
    )


class DemoResetResponse(BaseModel):
    state: PersonState
    seed: int
    scenario_version: str
    fixture_checksum: str


# ── The user-initiated loop ───────────────────────────────────────────────────────────────────
#
# Everything above this line begins with a policy trigger: the wearable changed, the ladder
# decided. These models are the second entry point, where the senior starts the loop themselves.
#
# "Find me something to do tomorrow" is not a behavioural anomaly and must never be modelled as
# one. It reaches the same planner, the same permitted-set guardrail and the same learner, but it
# does not require -- and does not create -- a wellbeing concern.


class TimeWindow(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    ANY = "any"


class SocialPreference(StrEnum):
    SOCIAL = "social"
    SOLO = "solo"
    EITHER = "either"


class ActivityEnvironment(StrEnum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    SHELTERED = "sheltered"
    EITHER = "either"


class ActivityIntensity(StrEnum):
    LIGHT = "light"
    MODERATE = "moderate"
    EITHER = "either"


class IndoorOutdoor(StrEnum):
    """What a *listing* says about its surroundings, as opposed to what a *request* asks for.

    Deliberately not `ActivityEnvironment`: a request may say "either", which a listing cannot,
    and a listing may say "unknown", which a request cannot. `activity_search`'s
    `_ENVIRONMENT_COMPATIBLE` is the one bridge between them. Declared here, above
    `ActivityIntent`, because an intent's `excluded_environments` is a list of things the
    *catalogue* can be, not of things a request can ask for.
    """

    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    SHELTERED = "sheltered"
    UNKNOWN = "unknown"


class IntentParser(StrEnum):
    """Which of the two parsers produced an intent.

    They exist as a pair because the offline profile forbids the planner (`runtime.py`), and the
    demo has to survive a dead network. `CHIPS` and `KEYWORD` are deterministic and always
    available; `LLM` is better at real sentences and only runs when the planner is live. All three
    emit the same `ActivityIntent`, so nothing downstream can tell them apart or needs to.
    """

    CHIPS = "chips"
    KEYWORD = "keyword"
    LLM = "llm"


class ActivityIntent(BaseModel):
    """A request for something to do, as structure rather than as a sentence.

    The model's entire job is to fill this in. It never answers the request, never names an
    activity and never invents a constraint the person did not express -- which is why every
    field defaults to "no preference" rather than to a plausible guess.

    `unparsed_terms` is the honesty valve. Anything the parser did not understand is carried here
    and shown back to the person, so a misread request is visible before it is acted on rather
    than silently narrowing the search.
    """

    # Bounded at the schema, not only at the request: the LLM parser fills this model too, and a
    # field with no ceiling is a field an adversarial request can use to stuff the next prompt.
    raw_text: str | None = Field(default=None, max_length=400)
    on_date: date | None = None
    time_window: TimeWindow = TimeWindow.ANY
    max_distance_m: int | None = Field(default=None, ge=0, le=50_000)
    # Whether the person gave a distance as a *number*. "Within 800 m" is a limit they know they
    # have; "near me" is a preference. Only the first is a barrier, so only the first filters --
    # a vague phrase read as a hard 1 km cut-off silently removed half the catalogue, including
    # the 1.2 km sheltered walk, from someone who had not asked for anything of the sort.
    distance_is_explicit: bool = False
    social_preference: SocialPreference = SocialPreference.EITHER
    environment: ActivityEnvironment = ActivityEnvironment.EITHER
    intensity: ActivityIntensity = ActivityIntensity.EITHER
    language: str | None = Field(default=None, max_length=40)
    # What kind of thing they asked for. A *soft* axis: it ranks, it never filters. The catalogue
    # is small, so a hard content filter would turn most requests into "nothing matched" -- the
    # honest failure here is showing a walk below the tai chi they asked for, never hiding it.
    activity_types: list[ActivityType] = Field(default_factory=list, max_length=5)
    # What they ruled out. All three are *hard*, and all three exist because of negation: a
    # sentence like "nothing outdoors today" or "no walking, my knee" used to be read as its own
    # opposite and then hard-filtered to it. An exclusion cannot on its own empty the catalogue,
    # and showing someone the one thing they said they could not do is the harmful error here.
    excluded_activity_types: list[ActivityType] = Field(default_factory=list, max_length=5)
    excluded_environments: list[IndoorOutdoor] = Field(default_factory=list, max_length=3)
    excluded_social: list[SocialPreference] = Field(default_factory=list, max_length=2)
    # Set by the server from the parser that actually ran; a client-supplied value is overwritten.
    parsed_by: IntentParser = IntentParser.CHIPS
    unparsed_terms: list[Annotated[str, Field(max_length=40)]] = Field(
        default_factory=list, max_length=20
    )


class ActivitySource(StrEnum):
    """Where a listing came from. Never decorative.

    Only `AAC_FIXTURE` carries real data in this build. The others exist so the adapter shape is
    visible in the contract, and a candidate may not claim one of them until that integration
    actually retrieved it -- see `integration_status`.
    """

    AAC_FIXTURE = "aac_fixture"
    ONEPA = "onepa"
    ACTIVESG = "activesg"
    HEALTHY365_HANDOFF = "healthy365_handoff"


class IntegrationStatus(StrEnum):
    FIXTURE = "fixture"
    FUTURE_AUTHORISED = "future_authorised"
    LIVE = "live"


class ActivityAvailability(StrEnum):
    AVAILABLE = "available"
    FULL = "full"
    UNKNOWN = "unknown"


class ActivityLocation(BaseModel):
    name: str
    address: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class DistanceBasis(StrEnum):
    """Where a candidate's `distance_m` came from, so a card never implies a measurement it
    does not have.

    `LISTING_STATIC` is the only basis in this build: a fixed figure typed into the listing with
    no origin and no route behind it. A future routing adapter (walk or public transport from a
    place the person chose to share) would add its own member here rather than reuse this one.
    `UNKNOWN` accompanies a `None` distance.
    """

    LISTING_STATIC = "listing_static"
    UNKNOWN = "unknown"


class ActivityBooking(StrEnum):
    """Whether a person can simply turn up, and if not, what they must do first.

    `UNKNOWN` is a real answer and must render as "Not listed". Telling someone to just turn up to
    something that needed booking wastes a journey they may have found difficult to make.
    """

    DROP_IN = "drop_in"
    REGISTER = "register"
    UNKNOWN = "unknown"


class ActivityCandidate(BaseModel):
    """One thing a person could actually go and do.

    The rule that governs this model: **the planner may rank candidates; it may never author
    one.** Every field here is retrieved, and `UNKNOWN` is a real answer that must render as "Not
    listed" rather than being filled in with something plausible. A fabricated language tag or an
    invented session time is the failure that would make the whole product untrustworthy, and it
    is invisible in a demo -- which is exactly why the schema, not the prompt, has to prevent it.

    `retrieved_at` and `source` travel with the candidate so a card can always say where its
    facts came from and how stale they are.
    """

    activity_id: str
    source: ActivitySource
    integration_status: IntegrationStatus
    title: str
    provider: str
    start_at: datetime | None = None
    location: ActivityLocation
    # The display badge, and only that. It reads as words ("Group class") because a card should,
    # and it is populated from `ontology.FORMAT_LABEL[format]` rather than typed per listing.
    # Nothing ranks, learns or diversifies on it any more: `format` and `activity_type` below
    # carry the two facts it used to conflate.
    category: str | None = None
    # What the thing *is*. `None` means the listing is not labelled, which is a different fact
    # from `ActivityType.OTHER` ("labelled, and none of the above") -- and neither is ever
    # guessed from the title in product code. Fixture listings carry hand-authored values and
    # `ontology.normalise` exists only to check them.
    activity_type: ActivityType | None = None
    activity_families: list[ActivityFamily] = Field(default_factory=list)
    # How it is run: a class, a led group activity, a drop-in, something self-guided, one to one.
    format: Format | None = None
    indoor_outdoor: IndoorOutdoor = IndoorOutdoor.UNKNOWN
    intensity: ActivityIntensity | None = None
    # Whether the activity actually puts someone among other people. `None` means the listing
    # does not say, and must render as "Not listed" -- a group session and an unlabelled one are
    # not the same thing, and guessing here would fabricate the single attribute most likely to
    # matter to someone who asked to meet people.
    social_shape: SocialPreference | None = None
    accessibility_tags: list[str] = Field(default_factory=list)
    language_tags: list[str] = Field(default_factory=list)
    capacity: int | None = None
    availability: ActivityAvailability = ActivityAvailability.UNKNOWN
    price: str | None = None
    source_url: str | None = None
    retrieved_at: datetime
    distance_m: int | None = None
    distance_basis: DistanceBasis = DistanceBasis.UNKNOWN
    # Everything below exists so a person can decide, and then actually go, from this one card.
    # Splitting "what is it", "how do I get there", "do I need to book" and "who do I call" across
    # separate places is exactly the cross-checking that stops someone attending -- and it falls
    # hardest on the people least able to chase it down.
    #
    # All optional, all `None`/empty when genuinely unknown, and all rendered as "Not listed"
    # rather than guessed. A fabricated bus number is worse than no bus number.
    description: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    what_to_bring: list[str] = Field(default_factory=list)
    booking: ActivityBooking = ActivityBooking.UNKNOWN
    booking_note: str | None = None
    contact_phone: str | None = None
    contact_note: str | None = None
    getting_there: list[str] = Field(default_factory=list)
    good_to_know: list[str] = Field(default_factory=list)


class ReasonBasis(StrEnum):
    """What a "why this fits you" line is grounded in. No line may exist without one."""

    INTENT = "intent"
    PREFERENCE = "preference"
    CONTEXT = "context"
    CATALOGUE = "catalogue"
    # The person's own recorded responses to this exact listing -- interested, went, enjoyed.
    HISTORY = "history"
    # Promoted by the diversity pass so the top three are not three of the same kind of thing.
    # The line says so plainly; it is never dressed up as a fit the evidence does not support.
    VARIETY = "variety"


class ActivityReason(BaseModel):
    text: str
    basis: ReasonBasis


class FilterOutcome(BaseModel):
    """A candidate the deterministic filter removed, and why.

    Kept and returned because the filter runs *before* the model sees anything, so this is the
    only record of what was excluded from its view. Without it, "the agent chose well" is
    unfalsifiable -- the interesting question is always what it never got to consider.
    """

    activity_id: str
    title: str
    rule: str
    detail: str


class ScoreFactor(BaseModel):
    """One named, bounded component of a candidate's deterministic rank.

    `value` is in [-1, 1] and `contribution = value * weight`. The names are fixed
    (`activity_search.RANKING_WEIGHTS`) so an evaluator can compare the same factor across
    candidates and searches; `note` says, in words, what the value was grounded in.
    """

    name: str
    value: float = Field(ge=-1, le=1)
    weight: float
    contribution: float
    note: str


class ScoreBreakdown(BaseModel):
    """Why the deterministic ranker put a candidate where it did -- for the evaluator, never the
    senior.

    A senior's card shows at most three grounded "why this fits you" lines; this is the fuller
    account behind the order, including the negatives (friction, a learned dislike, a recent
    "not for me") that a card never lists because they are not reasons something suits someone.
    Deliberately NOT a field of `RankedActivity`: that model travels to the senior client inside
    `ActivityQueryResponse`, and "the UI never renders it" is not a boundary -- the payload is.
    The breakdown reaches evaluators through the `activity_search` audit event's detail and the
    ranking evaluation artifact, both of which are operator surfaces.
    """

    factors: list[ScoreFactor]
    total: float
    # The primary sort key (`activity_search.sort_key_for`): how much of today's request this
    # listing can satisfy, less a recent "not for me" on it. Stated on its own because it is not
    # derivable from `factors` -- a listing that answers none of what was asked keeps the tier of
    # an unjudged fit while earning no intent credit.
    tier: float
    # True when the diversity pass moved this candidate into the top three because the three
    # above it were all the same kind of thing. The order is then not purely by `total`, and
    # this flag is what makes that honest.
    variety_promoted: bool = False
    # How many positive, grounded reason lines did not fit on the face of the three-line card:
    # always `len(RankedActivity.more_reasons)`, the lines the card shows when it is opened. The
    # name predates those lines being shown -- nothing counted here is hidden, and it is never a
    # negative. Non-zero means the face alone understates what the order rests on.
    reasons_suppressed: int = 0
    # True when a better-scoring session of the same programme already holds a top-three slot
    # and this one was moved below the top three so the person sees three different things.
    series_deferred: bool = False
    # How much of what is known about this person this listing could actually be judged on. A
    # sparsely described listing is scored on less; reporting that separately is what stops it
    # out-scoring a fully described identical one simply by being unanswerable.
    coverage: float = Field(default=0.0, ge=0, le=1)
    # How many axes -- asked-for and learned -- this listing genuinely matches. The tie-break at
    # equal total: UNKNOWN is out of both sides of every fit, so it is never a penalty, and this
    # is what stops it being free as well.
    matched_axes: int = Field(default=0, ge=0)


class RankedActivity(BaseModel):
    candidate: ActivityCandidate
    rank: int = Field(ge=1)
    # The face of the card: at most three, and each traceable to a stored field via its `basis`.
    reasons: list[ActivityReason] = Field(default_factory=list)
    # Every other grounded reason the ranker composed for this listing, shown when the card is
    # opened -- same rules as `reasons` (a line only for a factor that contributed positively),
    # in the same basis order. Empty whenever the face held everything; its length is the
    # breakdown's `reasons_suppressed`.
    more_reasons: list[ActivityReason] = Field(default_factory=list)
    selected_by: Literal["agent", "ranker"] = "ranker"
    # Which programme this session belongs to (`activity_search.series_key`), so a screen can fold
    # sessions of one programme into one card by the ranker's own definition of "the same
    # programme". Opaque; compare for equality only.
    series_key: str | None = None


class FactConfidence(StrEnum):
    """Qualitative on purpose. A number here would imply a precision the evidence behind most of
    these facts (one tap, three days) cannot support.

    Declared here, above the preference models, because a resolved preference and a world-model
    fact have to grade the same evidence on the same scale -- two vocabularies for "how sure are
    we" is how the ranker's number and the Privacy screen's wording came to mean different
    things about the very same row.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PreferenceDimension(StrEnum):
    """The axes a decline can teach, as opposed to the single candidate it was about.

    This is what makes "too far" different from "just not today". A per-candidate posterior can
    only ever say "not this one"; a dimension transfers to activities that have never been
    offered, which is the whole point of learning anything.

    Ranking only, exactly like the per-candidate learner: a dimension can reorder what the policy
    already permitted and can never permit, escalate or unblock anything.

    Two of these are *ordinal*: DISTANCE and INTENSITY carry a `pivot` and a `direction` rather
    than a value from a closed list, because "1.2 km was too far" is a statement about a ceiling
    and reading it as the nominal bucket the listing happened to fall in taught the opposite
    ("avoid things near home"). The rest are nominal.
    """

    DISTANCE = "distance"
    INTENSITY = "intensity"
    TIMING = "timing"
    SOCIAL = "social"
    ENVIRONMENT = "environment"
    # DEPRECATED, never written, never removed. `category` holds a *format* label ("Group class",
    # "Social group"), so a "not for me" on a morning walk taught a dislike of nine unrelated
    # programmes. `ACTIVITY_TYPE` is the content axis now. The member stays because rows written
    # before the split are still in the table and still have to be readable (and forgettable).
    CATEGORY = "category"
    # What the thing *is* (`ontology.ActivityType`), single-valued and closed, so a stated value
    # can be validated and a "not for me" teaches something a person would recognise.
    ACTIVITY_TYPE = "activity_type"


class ClarificationScope(StrEnum):
    """How far a decline reaches, when the person chose to say. Always optional, always skippable.

    Unclarified means item-level only: one "bad timing" is about the session in front of them,
    not about mornings in general, and one "not for me" is about that listing, not every walk --
    the 14-day cooldown already holds that listing back. Both are recorded (`THIS_SLOT`,
    `THIS_ONE`) and held back from the resolved set until a second answer agrees about a
    *different programme*: turning the same class down again, on another day or at another of its
    sessions, is still an answer about that class and widens nothing. A chip (`time_of_day`,
    `weekday`, `this_activity_type`) is the only thing that widens a single tap into a statement
    about a *kind* of activity before then. `this_one`, `this_venue` and `this_format` on a "not
    for me" teach no dimension at all.

    The ordinal reasons are the exception and take no chip: "too far" and "too tiring" record a
    ceiling at the listing's own distance or intensity, which applies at once and only narrows.
    """

    # `bad_timing`
    TIME_OF_DAY = "time_of_day"
    WEEKDAY = "weekday"
    THIS_SLOT = "this_slot"
    # `not_for_me`
    THIS_ACTIVITY_TYPE = "this_activity_type"
    THIS_FORMAT = "this_format"
    THIS_VENUE = "this_venue"
    THIS_ONE = "this_one"


class DimensionPreference(BaseModel):
    dimension: PreferenceDimension
    value: str
    # -1 strongly against, +1 strongly for. Small magnitudes are weak evidence and must read that
    # way wherever this is shown. Derived for a learned belief -- `(positive_evidence -
    # negative_evidence) / (positive_evidence + negative_evidence + 2)` -- and set outright for a
    # stated one, which is not evidence that accumulates but a person saying so.
    strength: float = Field(ge=-1, le=1)
    # `senior_statement` outranks `inferred`: something a person said in their own words is not
    # the same class of evidence as something derived from their taps, and the two must stay
    # distinguishable so a person can be shown, and can correct, what they told us.
    source: Literal["senior_statement", "decline_reason", "inferred"]
    confirmed: bool = False
    observations: int = 0
    updated_at: datetime
    # A temporary preference -- "no walks this week" -- is a fact until this moment and nothing
    # after. Readers treat an expired preference as absent; `None` means it does not expire.
    expires_at: datetime | None = None
    # The person's own words, when the preference came from them. Shown back verbatim on the
    # Privacy screen so what they agreed to is recoverable, never paraphrased.
    stated_text: str | None = None
    # When this belief was first recorded. `None` on beliefs recorded before the field existed;
    # never backfilled, because a guessed first date would be a fabricated one.
    first_observed_at: datetime | None = None
    # Evidence for and against, kept apart rather than folded into one scalar. One number could
    # not say whether 0.0 meant "nothing known" or "two things that disagree", so a like on one
    # axis silently cancelled an avoid on another and the card then read "nothing learned
    # applies". `strength` and `confidence` are both derived from these, and separately.
    positive_evidence: float = Field(default=0.0, ge=0)
    negative_evidence: float = Field(default=0.0, ge=0)
    # The ordinal half. `pivot` is the number the person's own answer put a line at -- metres for
    # DISTANCE, a rung on the intensity ladder for INTENSITY -- and `direction` says which side
    # of it they want. `None` on every nominal axis.
    pivot: float | None = None
    direction: Literal["lower", "higher"] | None = None
    # How far the answer reaches, when a clarification chip said. `None` means unclarified, which
    # is item-level: see `ClarificationScope`.
    scope: ClarificationScope | None = None
    # The single most recent thing this belief was folded from (a response id, a plan id, a
    # statement). Two folds of the same origin are one observation, not two.
    origin_id: str | None = None
    # Set when this belief has been retracted (`forget`) or consumed by a statement that ratified
    # it ("That's right"). A superseded row is never read, never rendered and never scored -- it
    # stays only so the audit trail is not rewritten. The next tap starts a fresh belief from
    # zero rather than resurrecting this one's count.
    superseded_by: str | None = None


class SourceTier(IntEnum):
    """How a belief came to be held, ordered. The higher tier wins an axis **outright**.

    Averaging a person's own words with what Care+ guessed from their taps is how three
    stated preferences came to be a constant offset that changed nothing, and how a guess could
    halve something someone said in plain words. Within one axis only the highest active tier
    contributes; across axes, contributions sum.

    `CURRENT_REQUEST` never enters preference utility at all. An axis the person constrained
    *today* belongs to the filter (if it is a hard ask) or to request fit (if it is soft), and
    scoring it a second time from history is the double count that made "indoor" worth four
    separate nudges.
    """

    DEFAULT = 0
    # One or two distinct origins. Shown as "just a hint"; capped well below a stated belief.
    WEAK_LEARNED = 1
    # Three or more agreeing origins.
    STRONG_LEARNED = 2
    # An `ActivityGoal`, which is a closed-vocabulary thing the person chose.
    STATED_GOAL = 3
    # `senior_statement`: the person's own standing words.
    STATED = 4
    # A statement that consumed an inferred row ("That's right"). One belief, not two.
    RATIFIED = 5
    # A statement with an `expires_on_day` still ahead: a promise about this week.
    TEMPORARY_STATED = 6
    # Today's `ActivityIntent`. Never scored as a preference -- see the class docstring.
    CURRENT_REQUEST = 7


class ResolvedPreference(BaseModel):
    """What the ranker actually reads: one active belief, with sentiment, confidence and evidence
    finally separate from one another.

    **Derived, never persisted.** Rebuilt per request from the rows that already exist, exactly
    like `PersonWorldModel` -- a read model cannot drift from its evidence, and a second store of
    the same belief is a second thing to keep true.

    `strength` says which way the belief leans and `confidence` how much sits behind it; one
    signed scalar used to carry both, so "nothing known" and "two things that disagree" were the
    same number. `weight` is the tier's own say, bounded to [0, 1] so the ADR 0005 argument that
    a social nudge cannot outvote a real acceptance stays structural rather than arithmetical.
    """

    dimension: PreferenceDimension
    # Nominal axes. On an ordinal axis this is the direction token the row is keyed by, and the
    # number that actually means something is `pivot`.
    value: str | None = None
    # The ordinal half: metres for DISTANCE, a rung on the intensity ladder for INTENSITY.
    pivot: float | None = None
    direction: Literal["lower", "higher"] | None = None
    sentiment: Literal["like", "avoid"]
    # Bounded, and the bound is load-bearing: `preferences.social_shape_score` is derived from it
    # and ADR 0005's tie-break bound rests on that derivation staying inside [-1, 1].
    strength: float = Field(ge=-1, le=1)
    confidence: FactConfidence
    positive_evidence: float = Field(default=0.0, ge=0)
    negative_evidence: float = Field(default=0.0, ge=0)
    # DISTINCT origins. A person saying the same thing three times is one piece of evidence.
    evidence_count: int = Field(default=0, ge=0)
    # This belief's own tier, and the highest tier active in its resolution group
    # (`preferences._resolution_group`): the whole axis on TIMING, ENVIRONMENT, SOCIAL and
    # INTENSITY; on DISTANCE, the lines with a pivot together, and the beliefs with no number in
    # two groups by which way they lean (near: "near" liked, "far" avoided, the `less_travel` goal;
    # far: the other two, never read); and the single (axis, value)
    # on ACTIVITY_TYPE (and deprecated CATEGORY), where one kind of activity says nothing about
    # another. A belief contributes to preference utility
    # only when the two are equal -- the supersedes-rather-than-average rule, stated as data
    # rather than buried in a scoring loop. Equal tiers on one value both win and, leaning
    # opposite ways, cancel.
    tier: SourceTier
    winning_tier: SourceTier
    weight: float = Field(default=0.0, ge=0, le=1)
    scope: ClarificationScope | None = None
    expires_on_day: date | None = None
    source: Literal["senior_statement", "decline_reason", "inferred"]
    run_id: str | None = None
    superseded_by: str | None = None
    stated_text: str | None = None
    # Keys of the rows behind this belief, and of the other active beliefs on the same
    # `(dimension, value)` that lean the other way: `dimension:value:source` for a stored row,
    # `goal:dimension:value` for a goal (`preferences.goal_key`). A contradiction is shown, never
    # scored: the person settles it.
    supporting: list[str] = Field(default_factory=list)
    contradicted_by: list[str] = Field(default_factory=list)


class ActivityPreferences(BaseModel):
    person_id: str
    dimensions: list[DimensionPreference] = Field(default_factory=list)
    # The same beliefs, resolved: tiers applied, superseded rows dropped, evidence counted.
    # `dimensions` stays the raw record the Privacy screen renders and the person edits; this is
    # what ranks. Both are derived from the same rows in the same read, so they cannot disagree.
    resolved: list[ResolvedPreference] = Field(default_factory=list)


# ── Closing the loop: was it any good, and what did that teach us ─────────────────────────────
#
# `FollowThrough` records whether something happened. It says nothing about whether it was worth
# happening, so the system could rank an activity someone dutifully attended and quietly hated
# exactly as highly as one they loved.


class Enjoyment(StrEnum):
    ENJOYED = "enjoyed"
    OKAY = "okay"
    NOT_FOR_ME = "not_for_me"


class LikedAspect(StrEnum):
    """What made it good, when the person chooses to say.

    These map onto `PreferenceDimension`, which is the point: "the people" is evidence about
    company, "the location" about distance, "the timing" about time of day. It is the only place
    in the product where a person tells us what worked rather than only what did not.
    """

    PEOPLE = "people"
    LOCATION = "location"
    ACTIVITY = "activity"
    TIMING = "timing"


# ── Proposed memory ───────────────────────────────────────────────────────────────────────────


class ProposedMemory(BaseModel):
    """Something Care+ believes it has learned, held back until the person agrees to it.

    The alternative -- storing it silently -- is what makes a system feel like it is watching
    rather than helping. A belief the person never agreed to is also one they can never correct,
    because they do not know it exists.

    `statement` and `question` are the exact words shown. They are stored rather than generated at
    render time so that what a person agreed to is recoverable later, word for word.
    """

    proposal_id: str
    dimension: PreferenceDimension
    value: str
    statement: str
    question: str
    source_text: str | None = None
    created_at: datetime


# ── The one question worth asking ─────────────────────────────────────────────────────────────


class ContextAnswerValue(StrEnum):
    """The five answers the one question offers, and the only five it accepts.

    The options are fixed server-side (`context_question._OPTIONS`); the senior surface renders
    them as taps, never as a text box. `value` was nonetheless a bare `str`, so anything a client
    sent -- a paragraph, an injected instruction -- was stored, echoed back and written into the
    audit detail verbatim, and anything longer than the column became a 500 on PostgreSQL. Closed
    here so the operator-readable audit trail can keep recording the token unredacted, which is
    the whole reason it is exempt from the free-text redaction rule the `note` beside it obeys.

    `PREFER_NOT_TO_SAY` is not a client-side dismissal: a question Care+ calls optional must
    be answerable with "no", and recording that is what stops it being asked again.
    """

    RESTING = "resting"
    AWAY = "away"
    OTHER_PLANS = "other_plans"
    NOT_FEELING_IT = "not_feeling_it"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class ContextAnswerOption(BaseModel):
    value: ContextAnswerValue
    label: str


class ContextQuestion(BaseModel):
    """A single question, asked only when the missing fact would change what Care+ does.

    The restraint is the feature. A question that does not change the outcome reads as scripted,
    and a system that asks whenever it is uncertain becomes an interrogation -- which is exactly
    what the people this is for have too much of already.

    `asked_because` names the specific gap, so the question is auditable as decision-changing
    rather than merely conversational.
    """

    question_id: str
    question: str
    options: list[ContextAnswerOption]
    asked_because: str


# ── Candidate baseline confirmation ───────────────────────────────────────────────────────────


class BaselineConfirmationDecision(StrEnum):
    """Two answers, deliberately not more: this is a yes/no judgement about a person's own life,
    not a multiple-choice survey, and offering a middle option would misstate what is being asked.
    """

    CONFIRM = "confirm"
    DECLINE = "decline"


class BaselineConfirmationQuestion(BaseModel):
    """Asked only when `analytics.BASELINE_DRIFT_FLOOR`'s clamp has been binding long enough that
    it plausibly describes a permanent change rather than a passing decline -- see
    `baseline_confirmation.py`. `question` is the exact plain-language wording shown; there is no
    percentage, band or internal vocabulary in it, by the same rule every senior-facing surface in
    this product follows.

    `streak_days` and `asked_because` are never rendered -- they exist so the decision is
    auditable as earned rather than merely asked.
    """

    question_id: str
    question: str
    asked_because: str
    streak_days: int


# ── Goals and the week ────────────────────────────────────────────────────────────────────────


class GoalKind(StrEnum):
    """Lifestyle goals only. Never a health target, never a step count, never a quota.

    A week view that reads as something a person is failing would be worse than no week view at
    all, which is why `target_per_week` is optional and why nothing here is ever scored.
    """

    GET_OUT_MORE = "get_out_more"
    MEET_PEOPLE = "meet_people"
    MORNING_ACTIVITY = "morning_activity"
    LESS_TRAVEL = "less_travel"


class ActivityGoal(BaseModel):
    goal_id: str
    kind: GoalKind
    text: str
    target_per_week: int | None = Field(default=None, ge=1, le=14)
    active: bool = True
    created_at: datetime


class PlannedFollowThrough(StrEnum):
    """What happened to a planned activity, in the person's words: they went, they did not, or it
    was cancelled. Three answers with no right one. `CANCELLED` is a fact about the listing, not
    the person, and teaches nothing about them."""

    WENT = "went"
    DID_NOT_GO = "did_not_go"
    CANCELLED = "cancelled"


class PlannedActivity(BaseModel):
    plan_id: str
    day: date
    activity: ActivityCandidate
    # `chosen` means the person picked it; `suggested` means Care+ is offering to fill a gap
    # and nothing is committed. The distinction has to survive to the screen.
    origin: Literal["chosen", "suggested"] = "chosen"
    replaced_reason: str | None = None
    # The loop after the plan: what the person said happened, and whether it was any good. Both
    # `None` until they say; `awaiting_report` is true once the day has passed with nothing said,
    # which is when the home screen asks -- once, gently, and never as a deadline.
    follow_through: PlannedFollowThrough | None = None
    enjoyment: Enjoyment | None = None
    awaiting_report: bool = False


class ActivityOfferResponse(StrEnum):
    """The two things a person can say to a search result. `INTERESTED` is a plan, not a booking
    -- Care+ books nothing -- and `NOT_FOR_ME` is a decline whose optional reason is the one
    piece of evidence the dimensional learner may learn a *kind* of activity from."""

    INTERESTED = "interested"
    NOT_FOR_ME = "not_for_me"


# ── Replanning ────────────────────────────────────────────────────────────────────────────────


class ReplanReason(StrEnum):
    """Why a planned activity can no longer happen -- the *code*, never the sentence.

    The wording a person reads is built in `replanning.py` from the code plus the listing's own
    title, so a reason can never be phrased as something it is not. `WEATHER` exists precisely so
    the simulator no longer has to fabricate a catalogue fact ("fully booked") to represent a
    context one: a forecast that turned is a forecast that turned.
    """

    FULL = "full"
    CANCELLED = "cancelled"
    WEATHER = "weather"


class ReplanResolution(StrEnum):
    """How a replan offer ended. `NO_ALTERNATIVE` is not a failure: "this can no longer happen and
    nothing similar was found" is a complete, honest answer, and recording it is what lets the
    gap be counted rather than guessed at. `EXPIRED` is the day passing with nothing said."""

    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    NO_ALTERNATIVE = "no_alternative"


class ReplanOffer(BaseModel):
    """One offer to replace a planned activity the world changed under, and what the person said.

    Written by the simulator's own `advance()` in the same transaction as the change that
    invalidated the plan, so an offer cannot exist without the fact behind it. `resolution` is
    `None` while the offer is open.
    """

    offer_id: str
    plan_id: str
    reason: ReplanReason
    # The listing that was actually offered at the time, or `None` when nothing similar survived
    # the same filter the search uses.
    alternative_activity_id: str | None = None
    offered_at: datetime
    resolved_at: datetime | None = None
    resolution: ReplanResolution | None = None


class ReplanNotice(BaseModel):
    """A planned activity that can no longer happen, and what Care+ suggests instead.

    The whole sequence this exists for: goal -> plan -> the world changes -> replan -> ASK -> the
    person decides. `alternative` is a proposal and nothing else; nothing is ever swapped without
    the person saying so, because silently substituting a different activity would be the system
    making a decision about someone's day on their behalf.

    `offer_id` is the server's own record of this offer. It is what "no thanks" is recorded
    against: before it existed, declining lived in browser state and the same notice came back on
    the next reload.
    """

    plan_id: str
    original_title: str
    reason: str
    # The machine-readable form of `reason`, so a surface can tell "fully booked" from "the
    # forecast turned" without reading the sentence.
    reason_code: ReplanReason
    alternative: RankedActivity | None = None
    message: str
    # `None` only for a notice computed outside the offer store (the pure `notices_for` view used
    # by tests and by the detection pass itself).
    offer_id: str | None = None


# ── The personal world model, as typed facts ──────────────────────────────────────────────────
#
# What Care+ knows about one person, assembled read-only from the stores that already hold
# it -- the baseline, the dimensional preferences, the person's own mutes and goals, their
# answers, the persona profile -- with every fact carrying where it came from and how much sits
# behind it. Nothing here is a new store: a derived view cannot drift from the evidence, and a
# fact with no row behind it cannot exist.


class FactSourceType(StrEnum):
    """Who or what a fact came from. The distinction the mandate is built on: an inference is
    never presented as something the person said."""

    EXPLICIT = "explicit"  # the person told us, in their own words or by a deliberate choice
    INFERRED = "inferred"  # learned from observations and outcomes
    EXTERNAL = "external"  # retrieved from a trusted source (none in this build)
    FIXTURE = "fixture"  # synthetic demo data, labelled as such


class FactCategory(StrEnum):
    IDENTITY = "identity"
    ROUTINE = "routine"
    ACTIVITY_PREFERENCE = "activity_preference"
    INTERACTION = "interaction"
    CONTEXT = "context"
    LEARNED_RESPONSE = "learned_response"


class PersonFact(BaseModel):
    key: str
    category: FactCategory
    # One plain sentence a person could read about themselves. Never a percentage, band or score.
    statement: str
    value: str
    source_type: FactSourceType
    # The concrete store or mechanism, e.g. `dimension_preference:senior_statement`,
    # `baseline_confirmation`, `persona_profile`.
    source: str
    confidence: FactConfidence
    evidence_count: int = Field(ge=0)
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    expires_at: datetime | None = None
    confirmed: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    # Keys of facts about the same thing that point the other way. Precedence is stated >
    # confirmed > inferred, and it is applied where the facts are used (`dimension_score`); here
    # the disagreement is shown rather than averaged away.
    contradicts: list[str] = Field(default_factory=list)
    # Which side of a disagreement the ranker actually uses, decided by the resolver's own tiers
    # (`ResolvedPreference.tier == winning_tier`) so no screen re-ranks fact kinds. `None` when
    # `contradicts` is empty. `this_applies`: this fact's belief is in effect and no contradicting
    # one is. `other_applies`: a contradicting belief is in effect and this one is not.
    # `neither_applies`: a higher-tier belief elsewhere in the resolution group (another value on
    # TIMING, SOCIAL or ENVIRONMENT) wins, so neither side is used. `undecided`: equal tiers, both
    # in effect, leaning opposite ways -- they cancel until the person settles it.
    contradiction_outcome: (
        Literal["this_applies", "other_applies", "neither_applies", "undecided"] | None
    ) = None
    # Whether this preference or goal is a belief the ranker currently uses (its tier wins its
    # resolution group, `preferences.belief_in_effect`). `False` for a belief held back, outranked
    # or not resolved, and for a DISTANCE belief with no number that is never read (one leaning
    # far, or a learned one); `None` for a
    # fact that is not a preference belief at all (identity, routine, history, a goal that names
    # no preference axis).
    in_effect: bool | None = None
    # An inferred fact nothing has reinforced for a long stretch of the person's simulated
    # calendar. Still shown, still counted, but labelled -- staleness is stated, never decayed
    # silently into a smaller number.
    stale: bool = False


class WorldModelQuality(BaseModel):
    """Is the model becoming richer, or merely larger? Counts, never rates."""

    facts: int = 0
    explicit: int = 0
    inferred: int = 0
    external: int = 0
    fixture: int = 0
    confirmed: int = 0
    single_evidence: int = 0
    temporary: int = 0
    expired_excluded: int = 0
    contradictions: int = 0
    stale: int = 0


class PersonWorldModel(BaseModel):
    person_id: str
    as_of_day: date
    facts: list[PersonFact] = Field(default_factory=list)
    # What Care+ does not know about this person and will not guess. Stated, not hidden.
    gaps: list[str] = Field(default_factory=list)
    quality: WorldModelQuality


class OperationalMetrics(BaseModel):
    people: int
    scenario_run_id: str
    audit_events: int
    decision_evidence: int
    interventions: int
    outcomes: int
    open_cases: int
    no_action_decisions: int
    consent_active: bool
    last_decision: Decision | None
    last_observed_at: datetime | None
    source_classification_counts: dict[str, int]
    preference_scores: dict[str, float]
    candidate_preference_scores: dict[str, float]
    candidate_labels: dict[str, str] = Field(default_factory=dict)
    candidate_offer_counts: dict[str, int] = Field(default_factory=dict)
    candidate_accepted_counts: dict[str, int] = Field(default_factory=dict)
    # Outreach-planner observability. Every one of these is derived from data the planner
    # already writes into `InterventionRow.evidence_json` and that nothing has ever read back.
    #
    # `planner_agreed_with_ranker` counts agent-mode runs whose choice matched the deterministic
    # ranker's top pick, which is recorded *before* the planner runs. It is a redundancy measure,
    # not a quality one: agreement says the planner added nothing, disagreement says nothing
    # about which was right. Read it over `planner_contested_runs` -- the agent-mode runs where
    # the policy permitted at least two candidates -- because a planner handed one option can
    # only agree. The guardrail counters answer "which safety rules actually bind in practice",
    # which is otherwise a claim with no number behind it.
    #
    # All default to zero so a run with the planner disabled reports honestly rather than absent.
    planner_runs: int = 0
    planner_agent_selected: int = 0
    planner_contested_runs: int = 0
    planner_agreed_with_ranker: int = 0
    planner_fallback_modes: dict[str, int] = Field(default_factory=dict)
    planner_guardrail_rejections: int = 0
    planner_guardrail_violations: int = 0
    # What the model cost, across all three LLM entry points (outreach planning, activity
    # reranking, intent parsing). Built by `sql_repository._llm_cost_observability` from evidence
    # those paths already write; nothing new is recorded to produce them.
    #
    # Counts and sums, never rates and never prices -- a rate here would be quoted without its
    # denominator within the week. `llm_calls` counts runs that actually reached a model, so
    # under `LLM_ENABLED=false` every one of these is zero and says so honestly.
    # `llm_fallbacks_by_mode` includes the `agent` mode too, so the modes sum to the number of
    # runs. `guardrail_rejections_by_rule` names which safety rules actually bind in practice.
    llm_calls: int = 0
    llm_latency_ms_total: int = 0
    llm_tokens_total: int = 0
    llm_fallbacks_by_mode: dict[str, int] = Field(default_factory=dict)
    guardrail_rejections_by_rule: dict[str, int] = Field(default_factory=dict)
    # Follow-through observability. `candidate_accepted_counts` counts taps; these count what
    # happened next, and the gap between the two is the number that says whether outreach is
    # landing or merely being acknowledged.
    candidate_followed_counts: dict[str, int] = Field(default_factory=dict)
    candidate_completed_counts: dict[str, int] = Field(default_factory=dict)
    follow_through_reported: int = 0
    follow_through_completed: int = 0
    # Deferred effect. `follow_up_returned_toward_usual` is a count of observations, NOT a success
    # rate and NOT a causal claim -- a person can return to their usual activity for every reason
    # under the sun. It is reported with its denominator so it cannot be quoted without one.
    follow_up_observations: int = 0
    follow_up_returned_toward_usual: int = 0
    suppressed_candidates: int = 0
    day_disputes: int = 0
    # Days in this run whose tracker wear-time was too low for the reading to be interpreted --
    # the days `quality.assess_data_quality` marks `device_suspected`. Until this existed, that
    # flag was computed, written into a careful sentence, and then rendered nowhere a coordinator
    # could see it: a care team could not tell "three of this week's readings never arrived" from
    # "this week was quiet", which are opposite problems.
    #
    # A data-collection fact, never a wellbeing signal, and it changes no decision: a sparse day
    # is still NO_ACTION and still `stable`, because a reading nobody can interpret supports
    # nothing either way. The strongest wording any surface may put on it is "tracker may not have
    # synced".
    device_suspected_days: int = 0
    # The shape of what is known about this person -- counts by provenance, never the content.
    # A coordinator or evaluator may see that three things were stated and two inferred; the
    # activity preferences themselves stay on the senior's own surface, by the standing decision
    # that care-team visibility into the user-initiated loop is aggregate only.
    world_model_quality: WorldModelQuality = Field(default_factory=WorldModelQuality)
    # The user-initiated loop's funnel, as counts with their own denominators beside them:
    # searches run, results shown, taps either way, plans made, reports back, and what those
    # reports said. `activity_decline_reasons` is per `DeclineReason`. None of these is a rate.
    activity_searches: int = 0
    activity_results_shown: int = 0
    activity_interested: int = 0
    activity_not_for_me: int = 0
    activity_decline_reasons: dict[str, int] = Field(default_factory=dict)
    activities_planned: int = 0
    # `plans_due` is the honest denominator for reports: week entries whose day has passed.
    # `activities_planned` includes days still to come, and a report cannot exist for those.
    plans_due: int = 0
    activity_reports: int = 0
    activity_went: int = 0
    activity_enjoyed: int = 0
    # Replanning, as counts with their own denominator beside them: how often the world changed
    # under a plan and the person was told, and what they said. Before these, the strongest
    # agentic moment the product has had no evidence and no measure at all (audit F finding 8).
    # `replans_offered` is the denominator; the two answers do not sum to it, because an offer
    # can still be open, or have expired with the day.
    replans_offered: int = 0
    replans_accepted: int = 0
    replans_declined: int = 0
    # The response clock. `awaiting_reply` is outreach still open inside its response window;
    # `no_reply_recorded` is outreach whose latest outcome is `no_response` -- recorded by the
    # clock once the window closed, or by a coordinator. Two numbers rather than one, because
    # "nobody has answered yet" and "nobody answered" are different states, and the difference
    # `interventions - outcomes` the UI used to compute conflated both with withdrawn offers.
    awaiting_reply: int = 0
    no_reply_recorded: int = 0
    # Override memory, as two counts rather than one rate. `coordinator_reviews` counts reviews a
    # human actually recorded a choice on -- not every `CaseReviewRow`, because the system writes
    # its own closures for recovery and consent withdrawal and folding those into the denominator
    # would make the system look more agreed-with the more cases resolved themselves.
    # `coordinator_overrides` is the subset where the human did not follow the recommendation. A
    # percentage is deliberately absent: this is a prototype with a handful of reviews, and a
    # "agreement rate" computed from three of them would be quoted without its denominator within
    # the week.
    coordinator_reviews: int = 0
    coordinator_overrides: int = 0
    # Learned from the timestamps of responses already on record -- the first genuinely new belief
    # about a person the system holds beyond their step baseline. `None` until there are enough
    # responses for the hour to mean anything.
    typical_response_hour: int | None = None
    typical_response_hour_sample: int = 0
    policy_version: str
    persistence: str
    offline_ready: bool


# ── Family groups ─────────────────────────────────────────────────────────────


class AccountRole(StrEnum):
    """What someone signs up as. Only these two roles can be chosen; the rest are provisioned."""

    SENIOR = "senior"
    FAMILY = "family"


class GroupRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class MemberStatus(StrEnum):
    ACTIVE = "active"
    PENDING = "pending"


class OnboardRequest(BaseModel):
    role: AccountRole
    display_name: str = Field(min_length=1, max_length=80)


class MyGroup(BaseModel):
    group_id: str
    # None until the senior is linked with their senior-link PIN.
    person_id: str | None
    # The senior's own account name once linked; until then the name the creator typed.
    senior_name: str
    my_role: GroupRole
    my_status: MemberStatus
    # Active members only; someone waiting for approval does not count.
    member_count: int
    # True on at most one group: the active membership this account opened most recently.
    last_opened: bool
    # This member's unread notifications in this group, for a badge on its group card. The bell
    # counts across every group; this is the same count split by group. 0 while pending.
    unread_count: int


class MeResponse(BaseModel):
    """Who is signed in, and what they still have to do before using the app."""

    sub: str
    role: AuthRole | None
    display_name: str | None
    # The senior's own record, for a senior account.
    person_id: str | None
    # True until the account has chosen `senior` or `family` (`POST /v1/me/onboard`).
    needs_onboarding: bool
    groups: list[MyGroup] = Field(default_factory=list)


class PinResponse(BaseModel):
    pin: str
    expires_at: datetime


class CreateGroupRequest(BaseModel):
    """`senior_name` alone creates a group with no senior linked yet; `senior_pin` (the PIN on the
    senior's screen) creates it linked, and the senior's own account name wins. At least one."""

    relationship: str = Field(min_length=1, max_length=40)
    senior_name: str | None = Field(default=None, min_length=1, max_length=80)
    senior_pin: str | None = Field(default=None, pattern=r"^[0-9]{6}$")

    @field_validator("senior_name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        # Before the length check, so only what is kept counts.
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _name_or_pin(self) -> CreateGroupRequest:
        if self.senior_name is None and self.senior_pin is None:
            raise ValueError("Enter the senior's name, or the PIN on their screen.")
        return self


class LinkSeniorRequest(BaseModel):
    senior_pin: str = Field(pattern=r"^[0-9]{6}$")


class SeniorNameRequest(BaseModel):
    senior_name: str = Field(min_length=1, max_length=80)

    @field_validator("senior_name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class JoinGroupRequest(BaseModel):
    pin: str = Field(pattern=r"^[0-9]{6}$")
    relationship: str = Field(min_length=1, max_length=40)


class GroupMember(BaseModel):
    member_id: str
    display_name: str
    relationship: str
    role: GroupRole
    status: MemberStatus
    is_me: bool
    joined_at: datetime


class CareGroup(BaseModel):
    group_id: str
    # None until the senior is linked with their senior-link PIN.
    person_id: str | None
    # The senior's own account name once linked; until then the name the creator typed.
    senior_name: str
    members: list[GroupMember]


# ── Family calendar (appointments, availability, helpers) ─────────────────────


class AppointmentKind(StrEnum):
    MEDICAL = "medical"
    THERAPY = "therapy"
    ACTIVITY = "activity"
    ERRAND = "errand"


class RepeatRule(StrEnum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


ClockTime = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]


class AppointmentRequest(BaseModel):
    """A new or changed appointment. A repeating one is stored once and shown on every day it
    repeats, until `repeat_until` (inclusive) or forever."""

    title: str = Field(min_length=1, max_length=120)
    kind: AppointmentKind
    date: date
    start: ClockTime
    end: ClockTime
    location: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=1000)
    repeat: RepeatRule = RepeatRule.NONE
    repeat_until: date | None = None

    @model_validator(mode="after")
    def _check_times(self) -> AppointmentRequest:
        if self.end <= self.start:
            raise ValueError("The end time needs to be after the start time.")
        if self.repeat_until is not None and self.repeat_until < self.date:
            raise ValueError("A repeat cannot end before the first day.")
        return self


class Appointment(AppointmentRequest):
    appointment_id: str


class AppointmentOccurrence(BaseModel):
    """One day of an appointment. `occurrence_id` is `<appointment_id>@<YYYY-MM-DD>`: what
    availability answers and helpers are attached to, so each week of a weekly visit has its own."""

    occurrence_id: str
    appointment_id: str
    title: str
    kind: AppointmentKind
    date: date
    start: str
    end: str
    location: str | None
    notes: str | None
    repeat: RepeatRule


class CalendarMember(BaseModel):
    member_id: str
    display_name: str
    relationship: str
    # Which avatar colour (0-5) this member wears, by the order they joined.
    colour: int
    is_me: bool


class AvailabilityEntryOut(BaseModel):
    entry_id: str
    member_id: str
    date: date
    start: str
    end: str
    status: AvailabilityStatus
    # Set when this is an answer about one appointment rather than a window of free time.
    occurrence_id: str | None


class HelperAssignment(BaseModel):
    occurrence_id: str
    member_id: str


class FamilyCalendar(BaseModel):
    # None for the calendar of a family group whose senior is not linked yet.
    person_id: str | None
    senior_name: str
    group_id: str | None
    from_date: date
    to_date: date
    members: list[CalendarMember]
    appointments: list[AppointmentOccurrence]
    availability: list[AvailabilityEntryOut]
    assignments: list[HelperAssignment]


class AvailabilityRequest(BaseModel):
    """A window of time the caller is (or is not) free, whatever is on the calendar."""

    date: date
    start: ClockTime
    end: ClockTime
    status: AvailabilityStatus

    @model_validator(mode="after")
    def _check_times(self) -> AvailabilityRequest:
        if self.end <= self.start:
            raise ValueError("The end time needs to be after the start time.")
        return self


class OccurrenceAnswerRequest(BaseModel):
    occurrence_id: str = Field(max_length=100)
    status: AvailabilityStatus


class OccurrenceRequest(BaseModel):
    occurrence_id: str = Field(max_length=100)


# ── Family activity feed and check-ins ────────────────────────────────────────


class FamilyActivityKind(StrEnum):
    """What a feed entry records. Closed: the browser words each one itself."""

    GROUP_CREATED = "group_created"
    MEMBER_APPROVED = "member_approved"
    MEMBER_DECLINED = "member_declined"
    APPOINTMENT_ADDED = "appointment_added"
    APPOINTMENT_CHANGED = "appointment_changed"
    APPOINTMENT_REMOVED = "appointment_removed"
    HELPER_JOINED = "helper_joined"
    HELPER_STEPPED_BACK = "helper_stepped_back"
    AVAILABILITY_UPDATED = "availability_updated"
    CHECK_IN = "check_in"
    NOTE_ADDED = "note_added"
    SENIOR_LINKED = "senior_linked"
    SENIOR_RENAMED = "senior_renamed"
    HELPER_ASKED = "helper_asked"
    HELPER_DECLINED = "helper_declined"


class CheckInKind(StrEnum):
    CALLED = "called"
    VISITED = "visited"
    MESSAGED = "messaged"


class CheckInRequest(BaseModel):
    """A family member telling the group they called, visited or messaged the senior. The note is
    for the group only: it is never sent to the senior, the agent or the audit trail."""

    kind: CheckInKind
    note: str | None = Field(default=None, max_length=200)

    @field_validator("note", mode="before")
    @classmethod
    def _strip_note(cls, value: object) -> object:
        # Before the length check, so only what is kept counts towards the 200.
        if isinstance(value, str):
            return value.strip() or None
        return value


class FamilyActivityEntry(BaseModel):
    """One entry of the family feed: structured fields only, the browser writes the sentence."""

    activity_id: str
    kind: FamilyActivityKind
    at: datetime
    actor_member_id: str
    actor_name: str
    is_me: bool
    # `member_approved`: the member who was let in. `helper_asked`: the member who was asked.
    subject_name: str | None
    appointment_id: str | None
    # A snapshot from when it happened, so it survives the appointment being removed.
    appointment_title: str | None
    appointment_kind: AppointmentKind | None
    on_date: date | None
    # Computed on read: set only while the appointment exists and still has that day.
    occurrence_id: str | None
    check_in_kind: CheckInKind | None
    note: str | None
    origin: Literal["live", "demo_seed"]


class FamilyActivityPage(BaseModel):
    """Newest first. Pass `next_before` as `before` for the next page; None at the end."""

    entries: list[FamilyActivityEntry]
    next_before: str | None


AgentMode = Literal["agent", "fallback_disabled", "fallback_error", "fallback_no_proposal"]


class AgentStep(BaseModel):
    """One step a family-facing agent took: a tool it read, or its submission and the verdict."""

    tool_name: str
    ok: bool
    summary: str


class CatchUp(BaseModel):
    """ "Since you last visited": a short catch-up for a family member opening Home.

    `mode` is `agent` when the catch-up agent wrote it and the deterministic check approved it;
    any `fallback_*` mode means Care+ assembled the same facts without a model (the flag is off,
    the provider failed, or nothing passed the check). `source` says which model wrote an `agent`
    result: `live` (a real provider) or `recorded` (a replayed recording); it is null otherwise.
    `steps` is what the agent did, in order.
    """

    mode: AgentMode
    source: Literal["live", "recorded"] | None
    summary: str
    highlights: list[str]
    since: datetime | None
    generated_at: datetime
    model: str | None
    new_updates: int = Field(ge=0)
    visits_needing_someone: int = Field(ge=0)
    tasks_done: int = Field(ge=0)
    tasks_total: int = Field(ge=0)
    steps: list[AgentStep]


class MyDay(BaseModel):
    """ "Read my day": a short spoken run-through of the senior's own day, for the browser to read
    aloud with its built-in speech. `mode`, `source`, `model` and `steps` as on `CatchUp`."""

    mode: AgentMode
    source: Literal["live", "recorded"] | None
    script: str
    day: date
    generated_at: datetime
    model: str | None
    appointments_today: int = Field(ge=0)
    reminders_done: int = Field(ge=0)
    reminders_total: int = Field(ge=0)
    steps: list[AgentStep]


class AppointmentDraftRequest(BaseModel):
    """What a family member typed to describe an appointment ("Eye check-up next Tuesday 10:30 at
    Bedok Polyclinic"). Never stored and never logged."""

    text: str = Field(min_length=1, max_length=300)


class AppointmentDraft(BaseModel):
    """The appointment form, filled in from what was typed. Nothing is saved: the family member
    checks the form and saves it with the ordinary `POST /appointments`.

    Each field is null when it was not recognised; `missing` names those, `assumed` names the ones
    filled in without being said (an end an hour after the start, a best-guess kind), and
    `clashes` the titles of the group's appointments that overlap the slot. `mode`, `source`,
    `model` and `steps` as on `CatchUp`; notes are never filled in.
    """

    mode: AgentMode
    source: Literal["live", "recorded"] | None
    title: str | None
    kind: AppointmentKind | None
    date: date | None
    start: str | None
    end: str | None
    location: str | None
    repeat: RepeatRule
    missing: list[str]
    assumed: list[str]
    clashes: list[str]
    generated_at: datetime
    model: str | None
    steps: list[AgentStep]


# ── Asks and notifications ────────────────────────────────────────────────────
#
# One family member asking another, by name, to take one day of an appointment that needs a
# helper, and the in-app notifications about it. Never sent to the senior, and none leaves the app.


class HelperAskState(StrEnum):
    """An ask is `open` until it ends in exactly one of the other states; it never reopens."""

    OPEN = "open"
    ACCEPTED = "accepted"  # the asked member said yes and became the helper
    DECLINED = "declined"  # the asked member said no; the day needs a helper again
    WITHDRAWN = "withdrawn"  # the asker took it back, or the appointment day was removed
    LAPSED = "lapsed"  # the appointment started with no answer
    CLOSED = "closed"  # someone else pressed "I'll go"


class NotificationKind(StrEnum):
    """What a notification tells its one recipient. Closed: the browser words each one itself."""

    ASK_RECEIVED = "ask_received"  # to the asked member
    ASK_ACCEPTED = "ask_accepted"  # to the asker
    ASK_DECLINED = "ask_declined"  # to the asker
    ASK_WITHDRAWN = "ask_withdrawn"  # to the asked member
    ASK_LAPSED = "ask_lapsed"  # to the asker
    ASK_CLOSED = "ask_closed"  # to the asker and the asked member, but not whoever closed it


class HelperAskRequest(BaseModel):
    """Ask an active member of the group to take one day of an appointment."""

    occurrence_id: str = Field(max_length=100)
    asked_member_id: str = Field(max_length=64)


class HelperAsk(BaseModel):
    ask_id: str
    occurrence_id: str
    appointment_id: str
    on_date: date
    asker_member_id: str
    asker_name: str
    asked_member_id: str
    asked_name: str
    created_at: datetime
    state: HelperAskState
    # For the viewer: whether they are the asked member (yes / no) or the asker (withdraw), while
    # the ask is open.
    can_answer: bool
    can_withdraw: bool


class HelperAskList(BaseModel):
    asks: list[HelperAsk]


class NotificationItem(BaseModel):
    """One notification for the signed-in member, with what the bell needs to show it."""

    notification_id: str
    kind: NotificationKind
    created_at: datetime
    read: bool
    group_id: str
    # The senior's name, as the group is labelled everywhere else.
    group_label: str
    ask_id: str
    # The ask's state now, which may have moved on since the notification was written.
    ask_state: HelperAskState
    # Set only while the appointment exists and still has that day.
    occurrence_id: str | None
    # The appointment's title now, or the one it had when asked once it is gone.
    appointment_title: str
    on_date: date
    # The appointment's start time now; None once the appointment or its day is gone.
    start: str | None
    asker_name: str
    asked_name: str
    # Who ended the ask, when a member did (None while open, and for a lapse).
    ended_by_name: str | None
    # The recipient is the asked member and the ask is still open: show "Yes, I'll go" / "Can't go".
    is_open_for_me: bool


class NotificationPage(BaseModel):
    """Newest first, across all the member's family groups. Pass `next_before` as `before` for the
    next page; None at the end. `unread_count` counts every unread notification, not just this
    page's."""

    items: list[NotificationItem]
    unread_count: int
    next_before: str | None


class NotificationReadRequest(BaseModel):
    """Mark some of your notifications read (`notification_ids`), or all of them (`all`)."""

    notification_ids: list[Annotated[str, Field(max_length=64)]] = Field(
        default_factory=list, max_length=100
    )
    all: bool = False

    @model_validator(mode="after")
    def _exactly_one(self) -> NotificationReadRequest:
        if bool(self.notification_ids) == self.all:
            raise ValueError("Send either notification_ids or all: true.")
        return self


# ── Appointment notes ─────────────────────────────────────────────────────────


class AppointmentNoteRequest(BaseModel):
    """A note on one day of an appointment, for the family group only: the senior never reads it,
    and it is never logged, audited or given to the agent."""

    date: date
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        # Before the length checks, so a blank note is refused and only what is kept counts.
        return value.strip() if isinstance(value, str) else value


class AppointmentNote(BaseModel):
    note_id: str
    appointment_id: str
    occurrence_id: str
    member_id: str
    author_name: str
    is_mine: bool
    text: str
    created_at: datetime


# ── Tasks ────────────────────────────────────────────────────────────────────
#
# A shared reminder list for the senior, kept by their family group. Never read by `advance`, the
# policy, review cases or outreach: a missed tick triggers nothing.


class TaskKind(StrEnum):
    # A label the family writes; Care+ never suggests a medicine, dose or time.
    TASK = "task"
    MEDICINE = "medicine"


class TaskRepeat(StrEnum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"  # every seven days from `start_date`


class TaskRequest(BaseModel):
    """A new or changed task. A repeating one is stored once and happens on every day it repeats,
    until `repeat_until` (inclusive) or forever."""

    title: str = Field(min_length=1, max_length=120)
    kind: TaskKind = TaskKind.TASK
    start_date: date
    time: ClockTime
    repeat: TaskRepeat = TaskRepeat.NONE
    repeat_until: date | None = None
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _check_dates(self) -> TaskRequest:
        if self.repeat_until is not None and self.repeat_until < self.start_date:
            raise ValueError("A repeat cannot end before the first day.")
        return self


class Task(TaskRequest):
    task_id: str
    # The display name of whoever added it, or None when their account is gone.
    added_by_name: str | None
    created_at: datetime
    updated_at: datetime


class TaskTick(BaseModel):
    """One day of a task ticked done."""

    task_id: str
    day: date
    done_by_name: str | None
    done_at: datetime


class TaskList(BaseModel):
    # None for a family group whose senior is not linked yet.
    person_id: str | None
    group_id: str | None
    from_date: date
    to_date: date
    tasks: list[Task]
    ticks: list[TaskTick]


class TaskDayRequest(BaseModel):
    done: bool


# ── The senior's watch ───────────────────────────────────────────────────────


class WearableStatus(BaseModel):
    """Whether the senior's watch is connected, when it last synced, and its battery. Simulated
    until a real device adapter exists (`source` says so); never a health signal."""

    connected: bool
    last_synced_at: datetime | None
    # 0-100, or None when no watch is connected.
    battery_percent: int | None = Field(default=None, ge=0, le=100)
    charging: bool
    source: Literal["synthetic"]


# ── The Care+ assistant ──────────────────────────────────────────────────────


class AssistantMessage(BaseModel):
    """One turn of the chat, as the person saw it."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AssistantChatRequest(BaseModel):
    """The conversation so far (the newest turn last, and it is theirs), which senior it is about,
    and the page they are on. Only the last 20 turns are sent."""

    messages: list[AssistantMessage] = Field(min_length=1, max_length=20)
    # Family only: the senior they care for. A senior always talks about themselves.
    person_id: str | None = Field(default=None, max_length=80)
    page: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def _ends_with_a_question(self) -> AssistantChatRequest:
        if self.messages[-1].role != "user":
            raise ValueError("The last message needs to be the person's own.")
        return self


class AssistantReply(BaseModel):
    """The assistant's answer. `source` says where it came from: `openai`, the built-in `helper`
    (no AI key, the offline demo, or the AI could not be reached), or a fixed `safety` answer
    (an emergency or a question about medicines, which never goes to the AI)."""

    reply: str
    source: Literal["openai", "helper", "safety"]
    suggestions: list[str] = Field(default_factory=list)
