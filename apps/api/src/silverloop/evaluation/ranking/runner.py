"""Orchestration: fold every (persona, query template) pair over the frozen catalogue, grade the
results against each persona's brief, and fold the per-case numbers into the artifact's macro
metrics, reference lines and ablation deltas.

Nothing here touches a database, FastAPI or an LLM client -- see `test_ranking_evaluation.py`'s
import-boundary test, which mirrors `test_evaluation.py`'s.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping
from dataclasses import dataclass, field

from silverloop.activity_search import ActivityEngagement, RankedScore, filter_candidates
from silverloop.evaluation.ranking import ablations
from silverloop.evaluation.ranking._grounding import (
    candidate_matches_a_constrained_axis,
    intent_is_constrained,
)
from silverloop.evaluation.ranking.context_labels import grade_context_fit
from silverloop.evaluation.ranking.dataset import (
    CATALOGUE,
    CORE_PERSONAS,
    FROZEN_TODAY,
    HOLDOUT_PERSONAS,
    QUERY_TEMPLATES,
    PersonaBrief,
    QueryTemplate,
    StatedPreferenceEvent,
    dataset_digest,
    holdout_digest,
    holdout_frozen,
)
from silverloop.evaluation.ranking.labels import (
    GRADE_TASTE_MATCH,
    grade_candidate,
)
from silverloop.evaluation.ranking.metrics import (
    RELEVANT_THRESHOLD,
    Delta,
    Rate,
    Stat,
    bootstrap_stat,
    category_entropy_at_k,
    cluster_bootstrap_stat,
    cluster_paired_delta,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    paired_delta,
    precision_at_k,
    slate_ndcg_at_k,
)
from silverloop.evaluation.ranking.traces import (
    build_engagement,
    build_preferences,
    label_engagement,
)
from silverloop.models import (
    ActivityCandidate,
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    ActivityPreferences,
    IndoorOutdoor,
    ReasonBasis,
    SocialPreference,
)
from silverloop.preferences import dimension_score

GENERATOR_VERSION = "1.0.0"
RANKING_EVAL_SEED = 20260908
TOP_K = 3
SHOWN_LIMIT = 10
RANDOM_DRAWS = 20

CORE_SPLIT = "core"
HOLDOUT_SPLIT = "holdout"


def _seed(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


@dataclass(frozen=True)
class CaseResult:
    split: str
    persona: PersonaBrief
    template: QueryTemplate
    intent: ActivityIntent
    kept: list[ActivityCandidate]
    grades: dict[str, int]
    context_grades: dict[str, int]
    """`context_labels.grade_context_fit` per kept candidate -- a SEPARATE grade from `grades`
    (relevance): whether a listing suits the persona's taste and whether it is a good idea given
    today's weather are different questions, so they are graded by different rules. This does NOT
    make the two judgements independent evidence of each other: `grade_context_fit` restates the
    same rain/environment premise `activity_search.py`'s own `context` factor encodes, so a metric
    built from it (`context_rule_conformance_at_3`, below) shows whether that factor is wired and
    behaves as declared -- not whether the declared rule is itself a good idea. See
    `context_labels.py`'s module docstring."""
    preferences: ActivityPreferences
    engagement: dict[str, ActivityEngagement]
    arms: dict[str, list[RankedScore]]


def _grades_for(
    persona: PersonaBrief,
    kept: list[ActivityCandidate],
    engagement: Mapping[str, ActivityEngagement],
) -> dict[str, int]:
    return {
        candidate.activity_id: grade_candidate(
            persona, candidate, engagement.get(candidate.activity_id), FROZEN_TODAY
        )
        for candidate in kept
    }


def _context_grades_for(
    kept: list[ActivityCandidate], intent: ActivityIntent, *, rain_forecast: bool
) -> dict[str, int]:
    return {
        candidate.activity_id: grade_context_fit(candidate, intent, rain_forecast=rain_forecast)
        for candidate in kept
    }


