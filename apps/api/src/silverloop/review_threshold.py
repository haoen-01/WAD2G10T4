"""The per-person review threshold: its bounds, its live value, and the rules around changing it.

The review threshold is the point on `policy.decide`'s ladder at which Care+ asks a human
(`COORDINATOR_REVIEW`). A coordinator's structured false-alarm judgement may tune it, per person
and inside fixed bounds -- never the baseline, never any other gate (ADR 0008,
`docs/review-threshold-spec.md`). Everything here is pure: stdlib and `silverloop.models` only, so
the ladder, the evaluation harness, the repository and the agent guardrail can all import it
without reaching a database, a configuration or a model.

What lives here:

- the constants and the fourteen-point grid (`ALLOWED_THRESHOLDS`);
- `resolve_live_threshold`, the stateless fold that reads the live value from append-only
  decision facts on every evaluation (reads never write);
- `is_false_alarm`, the one combination of a coordinator review this module ever counts;
- `validate_threshold_structure`, the structural half of the guardrail (the wording half lives in
  `agent/threshold_guardrails.py`);
- `fixed_rule_output` and `fixed_rule_tightening`, the deterministic proposers used offline and
  as the agent's fallback;
- checking afterwards: the never-ask-later revert walk, the shadow clear's approval stack, the
  checking period, the far-more-severe bar and the fixed write-up template;
- the senior notice wording and the rule selecting it.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from silverloop.models import (
    CaseStatus,
    HumanAction,
    OverrideReason,
    ReviewThresholdBounds,
    ReviewThresholdCause,
    ReviewThresholdDecisionKind,
    ReviewThresholdFloor,
    ReviewThresholdNotice,
    ReviewThresholdNoticeKind,
    ReviewThresholdOutputKind,
    ReviewThresholdRejectionReason,
    ReviewThresholdRevertTrigger,
    ReviewThresholdValue,
)

# ── Bounds ────────────────────────────────────────────────────────────────────────────────────

MIN_SEVERITY_PCT = 30
MAX_SEVERITY_PCT = 55
SEVERITY_STEP_PCT = 5
MIN_PERSISTENCE_DAYS = 3
MAX_PERSISTENCE_DAYS = 5
PERSISTENCE_STEP_DAYS = 1

# How long a looser setting may go without asking before the starting setting would have asked,
# before the shadow check asks a human anyway.
SHADOW_GRACE_DAYS = 3
# How far back the shadow check looks for the start of an unfinished episode.
SHADOW_SCAN_DAYS = 28
CHECKING_PERIOD_DAYS = 14
# A loosened setting lapses back this many days after it took effect unless reconfirmed.
LOOSENED_EXPIRY_DAYS = 60
COOLDOWN_DAYS = 7
WEEKLY_PROPOSAL_CAP = 5
PROPOSALS_PER_ROUND = 3
FIXED_RULE_FALSE_ALARMS = 2
FIXED_RULE_WINDOW_DAYS = 30
SENIOR_NOTICE_DAYS = 7
REPLAY_WINDOW_DAYS = 56

# Spelled-out persistence, so the default rung's rationale stays byte-identical to the literal
# policy text it replaced ("at least three valid-wear days").
PERSISTENCE_WORDS: dict[int, str] = {3: "three", 4: "four", 5: "five"}


@dataclass(frozen=True)
class ReviewThreshold:
    """Review when activity is at least `severity_pct` below the personal baseline for at least
    `persistence_days` valid-wear days.

    Deliberately not range-checked on construction: `ABSOLUTE_REVIEW_FLOOR` is a threshold too,
    and it sits outside the grid nobody may choose from. `is_allowed` answers the grid question.
    """

    severity_pct: int
    persistence_days: int

    def fires(self, severity: float, sustained_low_days: int) -> bool:
        return sustained_low_days >= self.persistence_days and severity >= self.severity_pct

    def looser_than(self, other: ReviewThreshold) -> bool:
        """Asks later than `other` in either dimension."""
        return (
            self.severity_pct > other.severity_pct or self.persistence_days > other.persistence_days
        )

    def stricter_than(self, other: ReviewThreshold) -> bool:
        """Asks sooner than `other` in either dimension."""
        return (
            self.severity_pct < other.severity_pct or self.persistence_days < other.persistence_days
        )

    @property
    def is_allowed(self) -> bool:
        return self in ALLOWED_THRESHOLDS

    def as_value(self) -> ReviewThresholdValue:
        """The contract shape. Raises for a value off the grid (the floor has its own shape)."""
        return ReviewThresholdValue(
            severity_pct=self.severity_pct, persistence_days=self.persistence_days
        )

    @classmethod
    def from_value(cls, value: ReviewThresholdValue) -> ReviewThreshold:
        return cls(value.severity_pct, value.persistence_days)


DEFAULT_REVIEW_THRESHOLD = ReviewThreshold(40, 3)
ABSOLUTE_REVIEW_FLOOR = ReviewThreshold(60, 3)
# A case opened at or beyond this shortfall inside a checking period reverts a loosening.
FAR_MORE_SEVERE_PCT = ABSOLUTE_REVIEW_FLOOR.severity_pct


def on_one_side_of_the_default(threshold: ReviewThreshold) -> bool:
    """No "mixed" settings: a setting either waits at least as long and asks at no lower shortfall
    than the starting setting (the loosening side, `severity >= 40` with `persistence >= 3`), or
    keeps the starting setting's three days and asks at a lower shortfall (the tightening side).

    Persistence can never go below three days, so asking sooner is severity-only. Forbidding the
    mixed values (30% or 35% for four or five days) keeps every allowed setting componentwise
    comparable with the starting setting: going back to the starting setting can never ask later
    in one dimension while asking sooner in the other. Settings on the same side are NOT all
    comparable with each other (45%/3 days and 40%/4 days are not), which is why a revert walks
    the stack and checks each value it would restore rather than trusting any earlier approval.
    """
    return (
        threshold.severity_pct >= DEFAULT_REVIEW_THRESHOLD.severity_pct
        or threshold.persistence_days == DEFAULT_REVIEW_THRESHOLD.persistence_days
    )


# Fourteen points: 40..55% x 3..5 days on the loosening side, plus 30% and 35% at three days.
ALLOWED_THRESHOLDS: tuple[ReviewThreshold, ...] = tuple(
    threshold
    for threshold in (
        ReviewThreshold(severity, persistence)
        for severity in range(MIN_SEVERITY_PCT, MAX_SEVERITY_PCT + 1, SEVERITY_STEP_PCT)
        for persistence in range(
            MIN_PERSISTENCE_DAYS, MAX_PERSISTENCE_DAYS + 1, PERSISTENCE_STEP_DAYS
        )
    )
    if on_one_side_of_the_default(threshold)
)


def review_threshold_bounds() -> ReviewThresholdBounds:
    """Every bound above, in the contract shape the Care Team card reads."""
    return ReviewThresholdBounds(
        default=DEFAULT_REVIEW_THRESHOLD.as_value(),
        minimum=ReviewThreshold(MIN_SEVERITY_PCT, MIN_PERSISTENCE_DAYS).as_value(),
        maximum=ReviewThreshold(MAX_SEVERITY_PCT, MAX_PERSISTENCE_DAYS).as_value(),
        floor=ReviewThresholdFloor(
            severity_pct=ABSOLUTE_REVIEW_FLOOR.severity_pct,
            persistence_days=ABSOLUTE_REVIEW_FLOOR.persistence_days,
        ),
        severity_step_pct=SEVERITY_STEP_PCT,
        persistence_step_days=PERSISTENCE_STEP_DAYS,
        grace_days=SHADOW_GRACE_DAYS,
        checking_period_days=CHECKING_PERIOD_DAYS,
        expiry_days=LOOSENED_EXPIRY_DAYS,
        cooldown_days=COOLDOWN_DAYS,
        weekly_proposal_cap=WEEKLY_PROPOSAL_CAP,
        proposals_per_round=PROPOSALS_PER_ROUND,
    )


# ── Live resolution ───────────────────────────────────────────────────────────────────────────

LiveSource = Literal["starting_setting", "approved", "reverted", "expired"]

# The decision kinds that move the live value. `rejected`, `reconfirmed` and the two checking
# outcomes never do (a reconfirmation only restarts a clock).
CHANGE_KINDS = frozenset(
    {
        ReviewThresholdDecisionKind.APPROVED,
        ReviewThresholdDecisionKind.REVERTED,
        ReviewThresholdDecisionKind.EXPIRED,
    }
)


@dataclass(frozen=True)
class ThresholdDecisionFact:
    """One `review_threshold_decisions` row, as much of it as the pure rules need.

    `after` is the value the row records: the approved value for `approved`, the restored value
    for `reverted`/`expired`, and the rejected proposal's value for `rejected` (so the repeat rule
    can see it). `None` where the row carries no value.
    """

    decision_id: str
    kind: ReviewThresholdDecisionKind
    previous: ReviewThreshold
    after: ReviewThreshold | None
    decided_on_day: date
    effective_from_day: date
    decided_at: datetime
    revert_trigger: ReviewThresholdRevertTrigger | None = None
    ends_approval_id: str | None = None
    affects_decision_id: str | None = None
    proposal_id: str | None = None
    # Set on `rejected` rows. System rejections (`consent_withdrawn`, `superseded`) are not a
    # coordinator's judgement of the value, so the repeat rule ignores them.
    rejection_reason: ReviewThresholdRejectionReason | None = None


@dataclass(frozen=True)
class LiveReviewThreshold:
    threshold: ReviewThreshold
    source: LiveSource
    # The approval whose value is live; `None` when the starting setting is live.
    approval_id: str | None
    # Whether the live approval carries an expiry clock: see `has_expiry_clock`.
    loosened: bool
    # When the most recent change to the live value took effect; `None` for the untouched default.
    effective_from_day: date | None
    expires_on_day: date | None


@dataclass
class _Entry:
    fact: ThresholdDecisionFact
    threshold: ReviewThreshold
    loosened: bool
    expires_on_day: date | None


def has_expiry_clock(previous: ReviewThreshold, after: ReviewThreshold) -> bool:
    """Whether an approval from `previous` to `after` lapses after `LOOSENED_EXPIRY_DAYS`.

    Looser than the starting setting in either dimension, OR looser than the value it replaced.
    The first half matters for a stacked step back: 40%/5 days -> 40%/4 days asks sooner than the
    value it replaced, but still waits longer than the starting setting, so it must not sit on the
    stack forever -- nor keep the loosening beneath it from expiring. The second half covers the
    tightening side: 30%/3 days -> 35%/3 days asks later than before while still sooner than the
    starting setting. This is deliberately a different question from the senior notice's "did
    this change make Care+ wait longer?", which compares with the value replaced only.
    """
    return after.looser_than(DEFAULT_REVIEW_THRESHOLD) or after.looser_than(previous)


# The decision kinds that touch the approval stack. `rejected` and the checking outcomes do not, so
# folding them never triggers a stateless expiry pop of its own.
_STACK_KINDS = frozenset(
    {
        ReviewThresholdDecisionKind.APPROVED,
        ReviewThresholdDecisionKind.REVERTED,
        ReviewThresholdDecisionKind.EXPIRED,
    }
)


def _fact_order(fact: ThresholdDecisionFact) -> tuple[date, datetime, str]:
    return (fact.effective_from_day, fact.decided_at, fact.decision_id)


def resolve_live_threshold(
    facts: Sequence[ThresholdDecisionFact], day: date
) -> LiveReviewThreshold:
    """Fold the decision facts in force on `day` into the live review threshold.

    A stack of approvals over rows with `effective_from_day <= day`, ordered by
    (`effective_from_day`, `decided_at`, `decision_id`): `approved` pushes (with an expiry clock
    when `has_expiry_clock`); `reconfirmed` restarts the top approval's 60-day clock; `reverted`
    pops (a `shadow_check` revert clears the stack back to the starting setting); `expired` pops;
    everything else changes nothing.

    Expiry is stateless: an approval with an expiry clock on top of the stack is popped once `day`
    (or the effective day of the next fact being folded) reaches its `expires_on_day`, repeatedly,
    so a chain of expired approvals unwinds in one read. The `expired` row the daily check writes
    that day records what already happened; a pop that names an approval no longer on the stack is
    a no-op, which keeps the audit row and the stateless pop from counting twice.
    """
    ordered = sorted((fact for fact in facts if fact.effective_from_day <= day), key=_fact_order)
    stack: list[_Entry] = []
    source: LiveSource = "starting_setting"
    changed_on: date | None = None

    def expire_until(on: date) -> None:
        nonlocal source, changed_on
        while stack and stack[-1].loosened and stack[-1].expires_on_day is not None:
            expires = stack[-1].expires_on_day
            if on < expires:
                return
            lapsed = stack.pop()
            source, changed_on = "expired", expires
            # Never ask later because a setting lapsed: an approval beneath that would ask later
            # in either dimension than the one that lapsed goes too. With the fourteen-point grid
            # a lower approval always lapses first, so this only guards the invariant.
            while stack and stack[-1].threshold.looser_than(lapsed.threshold):
                stack.pop()

    def pop(fact: ThresholdDecisionFact) -> bool:
        if not stack:
            return False
        if fact.ends_approval_id is None:
            stack.pop()
            return True
        ids = [entry.fact.decision_id for entry in stack]
        if fact.ends_approval_id not in ids:
            return False
        del stack[ids.index(fact.ends_approval_id) :]
        return True

    for fact in ordered:
        if fact.kind is ReviewThresholdDecisionKind.RECONFIRMED:
            # A reconfirmation is decided while the approval is still live and takes effect the
            # next day. Expiry is checked as of the day it was decided, so reconfirming on the last
            # live day keeps the approval rather than recording a promise the fold then breaks.
            expire_until(fact.decided_on_day)
        elif fact.kind in _STACK_KINDS:
            expire_until(fact.effective_from_day)
        if fact.kind is ReviewThresholdDecisionKind.APPROVED:
            if fact.after is None:
                continue
            loosened = has_expiry_clock(fact.previous, fact.after)
            stack.append(
                _Entry(
                    fact=fact,
                    threshold=fact.after,
                    loosened=loosened,
                    expires_on_day=(
                        fact.effective_from_day + timedelta(days=LOOSENED_EXPIRY_DAYS)
                        if loosened
                        else None
                    ),
                )
            )
            source, changed_on = "approved", fact.effective_from_day
        elif fact.kind is ReviewThresholdDecisionKind.RECONFIRMED:
            if stack and stack[-1].loosened:
                top = stack[-1]
                # Exactly the approval it names: a reconfirmation never restarts another clock.
                if fact.affects_decision_id == top.fact.decision_id:
                    top.expires_on_day = fact.effective_from_day + timedelta(
                        days=LOOSENED_EXPIRY_DAYS
                    )
        elif fact.kind is ReviewThresholdDecisionKind.REVERTED:
            if fact.revert_trigger is ReviewThresholdRevertTrigger.SHADOW_CHECK:
                if stack:
                    stack.clear()
                    source, changed_on = "reverted", fact.effective_from_day
            elif pop(fact):
                source, changed_on = "reverted", fact.effective_from_day
        elif fact.kind is ReviewThresholdDecisionKind.EXPIRED and pop(fact):
            source, changed_on = "expired", fact.effective_from_day
    expire_until(day)

    if not stack:
        return LiveReviewThreshold(
            threshold=DEFAULT_REVIEW_THRESHOLD,
            source=source,
            approval_id=None,
            loosened=False,
            effective_from_day=changed_on,
            expires_on_day=None,
        )
    top = stack[-1]
    return LiveReviewThreshold(
        threshold=top.threshold,
        source=source,
        approval_id=top.fact.decision_id,
        loosened=top.loosened,
        effective_from_day=changed_on,
        expires_on_day=top.expires_on_day,
    )


def cooldown_until(facts: Sequence[ThresholdDecisionFact]) -> date | None:
    """The first day a loosening may be proposed again, from the latest change decision.

    `None` when no approval, revert or expiry has ever been recorded. The cooldown binds while
    `today < cooldown_until(...)`, and it binds loosening proposals only.
    """
    changes = [fact for fact in facts if fact.kind in CHANGE_KINDS]
    if not changes:
        return None
    latest = max(fact.decided_on_day for fact in changes)
    return latest + timedelta(days=COOLDOWN_DAYS)


def reverted_away_values(facts: Sequence[ThresholdDecisionFact]) -> frozenset[ReviewThreshold]:
    """Every value Care+ reverted away from: what each `reverted` row records as before, and
    the value every approval it ended held -- a revert that ends several stacked approvals at
    once reverts away from each of them, not only from the value that was live."""
    approvals = {
        fact.decision_id: fact
        for fact in facts
        if fact.kind is ReviewThresholdDecisionKind.APPROVED and fact.after is not None
    }
    values: set[ReviewThreshold] = set()
    for fact in facts:
        if fact.kind is not ReviewThresholdDecisionKind.REVERTED:
            continue
        values.add(fact.previous)
        ended = approvals.get(fact.ends_approval_id or "")
        if ended is not None and ended.after is not None:
            values.add(ended.after)
    return frozenset(values)


def blocked_threshold_values(facts: Sequence[ThresholdDecisionFact]) -> frozenset[ReviewThreshold]:
    """Values a loosening may not propose again: rejected by a coordinator, or reverted away from
    (`reverted_away_values`).

    A system rejection (`consent_withdrawn`, `superseded`) says nothing about the value itself.
    """
    blocked: set[ReviewThreshold] = set(reverted_away_values(facts))
    for fact in facts:
        if (
            fact.kind is ReviewThresholdDecisionKind.REJECTED
            and fact.after is not None
            and fact.rejection_reason not in SYSTEM_REJECTION_REASONS
        ):
            blocked.add(fact.after)
    return frozenset(blocked)


# ── False alarms ──────────────────────────────────────────────────────────────────────────────

# Rejections the system records on a coordinator's behalf; never a judgement of the value.
SYSTEM_REJECTION_REASONS = frozenset(
    {
        ReviewThresholdRejectionReason.CONSENT_WITHDRAWN,
        ReviewThresholdRejectionReason.SUPERSEDED,
    }
)

FALSE_ALARM_REASONS = frozenset(
    {OverrideReason.NOT_A_CONCERN, OverrideReason.KNOWN_CONTEXT, OverrideReason.DATA_DOUBT}
)


def is_false_alarm(
    status: CaseStatus | str,
    human_action: HumanAction | str | None,
    override_reason: OverrideReason | str | None,
) -> bool:
    """A coordinator resolved the case by overriding it for a false-alarm reason.

    `recent_contact` and `other` are not false alarms (the first says outreach already happened,
    the second says nothing countable); acknowledgements, holds and system closures are not either.
    """
    return (
        status == CaseStatus.RESOLVED
        and human_action == HumanAction.OVERRIDE
        and override_reason is not None
        and override_reason in FALSE_ALARM_REASONS
    )


# ── Structural guardrail ──────────────────────────────────────────────────────────────────────

_CAUSE_NAMES = ", ".join(cause.value for cause in ReviewThresholdCause)

VIOLATION_CAUSE_REQUIRED = f"Name exactly one cause from: {_CAUSE_NAMES}."
VIOLATION_OFF_GRID = (
    f"A review setting must be between {MIN_SEVERITY_PCT}% and {MAX_SEVERITY_PCT}% in steps of "
    f"{SEVERITY_STEP_PCT}%, and between {MIN_PERSISTENCE_DAYS} and {MAX_PERSISTENCE_DAYS} days; "
    f"below {DEFAULT_REVIEW_THRESHOLD.severity_pct}% it must stay at "
    f"{DEFAULT_REVIEW_THRESHOLD.persistence_days} days."
)
VIOLATION_NOT_ONE_STEP = (
    f"A change must move exactly one of the two settings by exactly one step "
    f"({SEVERITY_STEP_PCT}% or {PERSISTENCE_STEP_DAYS} day); propose no change instead of "
    "restating the current setting."
)
VIOLATION_COOLDOWN = (
    f"This person's review setting changed within the last {COOLDOWN_DAYS} days; a looser setting "
    "cannot be proposed until that cooldown ends."
)
VIOLATION_CITATIONS = (
    "Cite at least one piece of evidence, using only evidence IDs returned for this person."
)
VIOLATION_REPEATED_VALUE = (
    "This value was already rejected, or reverted away from, for this person; do not propose it "
    "again."
)
VIOLATION_LOOSEN_CAUSE = (
    f"Only the cause {ReviewThresholdCause.TOO_TIGHT_FOR_PERSON.value} can justify a looser review "
    "setting."
)
VIOLATION_LOOSEN_REASON = (
    "A looser review setting needs the coordinator's structured reason "
    f"'{OverrideReason.NOT_A_CONCERN.value}'; notes cannot unlock it."
)


@dataclass(frozen=True)
class ThresholdVerdict:
    """Approved, or exactly what is wrong. Mirrors `agent.models.GuardrailVerdict`."""

    approved: bool
    violations: tuple[str, ...] = ()

    def as_feedback(self, tool_name: str = "propose_threshold_change") -> str:
        """Render violations as instruction text the calibrator can act on next iteration.
        `tool_name` is the submission tool to call again (the write-up task has its own)."""
        if self.approved:
            return "Approved."
        numbered = "\n".join(f"{index}. {text}" for index, text in enumerate(self.violations, 1))
        return (
            "REJECTED by the deterministic safety gate. Fix every point and call "
            f"{tool_name} again:\n{numbered}"
        )


def _parse_cause(cause: ReviewThresholdCause | str | None) -> ReviewThresholdCause | None:
    if cause is None:
        return None
    try:
        return ReviewThresholdCause(cause)
    except ValueError:
        return None


def is_single_step(previous: ReviewThreshold, proposed: ReviewThreshold) -> bool:
    severity_delta = abs(proposed.severity_pct - previous.severity_pct)
    persistence_delta = abs(proposed.persistence_days - previous.persistence_days)
    return (severity_delta == SEVERITY_STEP_PCT and persistence_delta == 0) or (
        severity_delta == 0 and persistence_delta == PERSISTENCE_STEP_DAYS
    )


def validate_threshold_structure(
    *,
    live: ReviewThreshold,
    proposed: ReviewThreshold | None,
    cause: ReviewThresholdCause | str | None,
    cited_evidence_ids: Sequence[str],
    known_evidence_ids: Collection[str],
    coordinator_reason: OverrideReason | str | None,
    facts: Sequence[ThresholdDecisionFact],
    today: date,
    blocked_values: Collection[ReviewThreshold] | None = None,
    require_cause: bool = True,
) -> ThresholdVerdict:
    """Guardrail rules 1-8 (rule 9, wording, lives in `agent/threshold_guardrails.py`).

    `proposed=None` is a no-change output: the change rules (2, 3, 4, 6, 7, 8) do not apply to it.
    Rules 4 (cooldown) and 6 (repeated value) bind **loosening** proposals only; a proposal that
    restores human attention is never blocked by either, and still needs a coordinator's approval.
    `blocked_values` defaults to `blocked_threshold_values(facts)`. `require_cause=False` is for
    the fixed-rule proposer's cause-less outputs ("waits for a second false alarm", tightening); a
    cause that is given must still be one of the four.
    """
    violations: list[str] = []
    parsed_cause = _parse_cause(cause)
    # Rule 1.
    if (cause is not None or require_cause) and parsed_cause is None:
        violations.append(VIOLATION_CAUSE_REQUIRED)
    if proposed is not None:
        # Rule 2.
        if not proposed.is_allowed:
            violations.append(VIOLATION_OFF_GRID)
        # Rule 3.
        if not is_single_step(live, proposed):
            violations.append(VIOLATION_NOT_ONE_STEP)
    loosening = proposed is not None and proposed.looser_than(live)
    # Rule 4.
    if loosening:
        until = cooldown_until(facts)
        if until is not None and today < until:
            violations.append(VIOLATION_COOLDOWN)
    # Rule 5.
    known = set(known_evidence_ids)
    if not cited_evidence_ids or any(cited not in known for cited in cited_evidence_ids):
        violations.append(VIOLATION_CITATIONS)
    if loosening and proposed is not None:
        # Rule 6.
        blocked = blocked_threshold_values(facts) if blocked_values is None else blocked_values
        if proposed in blocked:
            violations.append(VIOLATION_REPEATED_VALUE)
        # Rule 7.
        if parsed_cause is not ReviewThresholdCause.TOO_TIGHT_FOR_PERSON:
            violations.append(VIOLATION_LOOSEN_CAUSE)
        # Rule 8.
        if coordinator_reason is None or coordinator_reason != OverrideReason.NOT_A_CONCERN:
            violations.append(VIOLATION_LOOSEN_REASON)
    return ThresholdVerdict(approved=not violations, violations=tuple(violations))


# ── Fixed-rule proposer ───────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FalseAlarmRef:
    """One false-alarm review the fixed rule may count and cite.

    `opened_day` is the case's opening day (the false-alarm day); `evidence_ids` are that case's
    decision evidence IDs.
    """

    review_id: str
    opened_day: date
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class FixedRuleOutput:
    output_kind: ReviewThresholdOutputKind
    proposed: ReviewThreshold | None
    cause: ReviewThresholdCause | None
    reasoning: str
    cited: tuple[str, ...]


FIXED_RULE_KNOWN_CONTEXT = (
    "The coordinator resolved this review as explained by known context. A one-off event is not "
    "a reason to change when Care+ asks for a human, so the review setting stays as it is."
)
FIXED_RULE_DATA_DOUBT = (
    "The coordinator resolved this review as doubtful tracker data. Unreliable readings are not a "
    "reason to change when Care+ asks for a human, so the review setting stays as it is."
)
FIXED_RULE_WAITS_FOR_SECOND = (
    f"The coordinator marked this review as not a concern for this person. The fixed rule waits "
    f"for {FIXED_RULE_FALSE_ALARMS} such reviews within {FIXED_RULE_WINDOW_DAYS} days before "
    "proposing any change, so the review setting stays as it is for now."
)
FIXED_RULE_NO_REASON = (
    "This review was not resolved as a false alarm for this person, so the review setting stays "
    "as it is."
)
FIXED_RULE_NOTHING_LEFT = (
    "Coordinators have marked recent reviews as not a concern for this person, but every "
    "one-step looser setting is outside the allowed range or was already rejected or reverted, so "
    "the review setting stays as it is."
)
FIXED_RULE_ROUND_ENDED = (
    "The coordinator rejected the previous proposal for a reason other than preferring the other "
    "change, so this round ends without a change."
)
FIXED_RULE_TIGHTEN_AT_MINIMUM = (
    f"A review reached the coordinator later than it should have, but the review setting is "
    f"already at the lowest allowed shortfall of {MIN_SEVERITY_PCT}%, so it stays as it is."
)


def _fixed_rule_loosen_reasoning(
    alarms: int, live: ReviewThreshold, proposed: ReviewThreshold
) -> str:
    if proposed.persistence_days != live.persistence_days:
        change = (
            f"wait {proposed.persistence_days} valid-wear days instead of "
            f"{live.persistence_days} before asking"
        )
    else:
        change = f"ask at a {proposed.severity_pct}% shortfall instead of {live.severity_pct}%"
    return (
        f"Coordinators marked {alarms} reviews within {FIXED_RULE_WINDOW_DAYS} days as not a "
        f"concern for this person. The fixed rule proposes one step: {change}. A drop of "
        f"{ABSOLUTE_REVIEW_FLOOR.severity_pct}% or more for "
        f"{ABSOLUTE_REVIEW_FLOOR.persistence_days} low days still always asks, Care+ still "
        f"asks if the starting setting would have asked {SHADOW_GRACE_DAYS} days earlier, and "
        "a coordinator must approve the change."
    )


def _fixed_rule_tighten_reasoning(live: ReviewThreshold, proposed: ReviewThreshold) -> str:
    if proposed.persistence_days != live.persistence_days:
        change = (
            f"ask after {proposed.persistence_days} valid-wear days instead of "
            f"{live.persistence_days}"
        )
    else:
        change = f"ask at a {proposed.severity_pct}% shortfall instead of {live.severity_pct}%"
    return (
        "A review reached the coordinator later than it should have. The fixed rule proposes one "
        f"step sooner: {change}. A coordinator must approve the change."
    )


def _cite(alarms: Sequence[FalseAlarmRef]) -> tuple[str, ...]:
    cited: list[str] = []
    for alarm in sorted(alarms, key=lambda ref: (ref.opened_day, ref.review_id)):
        for evidence_id in (alarm.review_id, *alarm.evidence_ids):
            if evidence_id not in cited:
                cited.append(evidence_id)
    return tuple(cited)


def _no_change(
    reasoning: str, cause: ReviewThresholdCause | None, cited: tuple[str, ...]
) -> FixedRuleOutput:
    return FixedRuleOutput(
        output_kind=ReviewThresholdOutputKind.NO_CHANGE,
        proposed=None,
        cause=cause,
        reasoning=reasoning,
        cited=cited,
    )


def _step(live: ReviewThreshold, dimension: Literal["persistence", "severity"]) -> ReviewThreshold:
    if dimension == "persistence":
        return ReviewThreshold(live.severity_pct, live.persistence_days + PERSISTENCE_STEP_DAYS)
    return ReviewThreshold(live.severity_pct + SEVERITY_STEP_PCT, live.persistence_days)


def fixed_rule_output(
    *,
    live: ReviewThreshold,
    trigger_reason: OverrideReason | None,
    trigger: FalseAlarmRef,
    not_a_concern_alarms: Sequence[FalseAlarmRef],
    today: date,
    blocked_values: Collection[ReviewThreshold],
    round_rejection: ReviewThresholdRejectionReason | None = None,
    rejected_proposal: ReviewThreshold | None = None,
) -> FixedRuleOutput:
    """The deterministic calibrator (spec section 6).

    - `known_context` -> no change, `one_off_event`; `data_doubt` -> no change, `bad_data`.
    - `not_a_concern` with fewer than `FIXED_RULE_FALSE_ALARMS` not-a-concern false alarms opened
      in `[today - 29, today]` -> no change, no cause (waits for a second).
    - Otherwise loosen by one step: persistence +1 day, else severity +5% (once persistence is at
      its maximum, or when the +1 day value is blocked), skipping `blocked_values`; nothing left
      -> no change. Cause `too_tight_for_person`; cites the counted reviews and their cases'
      decision evidence.
    - A retry after a rejection (`round_rejection` set): `prefer_other_change` tries the other
      dimension from `rejected_proposal`; any other reason ends the round with no change.
    - Any other trigger reason loosens nothing, whatever the note says.

    `not_a_concern_alarms` is authoritative: the caller decides which alarms count (the repository
    counts only cases opened since the live setting took effect), and the trigger is never added
    back on top. The trigger is cited on its own only when no counted alarm is in the window.

    The output is a candidate, not a decision: it goes through `validate_threshold_output` before
    it is stored, and a coordinator approves any change.
    """
    trigger_cited = _cite([trigger])
    if trigger_reason == OverrideReason.KNOWN_CONTEXT:
        return _no_change(
            FIXED_RULE_KNOWN_CONTEXT, ReviewThresholdCause.ONE_OFF_EVENT, trigger_cited
        )
    if trigger_reason == OverrideReason.DATA_DOUBT:
        return _no_change(FIXED_RULE_DATA_DOUBT, ReviewThresholdCause.BAD_DATA, trigger_cited)
    if trigger_reason != OverrideReason.NOT_A_CONCERN:
        return _no_change(FIXED_RULE_NO_REASON, None, trigger_cited)

    window_start = today - timedelta(days=FIXED_RULE_WINDOW_DAYS - 1)
    in_window = [
        alarm for alarm in not_a_concern_alarms if window_start <= alarm.opened_day <= today
    ]
    cited = _cite(in_window) or trigger_cited

    if round_rejection is not None:
        if (
            round_rejection is not ReviewThresholdRejectionReason.PREFER_OTHER_CHANGE
            or rejected_proposal is None
        ):
            return _no_change(FIXED_RULE_ROUND_ENDED, None, cited)
        other: Literal["persistence", "severity"] = (
            "severity"
            if rejected_proposal.persistence_days != live.persistence_days
            else "persistence"
        )
        dimensions: tuple[Literal["persistence", "severity"], ...] = (other,)
    else:
        if len(in_window) < FIXED_RULE_FALSE_ALARMS:
            return _no_change(FIXED_RULE_WAITS_FOR_SECOND, None, cited)
        dimensions = ("persistence", "severity")

    for dimension in dimensions:
        candidate = _step(live, dimension)
        if candidate.is_allowed and candidate not in blocked_values:
            return FixedRuleOutput(
                output_kind=ReviewThresholdOutputKind.PROPOSAL,
                proposed=candidate,
                cause=ReviewThresholdCause.TOO_TIGHT_FOR_PERSON,
                reasoning=_fixed_rule_loosen_reasoning(len(in_window), live, candidate),
                cited=cited,
            )
    return _no_change(FIXED_RULE_NOTHING_LEFT, None, cited)


def fixed_rule_tightening(*, live: ReviewThreshold, trigger: FalseAlarmRef) -> FixedRuleOutput:
    """One step stricter; no cause. Proposed after a late review with nothing loosened live.

    On the loosening side with more than three days, one day fewer; otherwise 5% lower, floored at
    the grid minimum (a mixed setting such as 35%/4 days is off the grid). `trigger` is the
    reached-too-late review, cited as the evidence. Tightening is never blocked by the cooldown or
    the repeat rule, and still needs approval.
    """
    cited = _cite([trigger])
    if live.persistence_days > MIN_PERSISTENCE_DAYS:
        proposed = ReviewThreshold(live.severity_pct, live.persistence_days - PERSISTENCE_STEP_DAYS)
    elif live.severity_pct - SEVERITY_STEP_PCT < MIN_SEVERITY_PCT:
        return _no_change(FIXED_RULE_TIGHTEN_AT_MINIMUM, None, cited)
    else:
        proposed = ReviewThreshold(live.severity_pct - SEVERITY_STEP_PCT, live.persistence_days)
    return FixedRuleOutput(
        output_kind=ReviewThresholdOutputKind.PROPOSAL,
        proposed=proposed,
        cause=None,
        reasoning=_fixed_rule_tighten_reasoning(live, proposed),
        cited=cited,
    )


# ── Reverts that never ask later ──────────────────────────────────────────────────────────────


def never_later(candidate: ReviewThreshold, than: ReviewThreshold) -> bool:
    """`candidate` asks no later than `than` in either dimension."""
    return (
        candidate.severity_pct <= than.severity_pct
        and candidate.persistence_days <= than.persistence_days
    )


def asks_sooner(candidate: ReviewThreshold, than: ReviewThreshold) -> bool:
    """Never later in either dimension, and strictly sooner in at least one."""
    return never_later(candidate, than) and candidate != than


def pending_revert_fact(
    approval_id: str,
    previous: ReviewThreshold,
    *,
    today: date,
    decided_at: datetime,
    trigger: ReviewThresholdRevertTrigger = ReviewThresholdRevertTrigger.REACHED_TOO_LATE,
) -> ThresholdDecisionFact:
    """A not-yet-written revert ending `approval_id` from tomorrow, to ask the fold "what then"."""
    return ThresholdDecisionFact(
        decision_id=f"pending_{approval_id}",
        kind=ReviewThresholdDecisionKind.REVERTED,
        previous=previous,
        after=None,
        decided_on_day=today,
        effective_from_day=today + timedelta(days=1),
        decided_at=decided_at,
        revert_trigger=trigger,
        ends_approval_id=approval_id,
    )


@dataclass(frozen=True)
class RevertPlan:
    """End every approval in `ends` from tomorrow; Care+ then asks at `restored`.

    `ends` is top-down: each approval on tomorrow's stack above (and including) the lowest one that
    must go, with the value it held. Every one gets its own ending row, so no approval -- a pending
    one included -- ever silently disappears from the fold. `previous` is today's live value.
    """

    ends: tuple[tuple[str, ReviewThreshold], ...]
    previous: ReviewThreshold
    restored: ReviewThreshold

    @property
    def ends_approval_id(self) -> str:
        """The lowest approval ended -- the one whose ending decides `restored`."""
        return self.ends[-1][0]


@dataclass(frozen=True)
class RevertSkipped:
    """A reached-too-late mark that finds nowhere safe to go back to. Audited, never silent."""

    reason: Literal["no_setting_asks_sooner", "pending_change"]


def _componentwise_min(first: ReviewThreshold, second: ReviewThreshold) -> ReviewThreshold:
    return ReviewThreshold(
        min(first.severity_pct, second.severity_pct),
        min(first.persistence_days, second.persistence_days),
    )


def reached_too_late_revert(
    facts: Sequence[ThresholdDecisionFact],
    *,
    today: date,
    decided_at: datetime,
    trigger: ReviewThresholdRevertTrigger = ReviewThresholdRevertTrigger.REACHED_TOO_LATE,
) -> RevertPlan | RevertSkipped | None:
    """Where "this should have reached me sooner" goes back to.

    The target to beat is the componentwise minimum of today's live value and tomorrow's value as
    already decided (an approval or revert pending for tomorrow, or an expiry): the restored value
    must ask no later than either, and sooner than that minimum in at least one dimension.

    Walks tomorrow's stack from the top: ending an approval restores whatever the fold has beneath
    it (the starting setting beneath the bottom one, which counts only if it passes the same test).
    The first qualifying point is the lowest approval ended; every approval above it is ended
    explicitly too.

    The same walk serves every revert that must never ask later (stage 3 reuses it for
    `far_more_severe`); `trigger` names which one, and only a revert of the same trigger already
    decided today makes a second one a no-op.

    `None` when today's live setting carries no expiry clock (nothing loosened -- a looser
    approval pending for tomorrow is the repository's to end). `RevertSkipped("pending_change")`
    when a change already decided for tomorrow asks sooner than today and nothing asks sooner
    still, or when a reached-too-late revert was already decided today (a second mark never walks a
    step further); `RevertSkipped("no_setting_asks_sooner")` otherwise.
    """
    live = resolve_live_threshold(facts, today)
    if live.approval_id is None or not live.loosened:
        return None
    if any(
        fact.kind is ReviewThresholdDecisionKind.REVERTED
        and fact.revert_trigger is trigger
        and fact.decided_on_day == today
        for fact in facts
    ):
        # A second mark the same day: the first already decided where tomorrow goes back to.
        # Walking again would ratchet a step further for the same late review.
        return RevertSkipped("pending_change")
    tomorrow = today + timedelta(days=1)
    pending = resolve_live_threshold(facts, tomorrow)
    target = _componentwise_min(live.threshold, pending.threshold)
    visited: list[tuple[str, ReviewThreshold]] = []
    candidate: str | None = pending.approval_id
    candidate_value = pending.threshold
    while candidate is not None and candidate not in {approval for approval, _ in visited}:
        visited.append((candidate, candidate_value))
        trial = resolve_live_threshold(
            [
                *facts,
                pending_revert_fact(
                    candidate,
                    candidate_value,
                    today=today,
                    decided_at=decided_at,
                    trigger=trigger,
                ),
            ],
            tomorrow,
        )
        if asks_sooner(trial.threshold, target):
            return RevertPlan(
                ends=tuple(visited), previous=live.threshold, restored=trial.threshold
            )
        candidate, candidate_value = trial.approval_id, trial.threshold
    if (pending.threshold, pending.approval_id) != (
        live.threshold,
        live.approval_id,
    ) and asks_sooner(pending.threshold, live.threshold):
        return RevertSkipped("pending_change")
    return RevertSkipped("no_setting_asks_sooner")


def approval_stack(
    facts: Sequence[ThresholdDecisionFact], *, today: date, decided_at: datetime
) -> tuple[tuple[str, ReviewThreshold], ...]:
    """Every approval on today's live stack with the value it holds, top first.

    What a `shadow_check` revert clears. Each is ended with its own row so every value the person
    was held at counts as reverted away from (`reverted_away_values`), not only the top one.
    """
    stack: list[tuple[str, ReviewThreshold]] = []
    cursor = list(facts)
    current = resolve_live_threshold(cursor, today)
    while current.approval_id is not None and current.approval_id not in dict(stack):
        stack.append((current.approval_id, current.threshold))
        cursor.append(
            ThresholdDecisionFact(
                decision_id=f"pending_clear_{current.approval_id}",
                kind=ReviewThresholdDecisionKind.REVERTED,
                previous=current.threshold,
                after=None,
                decided_on_day=today,
                effective_from_day=today,
                decided_at=decided_at,
                revert_trigger=ReviewThresholdRevertTrigger.REACHED_TOO_LATE,
                ends_approval_id=current.approval_id,
            )
        )
        current = resolve_live_threshold(cursor, today)
    return tuple(stack)


# ── Checking afterwards (stage 3) ─────────────────────────────────────────────────────────────


def checking_until(approval: ThresholdDecisionFact) -> date:
    """The day a loosening's checking period closes: `CHECKING_PERIOD_DAYS` after it took effect."""
    return approval.effective_from_day + timedelta(days=CHECKING_PERIOD_DAYS)


