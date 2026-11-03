from dataclasses import dataclass
from datetime import date

from silverloop.context_explanation import EXPLANATION_MAX_SUSTAINED_DAYS, StatedExplanation
from silverloop.models import Decision, PolicyGate, SignalSummary
from silverloop.review_threshold import (
    ABSOLUTE_REVIEW_FLOOR,
    DEFAULT_REVIEW_THRESHOLD,
    PERSISTENCE_WORDS,
    SHADOW_GRACE_DAYS,
    ReviewThreshold,
)

# Below this the baseline is too small for a percentage change to mean anything. See the comment
# at the gate itself.
MINIMUM_INTERPRETABLE_BASELINE = 500

# How many days of quiet a person is owed after they took a suggestion up.
#
# The weekly contact cap counts messages SENT. It cannot see that the last one landed, and the
# person who engages is therefore the person who hears from us most -- exactly backwards. Someone
# who accepted a suggestion two days ago is in the middle of acting on it; another nudge is not
# support, it is supervision. Three days is short enough that a genuine new decline is still
# noticed quickly (a coordinator-review rung is never reached through this gate anyway, because
# it sits with the contact cap, below the severity ladder's top rung).
ACCEPTED_OUTREACH_COOLDOWN_DAYS = 3


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    support_priority: int
    rationale: list[str]
    # Which rung returned this result. `decide` below populates it on every branch; it defaults to
    # `None` only because the evaluation harness's *alternative* policies
    # (`evaluation/baselines.py`) share this result type and have no ladder to name a gate from.
    # Labelling a fixed-step-threshold baseline with one of Care+'s gate names would be a
    # fabricated fact about a policy that never had that gate.
    decided_by: PolicyGate | None = None


def _contact_guard(
    interventions_last_7_days: int,
    days_since_last_accepted: int | None,
) -> PolicyResult | None:
    """The two fatigue guards, checked together wherever outreach would otherwise be sent.

    Returns `None` when neither binds. Both are notification-fatigue rules rather than safety
    gates, which is why they sit at the same rung and share a support priority.
    """
    if interventions_last_7_days >= 2:
        return PolicyResult(
            Decision.SUPPRESS,
            15,
            ["Weekly contact cap reached; notification fatigue guard applied."],
            decided_by=PolicyGate.CONTACT_CAP,
        )
    if (
        days_since_last_accepted is not None
        and days_since_last_accepted < ACCEPTED_OUTREACH_COOLDOWN_DAYS
    ):
        return PolicyResult(
            Decision.SUPPRESS,
            15,
            [
                "This person took up a suggestion within the last few days.",
                "Leaving them space is the least intrusive thing to do; nothing new is sent.",
            ],
            decided_by=PolicyGate.ACCEPTED_COOLDOWN,
        )
    return None