def run_case(split: str, persona: PersonaBrief, template: QueryTemplate) -> CaseResult:
    intent = template.build_intent(persona)
    catalogue = list(CATALOGUE)
    kept, _filtered_out = filter_candidates(catalogue, intent, today=FROZEN_TODAY)
    preferences = build_preferences(persona)
    engagement = build_engagement(persona)
    # Graded from the frozen per-listing read, never from the ranker's own input: the grades are
    # ground truth and must not move when production's engagement counting does.
    grades = _grades_for(persona, kept, label_engagement(persona))
    context_grades = _context_grades_for(kept, intent, rain_forecast=template.rain_forecast)

    def trace_inputs(events: int) -> tuple[ActivityPreferences, dict[str, ActivityEngagement]]:
        """What the ranker would have had after exactly `events` trace events. Rebuilt through the
        same production folding functions the full trace goes through, so a cold-start arm is the
        real pipeline with less evidence, not a different pipeline."""
        return build_preferences(persona, limit=events), build_engagement(persona, limit=events)

    arms: dict[str, list[RankedScore]] = {}
    full_ranked = ablations.rank_for_arm(
        ablations.ARM_FULL,
        candidates=kept,
        intent=intent,
        preferences=preferences,
        engagement=engagement,
        today=FROZEN_TODAY,
        rain_forecast=template.rain_forecast,
    )
    arms[ablations.ARM_FULL] = full_ranked
    for arm in ablations.ABLATION_ARMS:
        if arm == ablations.ARM_FULL:
            continue
        arms[arm] = ablations.rank_for_arm(
            arm,
            candidates=kept,
            intent=intent,
            preferences=preferences,
            engagement=engagement,
            today=FROZEN_TODAY,
            rain_forecast=template.rain_forecast,
            full_ranked=full_ranked,
            trace_inputs=trace_inputs,
        )

    return CaseResult(
        split=split,
        persona=persona,
        template=template,
        intent=intent,
        kept=kept,
        grades=grades,
        context_grades=context_grades,
        preferences=preferences,
        engagement=engagement,
        arms=arms,
    )


def _relevances(case: CaseResult, ranked: list[RankedScore]) -> list[int]:
    return [case.grades[item.ranked.candidate.activity_id] for item in ranked]


def _context_relevances(case: CaseResult, ranked: list[RankedScore]) -> list[int]:
    return [case.context_grades[item.ranked.candidate.activity_id] for item in ranked]


def _case_metrics(case: CaseResult, ranked: list[RankedScore]) -> dict[str, float]:
    relevances = _relevances(case, ranked)
    context_relevances = _context_relevances(case, ranked)
    top = ranked[:TOP_K]
    categories = [item.ranked.candidate.category for item in ranked]
    unknown_count = sum(
        1 for item in top if _has_unknown_constrained_field(case.intent, item.ranked.candidate)
    )
    return {
        "ndcg_at_1": ndcg_at_k(relevances, 1),
        "hit_rate_at_3": hit_rate_at_k(relevances, TOP_K, GRADE_TASTE_MATCH),
        "slate_ndcg_at_3": slate_ndcg_at_k(relevances, categories, TOP_K),
        "ndcg_at_3": ndcg_at_k(relevances, TOP_K),
        "context_rule_conformance_at_3": ndcg_at_k(context_relevances, TOP_K),
        "precision_at_3": precision_at_k(relevances, TOP_K),
        "mrr": mrr(relevances),
        "unknown_admitted_at_3": (unknown_count / len(top)) if top else 0.0,
        "category_entropy_at_3": category_entropy_at_k(categories, TOP_K),
    }


def case_is_discriminable(case: CaseResult) -> bool:
    """Can this case tell a good ranking from a bad one at all?

    Exactly one property, measured rather than asserted: does any ordering of the kept pool score
    differently from any other on the headline metric? `NDCG@k`'s discount is strictly decreasing
    and its gains are non-negative, so the descending ordering maximises it and the ascending one
    minimises it -- if those two agree, every permutation in between does too. Equivalently, and
    this is what the numbers actually turn out to be on this dataset, a case is non-discriminable
    exactly when every kept candidate carries the same grade.

    This used to require a grade-3 taste match AND something graded <=1, justified in the artifact
    as "every ordering of them scores identically". That justification was false: of the 51 core
    cases whose ordering demonstrably changes the headline, the filter dropped 21, and on the
    holdout set it dropped 14 of 24. A case with a grade-2 and a grade-0 in it, or one with a
    grade-3 and a grade-2, discriminates perfectly well -- and both were being excluded from the
    stratum the headline is quoted over. `n_clusters` fell 10 -> 7 on core and 4 -> 3 on holdout,
    which is whole personas leaving the headline.
    """
    grades = [case.grades[candidate.activity_id] for candidate in case.kept]
    best = ndcg_at_k(sorted(grades, reverse=True), TOP_K)
    worst = ndcg_at_k(sorted(grades), TOP_K)
    return abs(best - worst) > _SCORE_TOLERANCE


_SCORE_TOLERANCE = 1e-12
"""Two NDCG values this close are the same number reached by two summation orders."""


def _has_unknown_constrained_field(intent: ActivityIntent, candidate: ActivityCandidate) -> bool:
    if intent.max_distance_m is not None and candidate.distance_m is None:
        return True
    if (
        intent.environment != ActivityEnvironment.EITHER
        and candidate.indoor_outdoor == IndoorOutdoor.UNKNOWN
    ):
        return True
    if intent.social_preference != SocialPreference.EITHER and candidate.social_shape is None:
        return True
    if intent.intensity != ActivityIntensity.EITHER and candidate.intensity is None:
        return True
    return bool(intent.language is not None and not candidate.language_tags)