def within_checking_period(approval: ThresholdDecisionFact, day: date) -> bool:
    return approval.effective_from_day <= day < checking_until(approval)


def far_more_severe(delta_percent: float, *, reached_floor: bool) -> bool:
    """A case that opened at least `FAR_MORE_SEVERE_PCT` below baseline, or through the floor."""
    return reached_floor or abs(min(0.0, delta_percent)) >= FAR_MORE_SEVERE_PCT


# What the approved change did not allow for, in plain words -- no rung names.
_WRITE_UP_UNANTICIPATED: dict[ReviewThresholdRevertTrigger, str] = {
    ReviewThresholdRevertTrigger.REACHED_TOO_LATE: (
        "a coordinator said a case should have reached them sooner"
    ),
    ReviewThresholdRevertTrigger.FAR_MORE_SEVERE: (
        "a much deeper decline opened a case within two weeks of the change"
    ),
    ReviewThresholdRevertTrigger.SHADOW_CHECK: (
        "the starting setting would have asked a coordinator three days earlier"
    ),
}


def describe_setting(threshold: ReviewThreshold) -> str:
    """The Care Team card's phrasing of a setting."""
    return (
        f"more than {threshold.severity_pct}% below usual for at least "
        f"{threshold.persistence_days} low days"
    )