def decide(
    signal: SignalSummary,
    *,
    consent_active: bool,
    interventions_last_7_days: int,
    days_since_last_accepted: int | None = None,
    stated_explanation: StatedExplanation | None = None,
    review_threshold: ReviewThreshold = DEFAULT_REVIEW_THRESHOLD,
    shadow_review_since: date | None = None,
) -> PolicyResult:
    if not consent_active:
        return PolicyResult(
            Decision.SUPPRESS,
            0,
            ["Consent is inactive; all outreach is blocked."],
            decided_by=PolicyGate.CONSENT,
        )
    if not signal.quality.safe_to_interpret:
        return PolicyResult(
            Decision.NO_ACTION,
            0,
            signal.quality.reasons,
            decided_by=PolicyGate.DATA_QUALITY,
        )
    if signal.confidence < 0.45:
        return PolicyResult(
            Decision.NO_ACTION,
            5,
            ["Wear-time or baseline coverage is insufficient for a reliable decision."],
            decided_by=PolicyGate.CONFIDENCE,
        )
    # The person's own account of their week, checked before the weather.
    #
    # Both this gate and the rain gate below return NO_ACTION, so their order changes only which
    # explanation is recorded -- and when someone has told us why their week was quiet, that is the
    # honest thing to put in the audit and on the trace, not a forecast that happened to coincide.
    #
    # The `< EXPLANATION_MAX_SUSTAINED_DAYS` bound is the load-bearing part, and it is the reason
    # this gate is safe to have at all. It is disjoint from the COORDINATOR_REVIEW rung's
    # `>= 3` threshold below, exactly as the rain gate's `< 2` is, so no answer a person can give
    # will stop a sustained, severe decline reaching a human. Deferring a nudge on someone's word is
    # support; declining to involve a human on their word would mean the person this system is
    # concerned about can switch off the concern, and a review that never happens cannot correct it.
    # `tests/test_context_explanation.py` asserts the disjointness rather than trusting this note.
    if (
        stated_explanation is not None
        and signal.sustained_low_days < EXPLANATION_MAX_SUSTAINED_DAYS
    ):
        return PolicyResult(
            Decision.NO_ACTION,
            10,
            [
                stated_explanation.rationale,
                "A quieter reading is expected while that holds; nothing is sent.",
                (
                    f"Explanation given on {stated_explanation.stated_on.isoformat()} and applies "
                    f"through {stated_explanation.explains_through.isoformat()}."
                ),
            ],
            decided_by=PolicyGate.STATED_EXPLANATION,
        )
    if signal.context.rainy and signal.sustained_low_days < 2:
        return PolicyResult(
            Decision.NO_ACTION,
            10,
            [
                "Rain plausibly explains a single-day decline.",
                "The system will observe before acting.",
            ],
            decided_by=PolicyGate.RAIN_CONTEXT,
        )
    # A percentage deviation from a tiny baseline is arithmetic, not evidence. A tracker
    # reporting ~3 steps a day -- a wheelchair user, a bedbound person, a dead accelerometer --
    # produces a -100% delta from a three-step difference, and the ladder would escalate on it.
    # `robust_z` reports that correctly as noise, which is precisely why the scale check belongs
    # here rather than in a z-threshold on every rung: a z-gate would also require people with
    # ERRATIC routines to fall further before being noticed, and variable activity is not a
    # reason to protect someone less.
    #
    # Zero means the field was never populated (a caller predating it), which the data-quality
    # gate already covers -- so only a genuinely small, genuinely present baseline trips this.
    if 0 < signal.baseline_median_steps < MINIMUM_INTERPRETABLE_BASELINE:
        return PolicyResult(
            Decision.NO_ACTION,
            5,
            [
                "This person's typical activity is too low for a percentage change to carry "
                "meaning; the difference is within measurement noise.",
            ],
            decided_by=PolicyGate.SMALL_BASELINE,
        )

    severity = abs(min(0, signal.delta_percent))
    # The review block: three rungs, all COORDINATOR_REVIEW, all above every contact gate.
    #
    # 1. This person's own review threshold (ADR 0008). With the starting setting (40% for three
    #    days) the rationale renders exactly the literal text it replaced.
    if review_threshold.fires(severity, signal.sustained_low_days):
        return PolicyResult(
            Decision.COORDINATOR_REVIEW,
            80,
            [
                f"Activity is more than {review_threshold.severity_pct}% below the personal "
                "baseline.",
                "The decline has persisted for at least "
                f"{PERSISTENCE_WORDS[review_threshold.persistence_days]} valid-wear days.",
                "A human must review before any higher-touch outreach.",
            ],
            decided_by=PolicyGate.SEVERITY_PERSISTENCE,
        )
    # 2. The absolute floor, whatever the person's setting. Every allowed setting asks at 55% or
    #    less, so the floor only adds anything for a setting that waits longer than three days.
    #    Under the default it is unreachable (the floor is a subset of 40%/three days), as is rung
    #    3, so the default ladder decides exactly as it did before these rungs existed.
    if ABSOLUTE_REVIEW_FLOOR.fires(severity, signal.sustained_low_days):
        return PolicyResult(
            Decision.COORDINATOR_REVIEW,
            80,
            [
                f"Activity is at least {ABSOLUTE_REVIEW_FLOOR.severity_pct}% below the personal "
                "baseline for at least "
                f"{PERSISTENCE_WORDS[ABSOLUTE_REVIEW_FLOOR.persistence_days]} valid-wear days.",
                "This is Care+'s absolute review floor; it applies whatever this person's "
                "review setting is.",
                "A human must review before any higher-touch outreach.",
            ],
            decided_by=PolicyGate.REVIEW_FLOOR,
        )
    # 3. The shadow check: the starting setting would have asked on `shadow_review_since` and this
    #    person's looser setting still has not, past the grace period. Computed by the caller
    #    (`review_threshold_replay.shadow_review_since`) from stored history; `decide` stays pure.
    if shadow_review_since is not None:
        return PolicyResult(
            Decision.COORDINATOR_REVIEW,
            80,
            [
                "Care+'s starting review setting would have asked for a human on "
                f"{shadow_review_since.isoformat()}.",
                "This person's own review setting has not asked within the "
                f"{SHADOW_GRACE_DAYS}-day grace period, so a human is asked now.",
                "A human must review before any higher-touch outreach.",
            ],
            decided_by=PolicyGate.SHADOW_CHECK,
        )
    if signal.sustained_low_days >= 2 and severity >= 25:
        if guarded := _contact_guard(interventions_last_7_days, days_since_last_accepted):
            return guarded
        return PolicyResult(
            Decision.PROGRAMME_SUGGESTION,
            55,
            [
                "Activity is at least 25% below the personal baseline for two valid-wear days.",
                "A nearby low-barrier programme is permitted.",
            ],
            decided_by=PolicyGate.SEVERITY_PERSISTENCE,
        )
    if severity >= 20:
        if guarded := _contact_guard(interventions_last_7_days, days_since_last_accepted):
            return guarded
        return PolicyResult(
            Decision.GENTLE_NUDGE,
            30,
            ["Activity is below the personal baseline; a single low-pressure nudge is permitted."],
            decided_by=PolicyGate.SEVERITY_PERSISTENCE,
        )
    return PolicyResult(
        Decision.NO_ACTION,
        5,
        ["Activity remains within the personal range."],
        decided_by=PolicyGate.WITHIN_RANGE,
    )