def _random_metrics(case: CaseResult) -> dict[str, float]:
    """Average of `RANDOM_DRAWS` random orderings of `case.kept`, using the SAME grades -- the
    floor every ranked metric must sit above to mean anything.
    """
    totals = {name: 0.0 for name in _REFERENCE_METRIC_NAMES}
    for draw in range(RANDOM_DRAWS):
        rng = random.Random(
            _seed("random", case.split, case.persona.person_id, case.template.name, str(draw))
        )
        shuffled = list(case.kept)
        rng.shuffle(shuffled)
        relevances = [case.grades[c.activity_id] for c in shuffled]
        categories = [c.category for c in shuffled]
        for name, value in _reference_metrics(relevances, categories).items():
            totals[name] += value
    return {key: value / RANDOM_DRAWS for key, value in totals.items()}


def _catalogue_order_metrics(case: CaseResult) -> dict[str, float]:
    graded = [case.grades[c.activity_id] for c in case.kept]
    categories = [c.category for c in case.kept]
    return _reference_metrics(graded, categories)


def _intent_filter_static_metrics(case: CaseResult) -> dict[str, float]:
    """The floor that was missing: what a rule-based catalogue app would do.

    `filter_candidates` has already applied every hard constraint the person asked for (this is the
    same kept pool every other arm sees); this line then sorts by distance, then title. No learned
    preference, no engagement history, no weather, no diversity. Beating `random` is a low bar;
    beating a competent static list is the one that means something.
    """
    ordered = sorted(
        case.kept,
        key=lambda candidate: (
            float(candidate.distance_m) if candidate.distance_m is not None else float("inf"),
            candidate.title,
        ),
    )
    graded = [case.grades[candidate.activity_id] for candidate in ordered]
    categories = [candidate.category for candidate in ordered]
    return _reference_metrics(graded, categories)


def _reference_metrics(graded: list[int], categories: list[str | None]) -> dict[str, float]:
    return {
        "ndcg_at_1": ndcg_at_k(graded, 1),
        "hit_rate_at_3": hit_rate_at_k(graded, TOP_K, GRADE_TASTE_MATCH),
        "slate_ndcg_at_3": slate_ndcg_at_k(graded, categories, TOP_K),
        "ndcg_at_3": ndcg_at_k(graded, TOP_K),
        "precision_at_3": precision_at_k(graded, TOP_K),
        "mrr": mrr(graded),
    }


def _oracle_metrics(case: CaseResult) -> dict[str, float]:
    ordered = sorted(case.kept, key=lambda c: (-case.grades[c.activity_id], c.title))
    graded = [case.grades[c.activity_id] for c in ordered]
    categories = [c.category for c in ordered]
    return _reference_metrics(graded, categories)


def _reason_grounded(
    basis: ReasonBasis,
    candidate: ActivityCandidate,
    case: CaseResult,
    breakdown_variety_promoted: bool,
) -> bool | None:
    """`True`/`False` for a verifiable basis, `None` for `CATALOGUE` (filler, reported
    separately, never counted in the rate's numerator or denominator -- E1's own instruction)."""
    if basis == ReasonBasis.INTENT:
        return intent_is_constrained(case.intent) and candidate_matches_a_constrained_axis(
            candidate, case.intent
        )
    if basis == ReasonBasis.PREFERENCE:
        return dimension_score(candidate, case.preferences) != 0.0
    if basis == ReasonBasis.HISTORY:
        engagement = case.engagement.get(candidate.activity_id)
        return (
            engagement is not None
            and (engagement.interested + engagement.went + engagement.enjoyed) > 0
        )
    if basis == ReasonBasis.CONTEXT:
        # The line claims the listing is "a better fit with rain around today", so three things
        # have to hold for it to be grounded, and the metric checks all three rather than the
        # forecast alone (which every template sets to True, making the old check unfailable):
        # rain, the person having left the environment open, and the listing actually being under
        # cover. A CONTEXT line on an OUTDOOR or unlisted venue is NOT grounded.
        return (
            case.template.rain_forecast
            and case.intent.environment == ActivityEnvironment.EITHER
            and candidate.indoor_outdoor in (IndoorOutdoor.INDOOR, IndoorOutdoor.SHELTERED)
        )
    if basis == ReasonBasis.VARIETY:
        return breakdown_variety_promoted
    return None  # CATALOGUE


def _reasons_grounded_for_case(case: CaseResult) -> tuple[int, int, int]:
    """`(grounded, verifiable, catalogue_filler)` over the `full` arm's top `SHOWN_LIMIT` cards."""
    grounded = 0
    verifiable = 0
    catalogue_filler = 0
    for item in case.arms[ablations.ARM_FULL][:SHOWN_LIMIT]:
        for reason in item.ranked.reasons:
            result = _reason_grounded(
                reason.basis, item.ranked.candidate, case, item.breakdown.variety_promoted
            )
            if result is None:
                catalogue_filler += 1
                continue
            verifiable += 1
            if result:
                grounded += 1
    return grounded, verifiable, catalogue_filler


