"""The arms the ranking benchmark compares: `full`, one arm per named ranking FACTOR, a small
number of honest input manipulations, and the diversity swap.

The distinction between the two kinds of arm is the whole point of this module, and it is the
defect the evaluation review found in its first version:

* a **factor arm** (`factor:<name>`) zeroes exactly one `ScoreFactor`'s weighted CONTRIBUTION to
  `total`, leaves every factor's VALUE (and therefore the tier, the hard filter and the
  environment-aware rain rule) exactly as production computed it, re-sorts on the adjusted totals
  and then re-runs the production post-scoring passes through the public
  `activity_search.postprocess`. Its delta is attributable to that one factor's weight.
* an **input arm** (`input:*`) changes one argument to `rank_candidates_with_breakdown`. That is
  honest and closer to "what if we never had this data", but an input almost never touches exactly
  one factor -- `engagement={}` also zeroes `repetition`, and an empty `ActivityIntent()` also
  re-enables the rain nudge -- so every input arm declares the list of factors it touches and the
  report prints it.

Every arm also declares the arm it is measured AGAINST (`ArmSpec.baseline`). An arm that runs with
the diversity swap off may only be compared to `no_diversity`, never to `full`: comparing it to
`full` silently folds the diversity swap's own delta into the factor's, which is exactly how the
old `no_intent_soft` number (+0.0517 on holdout) came to carry `no_diversity`'s +0.0112 inside it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date

from silverloop.activity_search import (
    RANKING_WEIGHTS,
    ActivityEngagement,
    RankedScore,
    postprocess,
    rank_candidates_with_breakdown,
    sort_key_for,
)
from silverloop.models import (
    ActivityCandidate,
    ActivityIntent,
    ActivityPreferences,
    PreferenceDimension,
    ScoreBreakdown,
)

ARM_FULL = "full"
ARM_NO_DIVERSITY = "no_diversity"
ARM_INPUT_NO_INTENT = "input:no_intent"
ARM_INPUT_NO_ENGAGEMENT = "input:no_engagement"
ARM_INPUT_NO_PREFERENCES = "input:no_preferences"
ARM_COLD_START = "cold_start"
ARM_FIRST_SIGNAL = "first_signal"

TRACE_PREFIX_LENGTHS: tuple[int, ...] = (1, 3, 5)
"""The learning curve's k. `trace_prefix:1` is the same manipulation as `first_signal`; both are
reported, and a test asserts they rank identically -- the duplicate is a check that the prefix
machinery does what its name says, not an oversight."""


def trace_prefix_arm(events: int) -> str:
    return f"trace_prefix:{events}"


FACTOR_NAMES: tuple[str, ...] = tuple(RANKING_WEIGHTS)
"""`intent`, `preference`, `engagement`, `repetition`, `context`, `friction` -- read from the
production weight table rather than restated here, so a new factor gets an arm automatically."""


def factor_arm(name: str) -> str:
    return f"factor:{name}"


def preference_dimension_arm(dimension: PreferenceDimension) -> str:
    return f"no_preference_dim:{dimension.value}"


@dataclass(frozen=True)
class ArmSpec:
    """One arm: how it is built, what it touches and what it is measured against."""

    name: str
    kind: str
    """`full` | `factor` | `input` | `preference_dimension` | `diversity`."""
    baseline: str
    diversity: bool
    """Whether the arm runs the production diversity swap. An arm with the swap off is only
    comparable to `no_diversity`."""
    touches: tuple[str, ...]
    """The `ScoreFactor` names this arm's manipulation can move. A factor arm touches exactly
    one, by construction; an input arm declares its confound instead of hiding it."""
    description: str
    factor: str | None = None
    dimension: PreferenceDimension | None = None
    trace_events: int | None = None


def _factor_spec(name: str) -> ArmSpec:
    return ArmSpec(
        name=factor_arm(name),
        kind="factor",
        baseline=ARM_FULL,
        diversity=True,
        touches=(name,),
        factor=name,
        description=(
            f"Zeroes only the `{name}` factor's weighted contribution to `total`, leaving every "
            "factor VALUE (and so the tier, the hard filter and the rain rule) untouched, then "
            "re-runs the production post-scoring passes."
        ),
    )


def _dimension_spec(dimension: PreferenceDimension) -> ArmSpec:
    return ArmSpec(
        name=preference_dimension_arm(dimension),
        kind="preference_dimension",
        baseline=ARM_FULL,
        diversity=True,
        touches=("preference",),
        dimension=dimension,
        description=(
            f"Drops every learned `{dimension.value}` row from `ActivityPreferences`. The only way "
            "to separate axes the ranker reads more than once -- `distance_m` is scored by "
            "`intent`, by the DISTANCE preference and by `friction`."
        ),
    )


_INPUT_SPECS: tuple[ArmSpec, ...] = (
    ArmSpec(
        name=ARM_INPUT_NO_INTENT,
        kind="input",
        baseline=ARM_FULL,
        diversity=True,
        touches=("intent", "context"),
        description=(
            "Substitutes an empty `ActivityIntent()`. CONFOUNDED, and kept only as the honest "
            '"what if nothing was asked for" arm: it also resets `environment` to EITHER, which '
            "switches `score_candidate`'s rain nudge back on for any case whose real intent asked "
            "for a specific environment, and it flattens every candidate's `intent` factor value "
            "to 0, which removes intent from the tier as well. Read `factor:intent` for the "
            "intent weight's own effect."
        ),
    ),
    ArmSpec(
        name=ARM_INPUT_NO_ENGAGEMENT,
        kind="input",
        baseline=ARM_FULL,
        diversity=True,
        touches=("engagement", "repetition"),
        description=(
            "Passes `engagement={}`. CONFOUNDED: the same map carries `last_not_for_me`, so this "
            "also zeroes the `repetition` factor and removes every HISTORY reason line. Read "
            "`factor:engagement` and `factor:repetition` for the two weights separately."
        ),
    ),
    ArmSpec(
        name=ARM_INPUT_NO_PREFERENCES,
        kind="input",
        baseline=ARM_FULL,
        diversity=True,
        touches=("preference",),
        description=(
            "Passes an empty `ActivityPreferences`: nothing learned from the observation trace "
            'reaches the ranker at all. The "what did the learning buy" arm, at the input rather '
            "than the weight."
        ),
    ),
)


def _trace_spec(name: str, events: int, description: str) -> ArmSpec:
    return ArmSpec(
        name=name,
        kind="trace_prefix",
        baseline=ARM_FULL,
        diversity=True,
        touches=("preference", "engagement", "repetition"),
        trace_events=events,
        description=description,
    )


_TRACE_SPECS: tuple[ArmSpec, ...] = (
    _trace_spec(
        ARM_COLD_START,
        0,
        "Day zero for a new person: no observation trace at all, so no learned preference and no "
        "engagement history. What the deterministic factors (`intent`, `context`, `friction`) "
        "achieve on their own, before the learner has anything to work with.",
    ),
    _trace_spec(
        ARM_FIRST_SIGNAL,
        1,
        "The first trace event only -- one decline, one enjoyment report or one stated "
        "preference. The same manipulation as `trace_prefix:1`.",
    ),
    *(
        _trace_spec(
            trace_prefix_arm(events),
            events,
            f"The first {events} trace event(s). Read the series as a learning curve: how much "
            "evidence does the learner need before it helps?",
        )
        for events in TRACE_PREFIX_LENGTHS
    ),
)

_DIVERSITY_SPEC = ArmSpec(
    name=ARM_NO_DIVERSITY,
    kind="diversity",
    baseline=ARM_FULL,
    diversity=False,
    touches=(),
    description=(
        "The production pipeline with only the diversity swap switched off; the tier sort and the "
        "series dedupe still run, so the delta is the swap alone. This arm is also the BASELINE "
        "every other diversity-off arm is measured against."
    ),
)

ARM_SPECS: dict[str, ArmSpec] = {
    ARM_FULL: ArmSpec(
        name=ARM_FULL,
        kind="full",
        baseline=ARM_FULL,
        diversity=True,
        touches=(),
        description="Production `rank_candidates_with_breakdown`, unmodified.",
    ),
    **{factor_arm(name): _factor_spec(name) for name in FACTOR_NAMES},
    **{spec.name: spec for spec in _INPUT_SPECS},
    **{
        preference_dimension_arm(dimension): _dimension_spec(dimension)
        for dimension in PreferenceDimension
    },
    **{spec.name: spec for spec in _TRACE_SPECS},
    ARM_NO_DIVERSITY: _DIVERSITY_SPEC,
}

ABLATION_ARMS: tuple[str, ...] = tuple(ARM_SPECS)


def baseline_for(arm: str) -> str:
    return ARM_SPECS[arm].baseline


def _with_contribution_zeroed(breakdown: ScoreBreakdown, name: str) -> ScoreBreakdown:
    """Zero one factor's `contribution` (its weighted term in `total`) while leaving its `value` --
    and every other factor -- exactly as production computed it. `total` is recomputed from the
    adjusted `factors` list so the breakdown stays internally consistent (`total ==
    sum(contributions)`), the same invariant `score_candidate` itself keeps.

    The two post-scoring flags are reset because the returned list is a PRE-postprocess one: it is
    about to be re-sorted and handed back to `activity_search.postprocess`, which sets both again
    from the new order.
    """
    factors = [
        factor.model_copy(update={"contribution": 0.0}) if factor.name == name else factor
        for factor in breakdown.factors
    ]
    total = round(sum(factor.contribution for factor in factors), 3)
    return breakdown.model_copy(
        update={
            "factors": factors,
            "total": total,
            "series_deferred": False,
            "variety_promoted": False,
        }
    )


def zero_factor(ranked: list[RankedScore], name: str) -> list[RankedScore]:
    """Subtract one named factor's weighted CONTRIBUTION from every candidate's `total` and re-sort.

    Nothing about the hard filter, the tier or the environment-aware rain rule changes: all three
    depend on factor VALUES (and on the real intent), which this function never touches -- it only
    reads and adjusts already-computed `ScoreBreakdown`s. The re-sort is production's own key,
    `activity_search.sort_key_for` -- tier (`ScoreBreakdown.tier`, which zeroing a contribution
    never moves), the adjusted total, matched axes, distance, title, start time, activity id. A
    private copy of that key used to live here: it rebuilt the tier from the `intent` factor's
    value (which stopped being the tier once weighted credit and tier fit were separated) and
    skipped the matched-axes, start-time and id tie-breaks, so an arm with nothing zeroed could
    still reorder ties.

    The result is a PRE-postprocess list, in the shape `activity_search.postprocess` expects: the
    caller re-runs the production series-dedupe and diversity passes on it rather than skipping
    them (which is what made the old `no_intent_soft` arm's series/category deltas meaningless).
    """
    if name not in RANKING_WEIGHTS:
        raise ValueError(f"unknown ranking factor: {name!r}")
    adjusted = [
        RankedScore(ranked=item.ranked, breakdown=_with_contribution_zeroed(item.breakdown, name))
        for item in ranked
    ]
    ordered = sorted(
        adjusted,
        key=lambda item: sort_key_for(item.ranked.candidate, item.breakdown).ordering(),
    )
    return [
        RankedScore(
            ranked=entry.ranked.model_copy(update={"rank": position}), breakdown=entry.breakdown
        )
        for position, entry in enumerate(ordered, start=1)
    ]


TraceInputs = Callable[[int], tuple[ActivityPreferences, Mapping[str, ActivityEngagement]]]
"""Given a number of trace events, the preference store and engagement map the ranker would have
had after exactly that many. Supplied by the runner (which owns the persona); this module stays
free of any knowledge of the dataset."""


def rank_for_arm(
    arm: str,
    *,
    candidates: list[ActivityCandidate],
    intent: ActivityIntent,
    preferences: ActivityPreferences,
    engagement: Mapping[str, ActivityEngagement],
    today: date,
    rain_forecast: bool,
    full_ranked: list[RankedScore] | None = None,
    trace_inputs: TraceInputs | None = None,
) -> list[RankedScore]:
    """Rank `candidates` under one named arm."""
    spec = ARM_SPECS.get(arm)
    if spec is None:
        raise ValueError(f"unknown ablation arm: {arm!r}")

    def rank(
        *,
        arm_intent: ActivityIntent = intent,
        arm_preferences: ActivityPreferences = preferences,
        arm_engagement: Mapping[str, ActivityEngagement] = engagement,
        arm_rain: bool = rain_forecast,
        diversity: bool = True,
    ) -> list[RankedScore]:
        return rank_candidates_with_breakdown(
            candidates,
            arm_intent,
            arm_preferences,
            rain_forecast=arm_rain,
            engagement=arm_engagement,
            today=today,
            diversity=diversity,
        )

    if spec.kind == "full":
        return rank()
    if spec.kind == "diversity":
        return rank(diversity=False)
    if spec.kind == "factor":
        assert spec.factor is not None
        # `diversity=False` on the way IN so the swap is not applied to an order this arm is about
        # to discard; `postprocess` then runs both production passes on the adjusted order.
        return postprocess(zero_factor(rank(diversity=False), spec.factor), diversity=True)
    if spec.kind == "trace_prefix":
        if trace_inputs is None:
            raise ValueError(f"{arm!r} needs `trace_inputs` to rebuild the truncated trace")
        assert spec.trace_events is not None
        prefix_preferences, prefix_engagement = trace_inputs(spec.trace_events)
        return rank(arm_preferences=prefix_preferences, arm_engagement=prefix_engagement)
    if spec.kind == "preference_dimension":
        assert spec.dimension is not None
        return rank(
            arm_preferences=ActivityPreferences(
                person_id=preferences.person_id,
                dimensions=[
                    dimension
                    for dimension in preferences.dimensions
                    if dimension.dimension is not spec.dimension
                ],
            )
        )
    if arm == ARM_INPUT_NO_INTENT:
        return rank(arm_intent=ActivityIntent())
    if arm == ARM_INPUT_NO_ENGAGEMENT:
        return rank(arm_engagement={})
    if arm == ARM_INPUT_NO_PREFERENCES:
        return rank(
            arm_preferences=ActivityPreferences(person_id=preferences.person_id, dimensions=[])
        )
    raise ValueError(f"unhandled ablation arm: {arm!r}")


__all__ = [
    "ABLATION_ARMS",
    "ARM_COLD_START",
    "ARM_FIRST_SIGNAL",
    "ARM_FULL",
    "ARM_INPUT_NO_ENGAGEMENT",
    "ARM_INPUT_NO_INTENT",
    "ARM_INPUT_NO_PREFERENCES",
    "ARM_NO_DIVERSITY",
    "ARM_SPECS",
    "FACTOR_NAMES",
    "TRACE_PREFIX_LENGTHS",
    "ArmSpec",
    "baseline_for",
    "factor_arm",
    "preference_dimension_arm",
    "rank_for_arm",
    "trace_prefix_arm",
    "zero_factor",
]