def fixed_write_up_text(
    *,
    trigger: ReviewThresholdRevertTrigger,
    previous: ReviewThreshold,
    restored: ReviewThreshold,
) -> str:
    """The write-up used when the agent is off or its text is refused. Fixed, coordinator-facing:
    what changed, what the approved change did not allow for, and that Care+ will not suggest
    that looser setting again. Pinned against the coordinator wording rule in the tests."""
    return (
        f"Care+ again asks a coordinator when activity is {describe_setting(restored)}, "
        f"instead of {describe_setting(previous)}. The approved change did not allow for what "
        f"happened next: {_WRITE_UP_UNANTICIPATED[trigger]}. Care+ will not suggest that "
        "looser setting for this person again."
    )


# ── Senior notice ─────────────────────────────────────────────────────────────────────────────

# Fixed wording, second person, no figures and none of the coordinator vocabulary the senior
# surface forbids (pinned against the e2e regex in `tests/test_review_threshold.py`).
SENIOR_NOTICE_LATER = (
    "Your care team has changed when Care+ lets them know about a quieter stretch. Because "
    "your activity naturally varies from week to week, Care+ will now wait a little longer "
    "before letting them know."
)
SENIOR_NOTICE_SOONER = (
    "Your care team has changed when Care+ lets them know about a quieter stretch. "
    "Care+ will now let them know a little sooner again, as it did before."
)
SENIOR_NOTICE_MESSAGES: dict[ReviewThresholdNoticeKind, str] = {
    ReviewThresholdNoticeKind.LATER: SENIOR_NOTICE_LATER,
    ReviewThresholdNoticeKind.SOONER: SENIOR_NOTICE_SOONER,
}