def _pool_present_divergence(cases: list[CaseResult]) -> list[tuple[frozenset[str], float]]:
    """`(persona pair, 1 - overlap)` of top-3 between every pair of cases in `cases` that share the
    identical built `ActivityIntent` ("the same query") and whose derived preference stores
    disagree about at least one candidate actually present in their shared kept pool.

    The unordered persona pair is carried beside each value because the values are NOT independent:
    45 pairs over 10 personas, each persona appearing in 9 of them. Bootstrapping the pairs i.i.d.
    produced the uninterpretable `[0.33, 0.46]` the evaluation review objected to; the pair is the
    cluster the CI is computed over instead.
    """
    by_intent: dict[str, list[CaseResult]] = {}
    for case in cases:
        key = case.intent.model_dump_json()
        by_intent.setdefault(key, []).append(case)

    divergences: list[tuple[frozenset[str], float]] = []
    for group in by_intent.values():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                left, right = group[i], group[j]
                pool = [
                    c for c in left.kept if c.activity_id in {k.activity_id for k in right.kept}
                ]
                differs = any(
                    dimension_score(candidate, left.preferences)
                    != dimension_score(candidate, right.preferences)
                    for candidate in pool
                )
                if not differs:
                    continue
                top_left = {
                    item.ranked.candidate.activity_id
                    for item in left.arms[ablations.ARM_FULL][:TOP_K]
                }
                top_right = {
                    item.ranked.candidate.activity_id
                    for item in right.arms[ablations.ARM_FULL][:TOP_K]
                }
                overlap = len(top_left & top_right) / TOP_K
                pair = frozenset({left.persona.person_id, right.persona.person_id})
                divergences.append((pair, 1.0 - overlap))
    return divergences


STATED_STRATUM = "stated"
INFERRED_ONLY_STRATUM = "inferred_only"


def persona_states_a_graded_fact(persona: PersonaBrief) -> bool:
    """True when the persona's trace hands the ranker, verbatim, one of the exact
    `(dimension, value)` pairs the ground-truth grader reads from her brief.

    Such a case does not measure "infer taste from behaviour" at all; it measures "obey what the
    person just told you", which is a different (and much easier) task. Neither is illegitimate --
    a stated preference IS what production receives, and the repo's own invariant says current
    explicit intent normally outranks historical inference -- but averaging the two into one
    headline hides which of them the number came from. Match is exact on the pair: `eval-mr-koh`
    states SOCIAL `solo` while her brief's hard avoid is SOCIAL `social`, the same fact expressed
    from the other pole, and is deliberately NOT counted here -- the report says so rather than
    quietly widening the rule.
    """
    graded = {pair for pair in (*persona.stated_tastes, *persona.soft_avoids, *persona.hard_avoids)}
    return any(
        (event.dimension, event.value) in graded
        for event in persona.trace
        if isinstance(event, StatedPreferenceEvent)
    )


@dataclass(frozen=True)
class LearningCurvePoint:
    """One point on "how much evidence does the learner need before it helps?".

    `lift_over_random` is the paired, persona-clustered difference between this arm and the random
    floor on the headline metric -- the same test the headline claim uses, applied at each prefix
    length.
    """

    arm: str
    trace_events: int
    ndcg_at_1: float
    hit_rate_at_3: float
    ndcg_at_3: float
    lift_over_random: Delta


@dataclass(frozen=True)
class ArmEffect:
    """Did an arm's manipulation reach the score, and did it reach the ORDER?

    A delta of exactly zero has two very different causes, and the artifact has to say which: the
    dataset never gave the factor a chance to matter, or the factor moved and something else --
    usually the tier -- absorbed it. The second is a masking result, not a null one.
    """

    arm: str
    baseline: str
    n_cases: int
    scores_changed_cases: int
    order_changed_cases: int

    @property
    def masked(self) -> bool:
        return self.scores_changed_cases > 0 and self.order_changed_cases == 0


@dataclass(frozen=True)
class PersonaSummary:
    """One persona's own numbers. A macro mean of 0.80 over ten personas can hide a 0.25, and on
    this dataset it does -- so the artifact prints the table rather than the mean alone."""

    person_id: str
    display_name: str
    n_cases: int
    stated: bool
    ndcg_at_3: float
    random_ndcg_at_3: float

    @property
    def lift_over_random(self) -> float:
        return round(self.ndcg_at_3 - self.random_ndcg_at_3, 4)


