"""A parameterised copy of the deterministic ladder, for gate ablation ONLY.

`silverloop.policy.decide` is an invariant: it is never edited, never monkeypatched and never
imported-and-mutated by this package. To answer "which of Care+'s gates is actually
load-bearing?" the harness therefore keeps its own transcription of the ladder here, with one
boolean per gate.

The transcription is not trusted on faith. `test_evaluation.py::
test_full_ladder_is_identical_to_the_real_policy` folds `make_ladder(FULL_LADDER)` and
`silverloop.policy.decide` over every replayed step of every scenario at every contact count and
asserts the two `PolicyResult`s are equal, so drift between this file and `policy.py` fails the
suite rather than silently producing a wrong ablation.

## What "disabling a gate" means, precisely

Most ablations simply delete a guard clause. `severity_persistence` needs a definition,
because that step of the ladder does two jobs at once: it decides *whether* to act at all, and it
decides *which* rung. The ablation removes only the first: with `severity_persistence=False` any
day whose activity is below the person's own median (`severity > 0`) becomes contact-eligible,
instead of requiring a 20% shortfall. The two escalation tiers keep their own thresholds, because
those select an action rather than authorise one; collapsing them too would send every step to
`COORDINATOR_REVIEW` and measure nothing.

## One gate is deliberately not mirrored

`policy.decide` also declines to contact someone who accepted outreach in the last few days
(`ACCEPTED_OUTREACH_COOLDOWN_DAYS`). That gate is absent here, and its absence is not drift.

It fires on `days_since_last_accepted`, which is derived from recorded outcomes -- and the harness
records none: it folds policies over a decision-independent environment stream, so nobody ever
accepts anything. The parameter therefore defaults to `None` on every harness call and the gate
cannot fire, which is why the equivalence test still passes. Transcribing it would add a row to
the ablation table that is dead by construction, and an ablation study that reports a gate it
never exercised is worse than one that says which gate it left out.

The equivalence test is correspondingly narrower than it looks: it proves these two ladders agree
*for the call shape the harness uses*, not that this file is a complete copy of `policy.py`.

`PolicyResult.decided_by` is transcribed here too, rung for rung, for the same reason: the
equivalence test compares whole `PolicyResult`s, so a gate name that drifted from `policy.py`
would fail the suite rather than quietly mislabel an ablation. `PolicyGate.ACCEPTED_COOLDOWN` is
the one value this file never returns, which is the gate it deliberately does not mirror (above).

## The review block: personal threshold, floor, shadow check

`policy.decide`'s review block is three rungs (ADR 0008): the person's own review threshold, the
absolute review floor, and the shadow check. All three are mirrored, with the same two keyword
parameters (`review_threshold`, `shadow_review_since`) and the same defaults, and the equivalence
test folds every one of the fourteen allowed thresholds, with and without a shadow date, at every
contact count. The threshold and the floor are imported from `silverloop.review_threshold` rather
than duplicated -- they are data the policy is parameterised by, not literals of its structure --
while the rationale templates stay transcribed so a wording change in `policy.py` still fails here.

The floor and shadow rungs are deliberately NOT given `LadderConfig` flags. Under the default
threshold, which is the only threshold the harness ever runs, neither can fire (the floor is a
subset of the default and the shadow date is always `None`), so an ablation row for either would
be dead by construction -- the same reason the accepted-outreach cooldown is left out.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import date

from silverloop.models import Decision, PolicyGate, SignalSummary
from silverloop.policy import PolicyResult
from silverloop.review_threshold import (
    ABSOLUTE_REVIEW_FLOOR,
    DEFAULT_REVIEW_THRESHOLD,
    ReviewThreshold,
)

# Mirrors of the literals in `policy.py`. Duplicated deliberately -- see the equivalence test.
CONFIDENCE_FLOOR = 0.45
RAIN_PERSISTENCE_DAYS = 2
# The starting review threshold's two numbers, kept under their historical names. The rung itself
# now reads `review_threshold` (default `DEFAULT_REVIEW_THRESHOLD`), exactly as `policy.py` does.
ESCALATION_DAYS = DEFAULT_REVIEW_THRESHOLD.persistence_days
ESCALATION_SEVERITY = DEFAULT_REVIEW_THRESHOLD.severity_pct
PROGRAMME_DAYS = 2
PROGRAMME_SEVERITY = 25
NUDGE_SEVERITY = 20
MINIMUM_INTERPRETABLE_BASELINE = 500
WEEKLY_CONTACT_CAP = 2
SHADOW_GRACE_DAYS = 3
PERSISTENCE_WORDS = {3: "three", 4: "four", 5: "five"}

GATE_CONSENT = "consent"
GATE_DATA_QUALITY = "data_quality"
GATE_CONFIDENCE = "confidence"
GATE_RAIN_CONTEXT = "rain_context"
GATE_SEVERITY_PERSISTENCE = "severity_persistence"
GATE_CONTACT_CAP = "contact_cap"
GATE_INTERPRETABLE_SCALE = "interpretable_scale"


@dataclass(frozen=True)
class LadderConfig:
    """One flag per gate in the ladder, in the order `policy.py` checks them."""

    consent: bool = True
    data_quality: bool = True
    confidence: bool = True
    rain_context: bool = True
    severity_persistence: bool = True
    interpretable_scale: bool = True
    contact_cap: bool = True


FULL_LADDER = LadderConfig()

GATE_NAMES: tuple[str, ...] = tuple(field.name for field in fields(LadderConfig))

GATE_DESCRIPTIONS: dict[str, str] = {
    GATE_CONSENT: "Inactive consent blocks every outreach decision (SUPPRESS).",
    GATE_DATA_QUALITY: "Wear-time below the 8h minimum yields an audited NO_ACTION.",
    GATE_CONFIDENCE: "Baseline/wear coverage below 0.45 confidence yields NO_ACTION.",
    GATE_RAIN_CONTEXT: "Rain suppresses a dip that has not yet persisted two valid-wear days.",
    GATE_SEVERITY_PERSISTENCE: (
        "A dip must be at least 20% below the personal median before any contact is permitted "
        "(ablation: any dip below the median becomes contact-eligible)."
    ),
    GATE_CONTACT_CAP: "At most two contacts per rolling week; the third is SUPPRESSed.",
    GATE_INTERPRETABLE_SCALE: (
        "A baseline too small for a percentage to mean anything yields NO_ACTION."
    ),
}


def make_ladder(config: LadderConfig) -> Callable[..., PolicyResult]:
    """Build a `Policy`-shaped callable that runs the ladder with `config`'s gates enabled."""

    def decide(
        signal: SignalSummary,
        *,
        consent_active: bool,
        interventions_last_7_days: int,
        review_threshold: ReviewThreshold = DEFAULT_REVIEW_THRESHOLD,
        shadow_review_since: date | None = None,
    ) -> PolicyResult:
        if config.consent and not consent_active:
            return PolicyResult(
                Decision.SUPPRESS,
                0,
                ["Consent is inactive; all outreach is blocked."],
                decided_by=PolicyGate.CONSENT,
            )
        if config.data_quality and not signal.quality.safe_to_interpret:
            return PolicyResult(
                Decision.NO_ACTION,
                0,
                list(signal.quality.reasons),
                decided_by=PolicyGate.DATA_QUALITY,
            )
        if config.confidence and signal.confidence < CONFIDENCE_FLOOR:
            return PolicyResult(
                Decision.NO_ACTION,
                5,
                ["Wear-time or baseline coverage is insufficient for a reliable decision."],
                decided_by=PolicyGate.CONFIDENCE,
            )
        if (
            config.rain_context
            and signal.context.rainy
            and signal.sustained_low_days < RAIN_PERSISTENCE_DAYS
        ):
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
        if (
            config.interpretable_scale
            and 0 < signal.baseline_median_steps < MINIMUM_INTERPRETABLE_BASELINE
        ):
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
        capped = config.contact_cap and interventions_last_7_days >= WEEKLY_CONTACT_CAP

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
        if ABSOLUTE_REVIEW_FLOOR.fires(severity, signal.sustained_low_days):
            return PolicyResult(
                Decision.COORDINATOR_REVIEW,
                80,
                [
                    f"Activity is at least {ABSOLUTE_REVIEW_FLOOR.severity_pct}% below the "
                    "personal baseline for at least "
                    f"{PERSISTENCE_WORDS[ABSOLUTE_REVIEW_FLOOR.persistence_days]} valid-wear days.",
                    "This is Care+'s absolute review floor; it applies whatever this "
                    "person's review setting is.",
                    "A human must review before any higher-touch outreach.",
                ],
                decided_by=PolicyGate.REVIEW_FLOOR,
            )
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
        if signal.sustained_low_days >= PROGRAMME_DAYS and severity >= PROGRAMME_SEVERITY:
            if capped:
                return PolicyResult(
                    Decision.SUPPRESS,
                    15,
                    ["Weekly contact cap reached; notification fatigue guard applied."],
                    decided_by=PolicyGate.CONTACT_CAP,
                )
            return PolicyResult(
                Decision.PROGRAMME_SUGGESTION,
                55,
                [
                    "Activity is at least 25% below the personal baseline for two valid-wear days.",
                    "A nearby low-barrier programme is permitted.",
                ],
                decided_by=PolicyGate.SEVERITY_PERSISTENCE,
            )

        nudge_eligible = severity >= NUDGE_SEVERITY if config.severity_persistence else severity > 0
        if nudge_eligible:
            if capped:
                return PolicyResult(
                    Decision.SUPPRESS,
                    15,
                    ["Weekly contact cap reached; notification fatigue guard applied."],
                    decided_by=PolicyGate.CONTACT_CAP,
                )
            return PolicyResult(
                Decision.GENTLE_NUDGE,
                30,
                [
                    "Activity is below the personal baseline; a single low-pressure nudge "
                    "is permitted."
                ],
                decided_by=PolicyGate.SEVERITY_PERSISTENCE,
            )
        return PolicyResult(
            Decision.NO_ACTION,
            5,
            ["Activity remains within the personal range."],
            decided_by=PolicyGate.WITHIN_RANGE,
        )

    return decide


def ablated_config(gate: str) -> LadderConfig:
    """`FULL_LADDER` with exactly one gate switched off."""
    if gate not in GATE_NAMES:
        raise ValueError(f"Unknown gate {gate!r}; expected one of {GATE_NAMES}")
    return replace(FULL_LADDER, **{gate: False})