def _notice_kind(fact: ThresholdDecisionFact) -> ReviewThresholdNoticeKind | None:
    """Which way the change moved, compared with the value it replaced.

    Deliberately not `has_expiry_clock`: 40%/4 days -> 35%/4 days carries a clock (it still waits
    longer than the starting setting) but asks sooner than before, so telling the person Care+
    "will now wait a little longer" would be false.
    """
    if fact.after is None:
        return None
    if fact.kind is ReviewThresholdDecisionKind.APPROVED and fact.after.looser_than(fact.previous):
        return ReviewThresholdNoticeKind.LATER
    if fact.kind in (
        ReviewThresholdDecisionKind.REVERTED,
        ReviewThresholdDecisionKind.EXPIRED,
    ) and fact.after.stricter_than(fact.previous):
        return ReviewThresholdNoticeKind.SOONER
    return None


def senior_notice_for(
    facts: Sequence[ThresholdDecisionFact], current_day: date
) -> ReviewThresholdNotice | None:
    """The notice the senior sees on `current_day`, if any.

    Taken from the latest change decision (approved, reverted or expired) decided on or before
    `current_day`: a loosening approval gives `later`, a revert or expiry that asks sooner gives
    `sooner`, for `SENIOR_NOTICE_DAYS` days from its decision day. An approved tightening, or a
    later change that superseded a notice-worthy one, gives nothing -- a stale "later" must never
    outlive the change that made it true. No server-side dismissal.
    """
    changes = [
        fact for fact in facts if fact.kind in CHANGE_KINDS and fact.decided_on_day <= current_day
    ]
    if not changes:
        return None
    latest = max(changes, key=lambda fact: (fact.decided_on_day, fact.decided_at, fact.decision_id))
    kind = _notice_kind(latest)
    if kind is None:
        return None
    if latest.ends_approval_id is not None:
        ended = next((fact for fact in facts if fact.decision_id == latest.ends_approval_id), None)
        # A revert of an approval that never became live (approved and marked "too late" the same
        # day) changed nothing the senior was ever told about, so it tells them nothing either --
        # and it supersedes the approval's own "later" notice.
        if ended is not None and ended.effective_from_day > latest.decided_on_day:
            return None
    if current_day >= latest.decided_on_day + timedelta(days=SENIOR_NOTICE_DAYS):
        return None
    return ReviewThresholdNotice(
        notice_id=latest.decision_id,
        kind=kind,
        message=SENIOR_NOTICE_MESSAGES[kind],
        shown_from_day=latest.decided_on_day,
    )


def senior_notice_if_approved(
    *,
    notice_id: str,
    previous: ReviewThreshold,
    proposed: ReviewThreshold,
    current_day: date,
) -> ReviewThresholdNotice | None:
    """The notice approving `previous -> proposed` today would show the senior, if any.

    The same rule `senior_notice_for` applies to an `approved` decision: a loosening gives
    `later`; an approved tightening tells the senior nothing. Read-only preview for the Care Team
    card; `notice_id` is the proposal's id, since no decision exists yet.
    """
    if not proposed.looser_than(previous):
        return None
    return ReviewThresholdNotice(
        notice_id=notice_id,
        kind=ReviewThresholdNoticeKind.LATER,
        message=SENIOR_NOTICE_MESSAGES[ReviewThresholdNoticeKind.LATER],
        shown_from_day=current_day,
    )