@dataclass(frozen=True)
class StratumResult:
    """One side of the stated / inferred-only split, with its own clustered lift over random."""

    name: str
    persona_ids: tuple[str, ...]
    metrics: dict[str, Stat]
    reference_random: dict[str, Stat]
    lift_over_random: Delta


@dataclass(frozen=True)
class SplitResult:
    split: str
    n_cases: int
    n_personas: int
    metrics: dict[str, Stat]
    metrics_clustered: dict[str, Stat]
    """The SAME metrics, bootstrapped by resampling personas rather than cases. Printed beside the
    per-case CI everywhere: six cases from one persona share her trace, her preference store and
    her grade table, so the per-case interval is ~2.2x too narrow on this dataset."""
    reference_random: dict[str, Stat]
    reference_catalogue_order: dict[str, Stat]
    reference_oracle: dict[str, Stat]
    reference_intent_filter_static: dict[str, Stat]
    """The honest "what a rule-based catalogue app would do" floor: the same filtered pool,
    sorted by distance then title."""
    reference_clustered: dict[str, dict[str, Stat]]
    lifts: dict[str, Delta]
    """Paired, persona-clustered `full - <reference line>` deltas. The headline claim ("the ranker
    beats a random shuffle") is this number, not a comparison of two marginal CIs."""
    discriminable_cases: int
    """Cases whose ordering can change the headline metric at all -- the best and the worst
    ordering of the kept pool score differently. Only these can distinguish a good ranking from a
    bad one; the headline is reported over them as well as over every case."""
    metrics_discriminable: dict[str, Stat]
    reference_discriminable: dict[str, dict[str, Stat]]
    lifts_discriminable: dict[str, Delta]
    learning_curve: tuple[LearningCurvePoint, ...]
    cases_to_beat_random: int | None
    """The smallest number of observation-trace events at which the paired, persona-clustered CI of
    (arm - random) on the headline metric excludes zero -- the only number that answers "how much
    evidence does the learner need before it helps". `None` when no prefix length reaches it."""
    max_trace_events: int
    """The longest observation trace in the split. The learning curve saturates here, and any
    prefix length beyond it is the full trace under another name -- printed so the flat tail of the
    curve is not misread as evidence that more evidence would not help."""
    per_persona: tuple[PersonaSummary, ...]
    strata: tuple[StratumResult, ...]
    personalisation_divergence: Stat
    reasons_grounded: Rate
    """Pooled numerator/denominator over every shown reason line in the split -- the headline,
    honest-at-a-glance number."""
    reasons_grounded_stat: Stat
    """The SAME rate, macro-averaged per case with a bootstrap CI (E1's own metric list groups
    `reasons_grounded_rate` with the other per-case, bootstrapped metrics). Cases with zero
    verifiable reason lines are skipped rather than counted as 0% or 100%, exactly like `Rate`
    already treats a zero denominator as `n/a` rather than a number."""
    catalogue_filler_count: int
    ablation_deltas: dict[str, dict[str, Delta]]
    ablation_deltas_clustered: dict[str, dict[str, Delta]]
    arm_effects: dict[str, ArmEffect]
    cases: list[CaseResult] = field(repr=False)

    @property
    def reference_all(self) -> dict[str, dict[str, Stat]]:
        """Every reference line by name, per-case CI -- the shape the report's tables want."""
        return {
            "random": self.reference_random,
            "catalogue_order": self.reference_catalogue_order,
            "intent_filter_static": self.reference_intent_filter_static,
            "oracle": self.reference_oracle,
        }


_CASE_METRIC_NAMES = (
    "ndcg_at_1",
    "hit_rate_at_3",
    "slate_ndcg_at_3",
    "ndcg_at_3",
    "context_rule_conformance_at_3",
    "precision_at_3",
    "mrr",
    "unknown_admitted_at_3",
    "category_entropy_at_3",
)
_REFERENCE_METRIC_NAMES = (
    "ndcg_at_1",
    "hit_rate_at_3",
    "slate_ndcg_at_3",
    "ndcg_at_3",
    "precision_at_3",
    "mrr",
)
assert RELEVANT_THRESHOLD == GRADE_TASTE_MATCH, (
    "P@3 and MRR count a 'taste match' as relevant, so their threshold and the grader's own "
    "taste-match grade have to be the same number"
)

HEADLINE_METRIC_NAMES = ("ndcg_at_1", "hit_rate_at_3", "slate_ndcg_at_3")
"""The three the reader should look at first: is the best thing FIRST, is a taste match anywhere
in the slate, and how good is the slate judged under the product's own one-per-category rule.
Graded `NDCG@3` stays in the technical table."""
REFERENCE_LINES = ("random", "catalogue_order", "intent_filter_static", "oracle")
HEADLINE_METRIC = "ndcg_at_3"


def _case_seed(split: str) -> int:
    """One seed per split for every per-case bootstrap, and one for every clustered one.

    Sharing the draws across metrics and arms is deliberate (see `metrics._resample_indices`):
    common random numbers, and the difference between two arms is then the arm rather than the
    luck of two independent draw sequences.
    """
    return _seed(split, "case", str(RANKING_EVAL_SEED))


def _cluster_seed(split: str) -> int:
    return _seed(split, "cluster", str(RANKING_EVAL_SEED))


def _run_split(split: str, personas: tuple[PersonaBrief, ...]) -> SplitResult:
    cases = [
        run_case(split, persona, template) for persona in personas for template in QUERY_TEMPLATES
    ]
    clusters = [case.persona.person_id for case in cases]
    case_seed = _case_seed(split)
    cluster_seed = _cluster_seed(split)

    per_metric_full: dict[str, list[float]] = {name: [] for name in _CASE_METRIC_NAMES}
    per_metric_reference: dict[str, dict[str, list[float]]] = {
        line: {name: [] for name in _REFERENCE_METRIC_NAMES} for line in REFERENCE_LINES
    }
    per_metric_random = per_metric_reference["random"]
    per_metric_arm: dict[str, dict[str, list[float]]] = {
        arm: {name: [] for name in _CASE_METRIC_NAMES} for arm in ablations.ABLATION_ARMS
    }
    effect_counts: dict[str, list[int]] = {arm: [0, 0] for arm in ablations.ABLATION_ARMS}

    grounded_total = 0
    verifiable_total = 0
    catalogue_filler_total = 0
    per_case_grounded_rate: list[float] = []

    for case in cases:
        full_case_metrics = _case_metrics(case, case.arms[ablations.ARM_FULL])
        for name, value in full_case_metrics.items():
            per_metric_full[name].append(value)
            per_metric_arm[ablations.ARM_FULL][name].append(value)

        reference_metrics = {
            "random": _random_metrics(case),
            "catalogue_order": _catalogue_order_metrics(case),
            "intent_filter_static": _intent_filter_static_metrics(case),
            "oracle": _oracle_metrics(case),
        }
        for line, values in reference_metrics.items():
            for name in _REFERENCE_METRIC_NAMES:
                per_metric_reference[line][name].append(values[name])

        for arm, values in per_metric_arm.items():
            if arm == ablations.ARM_FULL:
                continue
            arm_case_metrics = _case_metrics(case, case.arms[arm])
            for name, value in arm_case_metrics.items():
                values[name].append(value)
            scores_changed, order_changed = _arm_effect_on_case(case, arm)
            effect_counts[arm][0] += int(scores_changed)
            effect_counts[arm][1] += int(order_changed)

        grounded, verifiable, filler = _reasons_grounded_for_case(case)
        grounded_total += grounded
        verifiable_total += verifiable
        catalogue_filler_total += filler
        if verifiable > 0:
            per_case_grounded_rate.append(grounded / verifiable)

    metrics = {
        name: bootstrap_stat(values, seed=case_seed) for name, values in per_metric_full.items()
    }
    metrics_clustered = {
        name: cluster_bootstrap_stat(values, clusters, seed=cluster_seed)
        for name, values in per_metric_full.items()
    }
    reference = {
        line: {name: bootstrap_stat(values, seed=case_seed) for name, values in per_metric.items()}
        for line, per_metric in per_metric_reference.items()
    }
    reference_clustered = {
        line: {
            name: cluster_bootstrap_stat(values, clusters, seed=cluster_seed)
            for name, values in per_metric.items()
        }
        for line, per_metric in per_metric_reference.items()
    }
    lifts = {
        line: cluster_paired_delta(
            per_metric_reference[line][HEADLINE_METRIC],
            per_metric_full[HEADLINE_METRIC],
            clusters,
            seed=cluster_seed,
        )
        for line in REFERENCE_LINES
    }

    ablation_deltas: dict[str, dict[str, Delta]] = {}
    ablation_deltas_clustered: dict[str, dict[str, Delta]] = {}
    arm_effects: dict[str, ArmEffect] = {}
    for arm, values in per_metric_arm.items():
        if arm == ablations.ARM_FULL:
            continue
        baseline = per_metric_arm[ablations.baseline_for(arm)]
        ablation_deltas[arm] = {
            name: paired_delta(baseline[name], values[name], seed=case_seed)
            for name in _CASE_METRIC_NAMES
        }
        ablation_deltas_clustered[arm] = {
            name: cluster_paired_delta(baseline[name], values[name], clusters, seed=cluster_seed)
            for name in _CASE_METRIC_NAMES
        }
        arm_effects[arm] = ArmEffect(
            arm=arm,
            baseline=ablations.baseline_for(arm),
            n_cases=len(cases),
            scores_changed_cases=effect_counts[arm][0],
            order_changed_cases=effect_counts[arm][1],
        )

    divergences = _pool_present_divergence(cases)
    personalisation = cluster_bootstrap_stat(
        [value for _, value in divergences],
        [pair for pair, _ in divergences],
        seed=_seed(split, "personalisation_pairs"),
    )
    reasons_grounded_stat = bootstrap_stat(per_case_grounded_rate, seed=case_seed)

    discriminable = [index for index, case in enumerate(cases) if case_is_discriminable(case)]
    discriminable_clusters = [cases[index].persona.person_id for index in discriminable]
    discriminable_seed = _seed(split, "discriminable")
    metrics_discriminable = {
        name: cluster_bootstrap_stat(
            [values[index] for index in discriminable],
            discriminable_clusters,
            seed=discriminable_seed,
        )
        for name, values in per_metric_full.items()
    }
    reference_discriminable = {
        line: {
            name: cluster_bootstrap_stat(
                [values[index] for index in discriminable],
                discriminable_clusters,
                seed=discriminable_seed,
            )
            for name, values in per_metric.items()
        }
        for line, per_metric in per_metric_reference.items()
    }
    lifts_discriminable = {
        line: cluster_paired_delta(
            [per_metric_reference[line][HEADLINE_METRIC][index] for index in discriminable],
            [per_metric_full[HEADLINE_METRIC][index] for index in discriminable],
            discriminable_clusters,
            seed=discriminable_seed,
        )
        for line in REFERENCE_LINES
    }

    learning_curve = _learning_curve(per_metric_arm, per_metric_random, clusters, cluster_seed)
    cases_to_beat_random = next(
        (point.trace_events for point in learning_curve if point.lift_over_random.ci_low > 0),
        None,
    )

    per_persona = _per_persona_summaries(cases, per_metric_full, per_metric_random)
    strata = _strata(split, cases, per_metric_full, per_metric_random)

    return SplitResult(
        split=split,
        n_cases=len(cases),
        n_personas=len(personas),
        metrics=metrics,
        metrics_clustered=metrics_clustered,
        reference_random=reference["random"],
        reference_catalogue_order=reference["catalogue_order"],
        reference_oracle=reference["oracle"],
        reference_intent_filter_static=reference["intent_filter_static"],
        reference_clustered=reference_clustered,
        lifts=lifts,
        learning_curve=learning_curve,
        cases_to_beat_random=cases_to_beat_random,
        max_trace_events=max((len(persona.trace) for persona in personas), default=0),
        discriminable_cases=len(discriminable),
        metrics_discriminable=metrics_discriminable,
        reference_discriminable=reference_discriminable,
        lifts_discriminable=lifts_discriminable,
        per_persona=per_persona,
        strata=strata,
        personalisation_divergence=personalisation,
        reasons_grounded=Rate(numerator=grounded_total, denominator=verifiable_total),
        reasons_grounded_stat=reasons_grounded_stat,
        catalogue_filler_count=catalogue_filler_total,
        ablation_deltas=ablation_deltas,
        ablation_deltas_clustered=ablation_deltas_clustered,
        arm_effects=arm_effects,
        cases=cases,
    )


def _breakdown_signature(ranked: list[RankedScore]) -> dict[str, tuple[tuple[str, float], ...]]:
    return {
        item.ranked.candidate.activity_id: tuple(
            (factor.name, factor.contribution) for factor in item.breakdown.factors
        )
        for item in ranked
    }


def _arm_effect_on_case(case: CaseResult, arm: str) -> tuple[bool, bool]:
    """`(did any weighted contribution move, did the order move)` for one arm on one case,
    measured against that arm's OWN baseline rather than always against `full`."""
    baseline = case.arms[ablations.baseline_for(arm)]
    ranked = case.arms[arm]
    scores_changed = _breakdown_signature(baseline) != _breakdown_signature(ranked)
    order_changed = [item.ranked.candidate.activity_id for item in baseline] != [
        item.ranked.candidate.activity_id for item in ranked
    ]
    return scores_changed, order_changed


def _learning_curve(
    per_metric_arm: dict[str, dict[str, list[float]]],
    per_metric_random: dict[str, list[float]],
    clusters: list[str],
    cluster_seed: int,
) -> tuple[LearningCurvePoint, ...]:
    points = []
    arms = [
        (ablations.ARM_COLD_START, 0),
        (ablations.ARM_FIRST_SIGNAL, 1),
        *((ablations.trace_prefix_arm(k), k) for k in ablations.TRACE_PREFIX_LENGTHS),
        (ablations.ARM_FULL, -1),
    ]
    for arm, events in arms:
        values = per_metric_arm[arm]
        points.append(
            LearningCurvePoint(
                arm=arm,
                trace_events=events,
                ndcg_at_1=round(sum(values["ndcg_at_1"]) / len(values["ndcg_at_1"]), 4),
                hit_rate_at_3=round(sum(values["hit_rate_at_3"]) / len(values["hit_rate_at_3"]), 4),
                ndcg_at_3=round(sum(values[HEADLINE_METRIC]) / len(values[HEADLINE_METRIC]), 4),
                lift_over_random=cluster_paired_delta(
                    per_metric_random[HEADLINE_METRIC],
                    values[HEADLINE_METRIC],
                    clusters,
                    seed=cluster_seed,
                ),
            )
        )
    # `full` is the whole trace; sorting it last keeps the curve monotone in evidence.
    return tuple(sorted(points, key=lambda point: (point.trace_events < 0, point.trace_events)))


def _per_persona_summaries(
    cases: list[CaseResult],
    per_metric_full: dict[str, list[float]],
    per_metric_random: dict[str, list[float]],
) -> tuple[PersonaSummary, ...]:
    by_persona: dict[str, list[int]] = {}
    for index, case in enumerate(cases):
        by_persona.setdefault(case.persona.person_id, []).append(index)
    personas = {case.persona.person_id: case.persona for case in cases}
    summaries = []
    for person_id, indices in by_persona.items():
        persona = personas[person_id]
        full_values = [per_metric_full[HEADLINE_METRIC][index] for index in indices]
        random_values = [per_metric_random[HEADLINE_METRIC][index] for index in indices]
        summaries.append(
            PersonaSummary(
                person_id=person_id,
                display_name=persona.display_name,
                n_cases=len(indices),
                stated=persona_states_a_graded_fact(persona),
                ndcg_at_3=round(sum(full_values) / len(full_values), 4),
                random_ndcg_at_3=round(sum(random_values) / len(random_values), 4),
            )
        )
    return tuple(summaries)


def _strata(
    split: str,
    cases: list[CaseResult],
    per_metric_full: dict[str, list[float]],
    per_metric_random: dict[str, list[float]],
) -> tuple[StratumResult, ...]:
    """The stated / inferred-only split of the headline, with each side's own clustered lift.

    The inferred-only stratum is the one the benchmark claims to measure. On the holdout set the
    stated stratum is a single persona, which is exactly why it is printed with its cluster count
    rather than folded into one mean.
    """
    strata = []
    for name, want_stated in ((STATED_STRATUM, True), (INFERRED_ONLY_STRATUM, False)):
        indices = [
            index
            for index, case in enumerate(cases)
            if persona_states_a_graded_fact(case.persona) is want_stated
        ]
        persona_ids = tuple(dict.fromkeys(cases[index].persona.person_id for index in indices))
        clusters = [cases[index].persona.person_id for index in indices]
        seed = _seed(split, "stratum", name)
        metrics = {
            metric: cluster_bootstrap_stat(
                [per_metric_full[metric][index] for index in indices], clusters, seed=seed
            )
            for metric in _REFERENCE_METRIC_NAMES
        }
        reference_random = {
            metric: cluster_bootstrap_stat(
                [per_metric_random[metric][index] for index in indices], clusters, seed=seed
            )
            for metric in _REFERENCE_METRIC_NAMES
        }
        lift = cluster_paired_delta(
            [per_metric_random[HEADLINE_METRIC][index] for index in indices],
            [per_metric_full[HEADLINE_METRIC][index] for index in indices],
            clusters,
            seed=seed,
        )
        strata.append(
            StratumResult(
                name=name,
                persona_ids=persona_ids,
                metrics=metrics,
                reference_random=reference_random,
                lift_over_random=lift,
            )
        )
    return tuple(strata)


@dataclass(frozen=True)
class RankingEvaluationResult:
    generator_version: str
    seed: int
    dataset_digest: str
    core: SplitResult
    holdout: SplitResult
    holdout_digest: str = ""
    holdout_frozen: bool = False
    """Whether `HOLDOUT_PERSONAS` still hashes to the digest they were frozen at
    (`dataset.HOLDOUT_FROZEN_DIGEST`). Printed on every run: a holdout that is a list in a file
    rather than a process is a holdout in name only."""


def run_evaluation() -> RankingEvaluationResult:
    core = _run_split(CORE_SPLIT, CORE_PERSONAS)
    holdout = _run_split(HOLDOUT_SPLIT, HOLDOUT_PERSONAS)
    return RankingEvaluationResult(
        generator_version=GENERATOR_VERSION,
        seed=RANKING_EVAL_SEED,
        dataset_digest=dataset_digest(),
        core=core,
        holdout=holdout,
        holdout_digest=holdout_digest(),
        holdout_frozen=holdout_frozen(),
    )


__all__ = [
    "ArmEffect",
    "LearningCurvePoint",
    "case_is_discriminable",
    "CaseResult",
    "PersonaSummary",
    "RankingEvaluationResult",
    "SplitResult",
    "StratumResult",
    "persona_states_a_graded_fact",
    "run_case",
    "run_evaluation",
]
