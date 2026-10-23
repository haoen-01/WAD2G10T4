from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from silverloop.activity_search import RANKING_WEIGHTS, ActivityEngagement
from silverloop.evaluation.ranking import ablations
from silverloop.evaluation.ranking.context_labels import (
    CONTEXT_GOOD_FIT,
    CONTEXT_POOR_FIT,
    CONTEXT_UNKNOWN_FIT,
    grade_context_fit,
)
from silverloop.evaluation.ranking.dataset import (
    ALL_PERSONAS,
    CATALOGUE_BY_ID,
    CORE_PERSONAS,
    FROZEN_TODAY,
    HOLDOUT_PERSONAS,
    QUERY_TEMPLATES,
    PersonaBrief,
    dataset_digest,
)
from silverloop.evaluation.ranking.metrics import (
    RELEVANT_THRESHOLD,
    Delta,
    bootstrap_stat,
    cluster_bootstrap_stat,
    cluster_paired_delta,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    paired_delta,
    precision_at_k,
    slate_ndcg_at_k,
)
from silverloop.evaluation.ranking.report import check_artifacts, weights_digest, write_artifacts
from silverloop.evaluation.ranking.runner import (
    HEADLINE_METRIC_NAMES,
    INFERRED_ONLY_STRATUM,
    STATED_STRATUM,
    ArmEffect,
    RankingEvaluationResult,
    ReasonBasis,
    _reason_grounded,
    persona_states_a_graded_fact,
    run_case,
    run_evaluation,
)
from silverloop.models import ActivityCandidate, ActivityEnvironment, ActivityIntent

# --- One shared run ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def result() -> RankingEvaluationResult:
    """`run_evaluation()` is pure and deterministic, so one run serves every test that only reads
    its numbers -- the alternative is twenty identical two-second runs. The determinism test below
    deliberately does NOT use this fixture: it has to call the generator twice itself.
    """
    return run_evaluation()


# --- Module boundary -------------------------------------------------------------------------


def test_ranking_evaluation_imports_no_database_or_llm_module() -> None:
    script = (
        "import sys; import silverloop.evaluation.ranking; "
        "import silverloop.evaluation.ranking.runner; "
        "forbidden = {'silverloop.sql_repository', 'silverloop.db_models', "
        "'silverloop.main', 'silverloop.config', 'silverloop.agent', "
        "'silverloop.agent.planner', 'anthropic', 'openai', 'boto3'}; "
        "loaded = forbidden & set(sys.modules); "
        "assert not loaded, loaded; "
        "print('OK')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1] / "src",
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "OK" in completed.stdout


# --- Dataset -----------------------------------------------------------------------------------


def test_dataset_digest_is_stable() -> None:
    assert dataset_digest() == dataset_digest()
    digest = dataset_digest()
    assert len(digest) == 64
    int(digest, 16)  # a valid hex digest


def test_weights_digest_is_stable() -> None:
    assert weights_digest() == weights_digest()
    assert len(weights_digest()) == 64


def test_labels_never_reference_ranking_weights_keys() -> None:
    """A persona's stated taste/avoid names a `PreferenceDimension` value (distance, intensity,
    timing, social, environment, category); it must never accidentally collide with one of the
    six named ranking FACTORS (`RANKING_WEIGHTS`' keys: intent, preference, engagement,
    repetition, context, friction) -- the two vocabularies must stay visibly disjoint, or a future
    reader could mistake a taste for a factor.
    """
    weight_keys = set(RANKING_WEIGHTS)
    for persona in ALL_PERSONAS:
        for dimension, value in (
            *persona.stated_tastes,
            *persona.soft_avoids,
            *persona.hard_avoids,
        ):
            assert dimension.value not in weight_keys
            assert value not in weight_keys


def test_holdout_personas_disjoint_from_core() -> None:
    core_ids = {p.person_id for p in CORE_PERSONAS}
    holdout_ids = {p.person_id for p in HOLDOUT_PERSONAS}
    assert core_ids.isdisjoint(holdout_ids)
    assert core_ids | holdout_ids == {p.person_id for p in ALL_PERSONAS}


# --- Metrics: hand-computed cases -----------------------------------------------------------


def test_ndcg_hand_computed_case() -> None:
    # relevances [0, 0, 3]: dcg = 7/log2(4) = 3.5; ideal [3, 0, 0]: dcg = 7/log2(2) = 7.
    assert ndcg_at_k([0, 0, 3], k=3) == pytest.approx(0.5)


def test_ndcg_perfect_order_is_one() -> None:
    assert ndcg_at_k([3, 2, 0], k=3) == pytest.approx(1.0)


def test_ndcg_all_zero_is_zero_not_one() -> None:
    assert ndcg_at_k([0, 0, 0], k=3) == 0.0


def test_ndcg_empty_is_zero() -> None:
    assert ndcg_at_k([], k=3) == 0.0


def test_precision_at_3_hand_computed() -> None:
    assert precision_at_k([0, 0, 3], k=3, threshold=2) == pytest.approx(1 / 3)
    assert precision_at_k([3, 2, 1], k=3, threshold=2) == pytest.approx(2 / 3)


def test_mrr_hand_computed() -> None:
    assert mrr([0, 0, 3], threshold=2) == pytest.approx(1 / 3)
    assert mrr([2, 0, 0], threshold=2) == pytest.approx(1.0)
    assert mrr([0, 0, 0], threshold=2) == 0.0


def test_bootstrap_stat_is_deterministic() -> None:
    values = [0.1, 0.4, 0.9, 0.2, 0.6]
    first = bootstrap_stat(values, seed=42)
    second = bootstrap_stat(values, seed=42)
    assert first == second


def test_paired_delta_reports_not_exercised_when_identical() -> None:
    delta = paired_delta([0.5, 0.5, 0.5], [0.5, 0.5, 0.5], seed=1)
    assert delta.exercised is False
    assert delta.mean == 0.0


def test_paired_delta_reports_exercised_on_any_difference() -> None:
    delta = paired_delta([0.5, 0.5, 0.5], [0.5, 0.6, 0.5], seed=1)
    assert delta.exercised is True


# --- Context-rule conformance: a SEPARATE metric from relevance, NOT independent validation --


def test_grade_context_fit_good_fit_when_no_rain() -> None:
    outdoor = CATALOGUE_BY_ID["tai-chi-1"]
    assert grade_context_fit(outdoor, ActivityIntent(), rain_forecast=False) == CONTEXT_GOOD_FIT


def test_grade_context_fit_good_fit_when_environment_was_explicitly_asked_for() -> None:
    """An explicit ask about environment outranks the weather -- the same asymmetry
    `activity_search.score_candidate` applies to its own rain nudge."""
    outdoor = CATALOGUE_BY_ID["tai-chi-1"]
    intent = ActivityIntent(environment=ActivityEnvironment.OUTDOOR)
    assert grade_context_fit(outdoor, intent, rain_forecast=True) == CONTEXT_GOOD_FIT


def test_grade_context_fit_poor_fit_outdoor_in_rain_when_left_open() -> None:
    outdoor = CATALOGUE_BY_ID["tai-chi-1"]
    assert grade_context_fit(outdoor, ActivityIntent(), rain_forecast=True) == CONTEXT_POOR_FIT


def test_grade_context_fit_good_fit_indoor_in_rain_when_left_open() -> None:
    indoor = CATALOGUE_BY_ID["aqua-1"]
    assert grade_context_fit(indoor, ActivityIntent(), rain_forecast=True) == CONTEXT_GOOD_FIT


def test_grade_context_fit_unknown_fit_when_listing_does_not_say() -> None:
    from silverloop.models import IndoorOutdoor

    unlisted = next(
        c for c in CATALOGUE_BY_ID.values() if c.indoor_outdoor == IndoorOutdoor.UNKNOWN
    )
    assert grade_context_fit(unlisted, ActivityIntent(), rain_forecast=True) == CONTEXT_UNKNOWN_FIT


def test_context_rule_conformance_is_reported_alongside_relevance_ndcg_and_can_disagree(
    result: RankingEvaluationResult,
) -> None:
    """Two SEPARATE metrics over the same ranked list, not two independent judgements of it:
    `context_rule_conformance_at_3` is graded by a rule that restates the ranker's own `context`
    factor premise (see `context_labels.py`), so it measures whether that factor is wired and
    behaves as declared -- reported beside relevance NDCG so the two are never conflated into one
    number, not because they validate each other.
    """
    assert "ndcg_at_3" in result.core.metrics
    assert "context_rule_conformance_at_3" in result.core.metrics
    assert (
        result.core.metrics["ndcg_at_3"].mean
        != result.core.metrics["context_rule_conformance_at_3"].mean
    )


def test_removing_context_improves_relevance_ndcg_but_breaks_context_rule_conformance(
    result: RankingEvaluationResult,
) -> None:
    """ADR 0003's evidence, pinned as a regression test -- read this as an IMPLEMENTATION-
    CONFORMANCE check, not as validation of the rain nudge. On THIS dataset, `no_context` looks
    like a relevance win only because the relevance labels never encode weather (`labels.py` reads
    only the persona brief). `context_rule_conformance_at_3` is graded by a rule that deliberately
    restates the SAME rain/environment premise the `context` factor encodes (it does not import
    `activity_search`, but it shares its premise by construction -- see `context_labels.py`), so
    this second assertion is close to tautological: removing the factor a conformance check was
    defined from breaks conformance. It shows the factor is wired and does what it declares; it is
    NOT independent evidence that the rain nudge is a good idea. If this ever stops holding, ADR
    0003's decision (keep `context` as a ranking factor; do not restructure the ranker on the
    strength of the relevance benchmark alone) should be revisited.
    """
    arm = ablations.factor_arm("context")
    no_context = result.core.ablation_deltas[arm]
    clustered = result.core.ablation_deltas_clustered[arm]
    assert no_context["ndcg_at_3"].mean > 0
    assert no_context["context_rule_conformance_at_3"].mean < 0
    assert no_context["context_rule_conformance_at_3"].ci_high < 0
    # ...and it survives the honest, persona-clustered interval too.
    assert clustered["context_rule_conformance_at_3"].ci_high < 0


# --- The full run --------------------------------------------------------------------------


def test_run_evaluation_is_deterministic() -> None:
    from silverloop.evaluation.ranking.report import to_json_document

    first = to_json_document(run_evaluation())
    second = to_json_document(run_evaluation())
    assert first == second


def test_random_floor_is_strictly_below_full_on_ndcg_at_3(result: RankingEvaluationResult) -> None:
    """An NDCG without a random floor is not a result (E1's own words).

    Comparing two means is the weakest form of this check and the evaluation review said so: it
    passes whatever the uncertainty. The paired, persona-clustered CI below is the test that can
    actually fail, and it is asserted for the core set only -- on holdout the same interval
    includes zero today, which the artifact reports as a finding rather than something this suite
    pins in place.
    """
    assert result.core.reference_random["ndcg_at_3"].mean < result.core.metrics["ndcg_at_3"].mean
    assert (
        result.holdout.reference_random["ndcg_at_3"].mean < result.holdout.metrics["ndcg_at_3"].mean
    )
    core_lift = result.core.lifts["random"]
    assert core_lift.n_clusters == result.core.n_personas
    assert core_lift.excludes_zero, core_lift
    assert core_lift.ci_low > 0


# --- Persona-clustered confidence intervals ---------------------------------------------------


def test_cluster_bootstrap_is_wider_than_case_bootstrap_when_clusters_disagree() -> None:
    """The whole point of the clustered interval: when the clusters disagree with each other, the
    per-case bootstrap pretends to more evidence than the design supplies."""
    values = [0.2] * 6 + [0.9] * 6
    clusters = ["a"] * 6 + ["b"] * 6
    per_case = bootstrap_stat(values, seed=11)
    clustered = cluster_bootstrap_stat(values, clusters, seed=11)
    assert clustered.mean == per_case.mean
    assert clustered.n == 12
    assert clustered.n_clusters == 2
    assert (clustered.ci_high - clustered.ci_low) > (per_case.ci_high - per_case.ci_low)


def test_cluster_bootstrap_collapses_onto_the_mean_for_a_single_cluster() -> None:
    """One cluster carries no between-cluster information; the CI says so rather than inventing a
    width, the same honesty `Rate.rate` applies to a zero denominator."""
    stat = cluster_bootstrap_stat([0.1, 0.9, 0.5], ["only"] * 3, seed=3)
    assert stat.n_clusters == 1
    assert stat.ci_low == stat.ci_high == stat.mean


def test_cluster_paired_delta_pairs_by_case_and_resamples_clusters() -> None:
    baseline = [0.1, 0.1, 0.1, 0.5, 0.5, 0.5]
    arm = [0.2, 0.2, 0.2, 0.9, 0.9, 0.9]
    clusters = ["a", "a", "a", "b", "b", "b"]
    delta = cluster_paired_delta(baseline, arm, clusters, seed=5)
    assert delta.mean == pytest.approx(0.25, abs=1e-4)
    assert delta.n == 6
    assert delta.n_clusters == 2
    assert delta.exercised is True


def test_cluster_bootstrap_rejects_misaligned_inputs() -> None:
    with pytest.raises(ValueError):
        cluster_bootstrap_stat([0.1, 0.2], ["a"], seed=1)


def test_every_ci_header_states_n_and_n_clusters(result: RankingEvaluationResult) -> None:
    """E3's own pinning test: no interval is printed without the count of INDEPENDENT things
    behind it."""
    from silverloop.evaluation.ranking.report import to_markdown

    markdown = to_markdown(result)
    clustered_rows = [
        line for line in markdown.splitlines() if "n_clusters=" in line and line.startswith("|")
    ]
    assert clustered_rows
    for line in markdown.splitlines():
        if "n_clusters=" in line:
            assert "n=" in line
    assert "(n=60, n_clusters=10" in markdown
    assert "(n=24, n_clusters=4" in markdown


def test_every_arm_comparison_carries_a_paired_clustered_delta(
    result: RankingEvaluationResult,
) -> None:
    for split in (result.core, result.holdout):
        assert set(split.ablation_deltas_clustered) == set(split.ablation_deltas)
        for arm, deltas in split.ablation_deltas_clustered.items():
            for name, delta in deltas.items():
                assert delta.n == split.n_cases, (arm, name)
                assert delta.n_clusters == split.n_personas, (arm, name)


def test_headline_lift_is_reported_per_stratum_with_the_inferred_only_number_headlined(
    result: RankingEvaluationResult,
) -> None:
    """E2's finding, made structural: the stated stratum measures "obey what you were just told",
    the inferred-only stratum measures what the benchmark claims to measure, and the artifact
    quotes the second."""
    from silverloop.evaluation.ranking.report import to_markdown

    for split in (result.core, result.holdout):
        names = [stratum.name for stratum in split.strata]
        assert names == [STATED_STRATUM, INFERRED_ONLY_STRATUM]
        stated, inferred = split.strata
        assert set(stated.persona_ids).isdisjoint(inferred.persona_ids)
        assert stated.lift_over_random.n + inferred.lift_over_random.n == split.n_cases

    markdown = to_markdown(result)
    assert f"The number to quote is the `{INFERRED_ONLY_STRATUM}` one" in markdown


def test_stated_stratum_is_exactly_the_personas_whose_brief_fact_was_handed_over() -> None:
    """The stratum rule is an exact `(dimension, value)` match against the grading brief, not a
    guess: `eval-mr-goh` and `eval-mr-yusof` on core, `eval-mr-lim-kw` on holdout."""
    stated = {p.person_id for p in ALL_PERSONAS if persona_states_a_graded_fact(p)}
    assert stated == {"eval-mr-goh", "eval-mr-yusof", "eval-mr-lim-kw"}


def test_holdout_lift_over_random_is_reported_with_its_cluster_count(
    result: RankingEvaluationResult,
) -> None:
    """Not an assertion about the direction -- an assertion that the reader is told how many
    independent personas the holdout number rests on (four), because it rests on very few."""
    lift = result.holdout.lifts["random"]
    assert lift.n_clusters == 4
    assert lift.n == 24


def test_per_persona_table_reports_every_persona_including_the_worst(
    result: RankingEvaluationResult,
) -> None:
    for split in (result.core, result.holdout):
        assert len(split.per_persona) == split.n_personas
        assert sum(summary.n_cases for summary in split.per_persona) == split.n_cases
    worst = min(result.core.per_persona, key=lambda summary: summary.ndcg_at_3)
    assert worst.ndcg_at_3 < result.core.metrics["ndcg_at_3"].mean


def test_personalisation_divergence_is_clustered_by_unordered_persona_pair(
    result: RankingEvaluationResult,
) -> None:
    """Pair values are drawn from at most the 45 unordered pairs over 10 personas; the pairs that
    share a persona are dependent, so the pair is the cluster. A pair whose preference stores
    agree on every candidate in their shared pool contributes nothing, so fewer than 45 clusters
    is a property of the dataset, not a clustering error."""
    divergence = result.core.personalisation_divergence
    assert 0 < divergence.n_clusters <= 45
    assert divergence.n_clusters < divergence.n


def test_oracle_ndcg_at_3_is_one(result: RankingEvaluationResult) -> None:
    assert result.core.reference_oracle["ndcg_at_3"].mean == pytest.approx(1.0)
    assert result.holdout.reference_oracle["ndcg_at_3"].mean == pytest.approx(1.0)


def test_by_construction_metrics_are_gone_from_the_artifact(
    result: RankingEvaluationResult,
) -> None:
    """`constraint_satisfaction@3` was `1.0 if top else 0.0` and `series_duplication_rate@3` was
    0.0000 on every arm because `_dedupe_series` always runs. Neither could fail, and both
    occupied a headline row and a row in every ablation table. They are now unit tests on
    `activity_search` (`test_every_hard_constraint_violation_is_removed_before_ranking_ever_sees_it`
    and `test_the_top_three_never_repeat_a_series_however_many_sessions_are_offered`), where a
    regression fails something.
    """
    for split in (result.core, result.holdout):
        assert "constraint_satisfaction_at_3" not in split.metrics
        assert "series_duplication_rate_at_3" not in split.metrics
        for deltas in split.ablation_deltas.values():
            assert "constraint_satisfaction_at_3" not in deltas
            assert "series_duplication_rate_at_3" not in deltas


# --- The metric family that replaces the single NDCG@3 ------------------------------------------


def test_hit_rate_at_k_hand_computed() -> None:
    assert hit_rate_at_k([0, 0, 3], k=3, threshold=3) == 1.0
    assert hit_rate_at_k([2, 2, 2], k=3, threshold=3) == 0.0
    assert hit_rate_at_k([3, 0, 0], k=1, threshold=3) == 1.0
    # Blind to position on purpose -- `NDCG@1` is the metric that asks about position.
    assert hit_rate_at_k([0, 3], k=3, threshold=3) == hit_rate_at_k([3, 0], k=3, threshold=3)
    assert hit_rate_at_k([], k=3, threshold=3) == 0.0


def test_slate_ndcg_ideal_is_computed_under_the_one_per_category_rule() -> None:
    # Three grade-3 listings, all the same category, plus a grade-2 of another kind. Plain NDCG's
    # ideal is [3,3,3] (a slate the product refuses to show); the slate ideal is [3,2,...].
    relevances = [3, 3, 3, 2]
    assert ndcg_at_k(relevances, 3) == pytest.approx(1.0)
    diversified = slate_ndcg_at_k([3, 2, 3], ["Tai Chi", "Gardening", "Tai Chi"], 3)
    assert diversified == pytest.approx(1.0)
    # A listing with no category is never "a kind", so it is not subject to the constraint.
    assert slate_ndcg_at_k([3, 3], [None, None], 2) == pytest.approx(1.0)


def test_slate_ndcg_does_not_penalise_a_category_swap_within_margin() -> None:
    """E8's finding: nine of fourteen personas' only route to a grade 3 is a CATEGORY taste and
    each category has five listings, so plain NDCG@3's optimum is three sessions of one kind --
    exactly the slate `_diversify` exists to prevent. Under the constrained ideal the swap costs
    nothing.
    """
    same_kind = [3, 3, 3, 2]
    swapped = [3, 3, 2, 3]
    categories_same = ["Choir", "Choir", "Choir", "Mahjong"]
    categories_swapped = ["Choir", "Choir", "Mahjong", "Choir"]
    assert ndcg_at_k(swapped, 3) < ndcg_at_k(same_kind, 3)
    assert slate_ndcg_at_k(swapped, categories_swapped, 3) >= slate_ndcg_at_k(
        same_kind, categories_same, 3
    )


def test_slate_ndcg_never_rewards_breaking_the_product_s_own_rule() -> None:
    """A slate can only out-score the constrained ideal by putting two of one kind in the top
    three; the cap says that is not better, rather than scoring it above 1.0."""
    value = slate_ndcg_at_k([3, 3, 3, 2], ["A", "A", "A", "B"], 3)
    assert value == pytest.approx(1.0)


def test_relevance_threshold_counts_a_taste_match_not_a_neutral_listing() -> None:
    """`P@3 (rel>=2)` measured pool composition: 77.8% of the core kept pool grades >=2 and a
    random shuffle already scored 0.788 on it."""
    from silverloop.evaluation.ranking.labels import GRADE_NEUTRAL, GRADE_TASTE_MATCH

    assert RELEVANT_THRESHOLD == GRADE_TASTE_MATCH
    assert RELEVANT_THRESHOLD > GRADE_NEUTRAL
    assert precision_at_k([2, 2, 2], k=3) == 0.0
    assert mrr([2, 2, 3]) == pytest.approx(1 / 3)


def test_the_headline_family_is_reported_for_every_split(
    result: RankingEvaluationResult,
) -> None:
    for split in (result.core, result.holdout):
        for name in HEADLINE_METRIC_NAMES:
            assert name in split.metrics
            assert name in split.metrics_clustered
            assert name in split.reference_random


def test_discriminable_cases_are_counted_and_the_headline_is_reported_over_them(
    result: RankingEvaluationResult,
) -> None:
    from silverloop.evaluation.ranking.runner import case_is_discriminable

    for split in (result.core, result.holdout):
        assert 0 < split.discriminable_cases <= split.n_cases
        expected = sum(1 for case in split.cases if case_is_discriminable(case))
        assert split.discriminable_cases == expected
        for name in HEADLINE_METRIC_NAMES:
            assert split.metrics_discriminable[name].n == split.discriminable_cases
        assert split.lifts_discriminable["random"].n == split.discriminable_cases


def _achievable_headline_scores(case: object) -> set[float]:
    """Every value the headline metric can take over the orderings of this case's kept pool.

    `NDCG@3` depends on the first three graded items (in order) and on the pool's whole grade
    multiset, so enumerating the ordered triples of grades enumerates the achievable scores --
    without enumerating 29! orderings. Deduplicated first, because grades only take four values
    and the distinct triples number at most 4^3.
    """
    import itertools

    from silverloop.evaluation.ranking.metrics import dcg
    from silverloop.evaluation.ranking.runner import TOP_K

    grades = [case.grades[candidate.activity_id] for candidate in case.kept]  # type: ignore[attr-defined]
    if not grades:
        return {0.0}
    ideal = dcg(sorted(grades, reverse=True)[:TOP_K])
    if ideal == 0:
        return {0.0}
    triples = set(itertools.permutations(grades, min(TOP_K, len(grades))))
    return {dcg(list(triple)) / ideal for triple in triples}


def test_a_case_is_non_discriminable_exactly_when_every_ordering_scores_the_same(
    result: RankingEvaluationResult,
) -> None:
    """The property the stratum is named for, checked by enumeration rather than restated.

    The filter used to require a grade-3 taste match AND something graded <=1, justified in the
    artifact as "every ordering of them scores identically". That sentence was false for 21 of the
    60 core cases the filter dropped and 14 of the 24 on holdout -- a pool holding a grade-2 and a
    grade-0, or a grade-3 and a grade-2, discriminates perfectly well. Whole personas were leaving
    the stratum the headline is quoted over.
    """
    from silverloop.evaluation.ranking.runner import case_is_discriminable

    for split in (result.core, result.holdout):
        for case in split.cases:
            achievable = _achievable_headline_scores(case)
            assert case_is_discriminable(case) is (len(achievable) > 1), (
                split.split,
                case.persona.person_id,
                case.template.name,
            )


def test_the_discriminable_rule_is_equivalent_to_a_pool_whose_grades_differ(
    result: RankingEvaluationResult,
) -> None:
    """The plain-English restatement the artifact prints beside the count. It is a claim about
    this dataset and this metric, not a definition, so it is asserted rather than assumed."""
    from silverloop.evaluation.ranking.runner import case_is_discriminable

    for split in (result.core, result.holdout):
        for case in split.cases:
            grades = {case.grades[candidate.activity_id] for candidate in case.kept}
            assert case_is_discriminable(case) is (len(grades) > 1)


def test_intent_filter_static_floor_is_reported_beside_random_and_catalogue_order(
    result: RankingEvaluationResult,
) -> None:
    """The floor E9 said was missing: the same filtered pool sorted by distance then title -- what
    a rule-based catalogue app would do, with nothing learned, no history and no weather."""
    from silverloop.evaluation.ranking.runner import REFERENCE_LINES

    assert "intent_filter_static" in REFERENCE_LINES
    for split in (result.core, result.holdout):
        assert set(split.reference_intent_filter_static) == set(split.reference_random)
        assert "intent_filter_static" in split.lifts
        assert split.lifts["intent_filter_static"].n_clusters == split.n_personas
    # It is a genuinely stronger floor than a shuffle on the headline metric.
    assert (
        result.core.reference_intent_filter_static["ndcg_at_3"].mean
        > result.core.reference_random["ndcg_at_3"].mean
    )


def test_intent_filter_static_floor_sorts_by_distance_then_title() -> None:
    from silverloop.evaluation.ranking.runner import _intent_filter_static_metrics, ndcg_at_k

    case = run_case("core", CORE_PERSONAS[0], QUERY_TEMPLATES[0])
    ordered = sorted(
        case.kept,
        key=lambda candidate: (
            float(candidate.distance_m) if candidate.distance_m is not None else float("inf"),
            candidate.title,
        ),
    )
    expected = ndcg_at_k([case.grades[c.activity_id] for c in ordered], 3)
    assert _intent_filter_static_metrics(case)["ndcg_at_3"] == pytest.approx(expected)


# --- Ablations: each changes only its own input ----------------------------------------------


def _contributions(ranked) -> dict[str, dict[str, float]]:
    return {
        item.ranked.candidate.activity_id: {
            factor.name: factor.contribution for factor in item.breakdown.factors
        }
        for item in ranked
    }


def _values(ranked) -> dict[str, dict[str, float]]:
    return {
        item.ranked.candidate.activity_id: {
            factor.name: factor.value for factor in item.breakdown.factors
        }
        for item in ranked
    }


def test_each_factor_arm_changes_exactly_one_factor_contribution() -> None:
    """The structural guard the evaluation review asked for, and the one the old version got
    wrong. Counting differing KEYWORD ARGUMENTS said `no_engagement` was a clean single-factor
    ablation when it also zeroes `repetition`; this counts differing FACTOR CONTRIBUTIONS on the
    real `ScoreBreakdown`s instead, over every core case, so a confounded arm cannot pass.
    """
    for persona in CORE_PERSONAS:
        for template in QUERY_TEMPLATES:
            case = run_case("core", persona, template)
            full = _contributions(case.arms[ablations.ARM_FULL])
            full_values = _values(case.arms[ablations.ARM_FULL])
            for name in ablations.FACTOR_NAMES:
                arm = ablations.factor_arm(name)
                arm_contributions = _contributions(case.arms[arm])
                arm_values = _values(case.arms[arm])
                assert arm_contributions.keys() == full.keys(), (arm, persona.person_id)
                for activity_id, contributions in arm_contributions.items():
                    moved = {
                        factor
                        for factor, contribution in contributions.items()
                        if contribution != full[activity_id][factor]
                    }
                    assert moved <= {name}, (arm, persona.person_id, template.name, moved)
                    assert contributions[name] == 0.0
                    # Every factor VALUE -- including the ablated one, and so the tier it feeds --
                    # is exactly what production computed.
                    assert arm_values[activity_id] == full_values[activity_id]


def test_confounded_input_arms_declare_every_factor_they_touch() -> None:
    """`input:no_engagement` moves `repetition` as well, and `input:no_intent` moves `context`.
    Both are legitimate arms; what was wrong was reporting them as single-factor ablations. The
    declared `touches` list is what the artifact prints, so it must be true of the real run.
    """
    persona = next(p for p in CORE_PERSONAS if p.person_id == "eval-mr-ong")
    template = next(t for t in QUERY_TEMPLATES if t.name == "tuesday_morning_indoors_gentle")
    case = run_case("core", persona, template)
    full = _contributions(case.arms[ablations.ARM_FULL])
    for arm in (ablations.ARM_INPUT_NO_INTENT, ablations.ARM_INPUT_NO_ENGAGEMENT):
        declared = set(ablations.ARM_SPECS[arm].touches)
        moved: set[str] = set()
        for activity_id, contributions in _contributions(case.arms[arm]).items():
            moved |= {
                factor
                for factor, contribution in contributions.items()
                if contribution != full[activity_id][factor]
            }
        assert moved, arm
        assert moved <= declared, (arm, moved - declared)
    # ...and the confound is real, not hypothetical: this arm does move a second factor.
    engagement_arm = _contributions(case.arms[ablations.ARM_INPUT_NO_ENGAGEMENT])
    assert any(
        contributions["repetition"] != full[activity_id]["repetition"]
        for activity_id, contributions in engagement_arm.items()
    )


def test_the_arm_count_matches_the_number_documented_in_testing_md() -> None:
    """R15 found three doc/code mismatches on the evaluation pages, one of them "Seven arms"
    against a code that had eight. This is the cheapest possible guard against the fourth: the
    number in `docs/testing.md` is pinned here, so adding an arm without touching the prose fails.
    """
    documented = 23  # docs/testing.md, "Ranking evaluation": `full` plus twenty-two ablations
    assert len(ablations.ABLATION_ARMS) == documented
    assert len(set(ablations.ABLATION_ARMS)) == documented
    assert ablations.ABLATION_ARMS[0] == ablations.ARM_FULL


def test_soft_arms_are_reported_against_no_diversity() -> None:
    """The baseline rule, enforced structurally rather than remembered: an arm that runs with the
    diversity swap off may only be compared to `no_diversity`. Comparing it to `full` is what put
    `no_diversity`'s own delta inside the old `no_intent_soft` number that ADR 0003 handed on.
    """
    for arm, spec in ablations.ARM_SPECS.items():
        if arm == ablations.ARM_FULL:
            assert spec.baseline == ablations.ARM_FULL
            continue
        if arm == ablations.ARM_NO_DIVERSITY:
            # The diversity ablation IS the swap's own delta, so it is the one diversity-off arm
            # measured against `full`.
            assert spec.baseline == ablations.ARM_FULL
            assert spec.diversity is False
            continue
        expected = ablations.ARM_NO_DIVERSITY if not spec.diversity else ablations.ARM_FULL
        assert spec.baseline == expected, arm


def test_factor_arms_re_run_the_production_post_scoring_passes() -> None:
    """`zero_factor` returns a PRE-postprocess list and the arm hands it back to
    `activity_search.postprocess`, so production's series dedupe holds on the re-sorted order --
    the gap the old hand-rolled re-sort left behind (its `series_duplication_rate@3` delta was
    +0.44, an artefact of skipping dedupe rather than a fact about the factor).
    """
    from silverloop.activity_search import series_key
    from silverloop.evaluation.ranking.runner import TOP_K

    for persona in CORE_PERSONAS:
        for template in QUERY_TEMPLATES:
            case = run_case("core", persona, template)
            for name in ablations.FACTOR_NAMES:
                ranked = case.arms[ablations.factor_arm(name)]
                keys = [series_key(item.ranked.candidate) for item in ranked[:TOP_K]]
                assert len(set(keys)) == len(keys), (name, persona.person_id, template.name)
                assert [item.ranked.rank for item in ranked] == list(range(1, len(ranked) + 1))


def test_every_preference_dimension_has_its_own_arm() -> None:
    """`distance_m` is scored three times over (`intent`, the DISTANCE preference, `friction`);
    a per-dimension arm is the only way to separate them."""
    from silverloop.models import PreferenceDimension

    for dimension in PreferenceDimension:
        arm = ablations.preference_dimension_arm(dimension)
        assert arm in ablations.ARM_SPECS
        assert ablations.ARM_SPECS[arm].touches == ("preference",)


def test_per_dimension_arm_drops_only_that_dimension() -> None:
    persona = next(p for p in CORE_PERSONAS if p.person_id == "eval-mdm-lee")
    template = QUERY_TEMPLATES[0]
    case = run_case("core", persona, template)
    from silverloop.models import PreferenceDimension

    dropped = PreferenceDimension.TIMING
    assert any(row.dimension is dropped for row in case.preferences.dimensions)
    arm = case.arms[ablations.preference_dimension_arm(dropped)]
    full = _contributions(case.arms[ablations.ARM_FULL])
    moved = {
        factor
        for activity_id, contributions in _contributions(arm).items()
        for factor, contribution in contributions.items()
        if contribution != full[activity_id][factor]
    }
    assert moved == {"preference"}


def test_a_masked_arm_says_masked_rather_than_not_exercised(
    result: RankingEvaluationResult,
) -> None:
    """R10's wording fix: a zero delta on an arm whose weighted contribution DID move is a masking
    result, not "this dataset does not exercise the factor". Which arms are masked is a property
    of the dataset (after the scoring rewrite none of the committed arms is), so the wording is
    pinned on constructed effects, and the artifact is only checked for consistency."""
    from silverloop.evaluation.ranking.report import _fmt_arm_delta

    zero = Delta(mean=0.0, ci_low=0.0, ci_high=0.0, exercised=False, n=60, n_clusters=10)
    untouched = ArmEffect(
        arm="x", baseline="full", n_cases=60, scores_changed_cases=0, order_changed_cases=0
    )
    by_tier = ArmEffect(
        arm="x", baseline="full", n_cases=60, scores_changed_cases=17, order_changed_cases=0
    )
    by_metric = ArmEffect(
        arm="x", baseline="full", n_cases=60, scores_changed_cases=17, order_changed_cases=20
    )
    assert _fmt_arm_delta(zero, untouched) == "this dataset does not exercise the factor"
    assert _fmt_arm_delta(zero, by_tier).startswith("masked by the tier sort")
    assert _fmt_arm_delta(zero, by_metric).startswith("masked by this metric")

    # On the committed artifact every arm the effect table calls masked must read as masked.
    for arm, effect in result.core.arm_effects.items():
        if arm not in result.core.ablation_deltas:
            continue
        delta = result.core.ablation_deltas[arm]["ndcg_at_3"]
        if not delta.exercised and effect.scores_changed_cases > 0:
            assert _fmt_arm_delta(delta, effect).startswith("masked by")


def test_no_diversity_is_the_production_pipeline_with_only_the_swap_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The arm runs the real ranker (tier sort and series dedupe included) with `diversity=False`,
    so its delta is attributable to the diversity swap alone -- not to a re-sort that would also
    drop the intent tier and the dedupe."""
    kwargs_seen: list[dict[str, object]] = []
    real = ablations.rank_candidates_with_breakdown
    monkeypatch.setattr(
        ablations,
        "rank_candidates_with_breakdown",
        lambda *a, **k: kwargs_seen.append(dict(k)) or real(*a, **k),
    )
    persona = CORE_PERSONAS[0]
    template = QUERY_TEMPLATES[0]
    case = run_case("core", persona, template)
    kwargs_seen.clear()
    ranked = ablations.rank_for_arm(
        ablations.ARM_NO_DIVERSITY,
        candidates=case.kept,
        intent=case.intent,
        preferences=case.preferences,
        engagement=case.engagement,
        today=FROZEN_TODAY,
        rain_forecast=template.rain_forecast,
        full_ranked=case.arms[ablations.ARM_FULL],
    )
    assert len(kwargs_seen) == 1 and kwargs_seen[0].get("diversity") is False
    assert not any(item.breakdown.variety_promoted for item in ranked)


# --- Cold start and the learning curve ---------------------------------------------------------


def test_cold_start_arm_has_no_learned_preference_and_no_history() -> None:
    """Day zero for a new person. Only `intent`, `context` and `friction` can move anything."""
    persona = next(p for p in CORE_PERSONAS if p.person_id == "eval-mdm-lee")
    case = run_case("core", persona, QUERY_TEMPLATES[0])
    assert case.preferences.dimensions  # ...she does have a trace, so this is a real ablation
    cold = case.arms[ablations.ARM_COLD_START]
    for item in cold:
        factors = {factor.name: factor for factor in item.breakdown.factors}
        assert factors["preference"].value == 0.0
        assert factors["engagement"].value == 0.0
        assert factors["repetition"].value == 0.0


def test_trace_prefix_arms_use_only_the_first_k_events() -> None:
    from silverloop.evaluation.ranking.traces import build_preferences, trace_prefix

    persona = next(p for p in CORE_PERSONAS if len(p.trace) >= 3)
    assert len(trace_prefix(persona, 0)) == 0
    assert len(trace_prefix(persona, 1)) == 1
    assert trace_prefix(persona, None) == persona.trace
    assert trace_prefix(persona, 99) == persona.trace
    assert build_preferences(persona, limit=0).dimensions == []
    # A longer prefix never forgets what a shorter one already taught the ranker.
    short = {(d.dimension, d.value) for d in build_preferences(persona, limit=1).dimensions}
    longer = {(d.dimension, d.value) for d in build_preferences(persona, limit=3).dimensions}
    assert short <= longer


def test_first_signal_and_trace_prefix_1_are_the_same_manipulation() -> None:
    """Two names for one arm, reported under both because the design names both. Asserting they
    agree exactly is the cheap check that the prefix machinery does what it says."""
    for persona in CORE_PERSONAS:
        case = run_case("core", persona, QUERY_TEMPLATES[2])
        first = [
            item.ranked.candidate.activity_id for item in case.arms[ablations.ARM_FIRST_SIGNAL]
        ]
        prefix = [
            item.ranked.candidate.activity_id for item in case.arms[ablations.trace_prefix_arm(1)]
        ]
        assert first == prefix, persona.person_id


def test_a_trace_prefix_at_or_above_the_longest_trace_equals_the_full_arm() -> None:
    persona = next(p for p in CORE_PERSONAS if len(p.trace) <= 3)
    case = run_case("core", persona, QUERY_TEMPLATES[0])
    saturated = [
        item.ranked.candidate.activity_id for item in case.arms[ablations.trace_prefix_arm(5)]
    ]
    full = [item.ranked.candidate.activity_id for item in case.arms[ablations.ARM_FULL]]
    assert saturated == full


def test_learning_curve_is_reported_and_cases_to_beat_random_is_the_first_k_that_excludes_zero(
    result: RankingEvaluationResult,
) -> None:
    """The only number that answers "how much evidence does the learner need before it helps"."""
    for split in (result.core, result.holdout):
        events = [point.trace_events for point in split.learning_curve]
        assert events == sorted(events, key=lambda k: (k < 0, k))
        assert events[0] == 0  # cold_start
        assert events[-1] == -1  # full, i.e. the whole trace
        for point in split.learning_curve:
            assert point.lift_over_random.n_clusters == split.n_personas

        excluding = [
            point.trace_events
            for point in split.learning_curve
            if point.trace_events >= 0 and point.lift_over_random.ci_low > 0
        ]
        assert split.cases_to_beat_random == (excluding[0] if excluding else None)
        assert split.max_trace_events == max(len(case.persona.trace) for case in split.cases)


def test_cold_start_alone_does_not_clear_the_random_floor_on_core(
    result: RankingEvaluationResult,
) -> None:
    """The finding the curve exists to surface: with no trace at all, the deterministic factors
    beat a random shuffle by +0.0156 with a CI that includes zero -- the lift the artifact
    headlines is bought by the first observation, not by the ranker's constants.
    """
    cold = next(
        point for point in result.core.learning_curve if point.arm == ablations.ARM_COLD_START
    )
    assert cold.lift_over_random.excludes_zero is False
    assert result.core.cases_to_beat_random == 1


# --- input:no_intent is confounded; factor:intent is the isolated version (ADR 0003) --------


def _context_values(ranked) -> dict[str, float]:
    return {
        item.ranked.candidate.activity_id: next(
            factor.value for factor in item.breakdown.factors if factor.name == "context"
        )
        for item in ranked
    }


def test_no_intent_confound_reenables_rain_for_an_explicit_environment_ask() -> None:
    """Pins the MAJOR review finding directly. `input:no_intent` substitutes an empty
    `ActivityIntent()`, which resets `environment` to `EITHER` and therefore switches
    `activity_search.score_candidate`'s rain nudge back on for a template that asked for a specific
    environment -- so that arm's own delta is not attributable to the intent factor alone; it is
    entangled with the context factor, which is why its `touches` list names both.
    `factor:intent` (the isolated version) leaves the real, explicit environment untouched, so its
    context factor matches `full` exactly. See ADR 0003's handoff section.
    """
    persona = CORE_PERSONAS[0]
    template = next(t for t in QUERY_TEMPLATES if t.name == "tuesday_morning_indoors_gentle")
    case = run_case("core", persona, template)
    assert case.intent.environment == ActivityEnvironment.INDOOR
    assert template.rain_forecast is True

    full_context = _context_values(case.arms[ablations.ARM_FULL])
    no_intent_context = _context_values(case.arms[ablations.ARM_INPUT_NO_INTENT])
    factor_intent_context = _context_values(case.arms[ablations.factor_arm("intent")])

    # `full`: the environment was explicit, so the rain nudge never applied here.
    assert all(value == 0.0 for value in full_context.values())
    # `input:no_intent`: environment resets to EITHER, so the rain nudge switches back on for some
    # candidates -- exactly the confound this test pins, verified against the real dataset.
    assert any(value != 0.0 for value in no_intent_context.values())
    # `factor:intent`: the real, explicit environment is untouched, so context matches `full`.
    assert factor_intent_context == full_context


def test_factor_intent_zeros_only_the_intent_contribution_and_keeps_the_real_tier() -> None:
    """The isolated ablation the intent ticket actually needs: the `intent` factor's own VALUE
    (and hence the tier it feeds -- `activity_search._tier`) is untouched, only its weighted
    CONTRIBUTION to `total` is removed, and the resulting order never crosses a tier boundary the
    real intent established.
    """
    persona = CORE_PERSONAS[0]
    template = next(t for t in QUERY_TEMPLATES if t.name == "meet_people_nearby")
    case = run_case("core", persona, template)
    full_by_id = {item.ranked.candidate.activity_id: item for item in case.arms[ablations.ARM_FULL]}
    soft_by_id = {
        item.ranked.candidate.activity_id: item
        for item in case.arms[ablations.factor_arm("intent")]
    }
    assert full_by_id.keys() == soft_by_id.keys()

    for activity_id, full_item in full_by_id.items():
        soft_item = soft_by_id[activity_id]
        full_by_name = {f.name: f for f in full_item.breakdown.factors}
        soft_by_name = {f.name: f for f in soft_item.breakdown.factors}
        # The intent factor's own VALUE is unchanged -- only its contribution to `total` moves.
        assert soft_by_name["intent"].value == full_by_name["intent"].value
        assert soft_by_name["intent"].contribution == 0.0
        expected_total = round(full_item.breakdown.total - full_by_name["intent"].contribution, 3)
        assert soft_item.breakdown.total == pytest.approx(expected_total)
        # Every other factor (including context) is untouched.
        for name in ("preference", "engagement", "repetition", "context", "friction"):
            assert soft_by_name[name].value == full_by_name[name].value
        # ... and so is the tier the re-sort orders by first.
        assert soft_item.breakdown.tier == full_item.breakdown.tier


def test_factor_intent_ablation_is_reported_in_the_artifact(
    result: RankingEvaluationResult,
) -> None:
    """The new arm flows through the same generic ablation reporting every other arm uses --
    reported for reference, per ADR 0003, without deciding the still-blocked intent-factor ticket.
    """
    assert ablations.factor_arm("intent") in result.core.ablation_deltas
    assert ablations.factor_arm("intent") in result.holdout.ablation_deltas
    assert "ndcg_at_3" in result.core.ablation_deltas[ablations.factor_arm("intent")]


# --- Reasons-grounded verifier ---------------------------------------------------------------


def test_reasons_grounded_intent_basis() -> None:
    persona = CORE_PERSONAS[0]
    template = QUERY_TEMPLATES[3]  # language_constrained
    case = run_case("core", persona, template)
    candidate = CATALOGUE_BY_ID["tai-chi-1"]  # English-tagged, matches an English-constrained ask
    assert _reason_grounded(ReasonBasis.INTENT, candidate, case, False) is True


def test_reasons_grounded_preference_basis_false_without_a_match() -> None:
    persona = CORE_PERSONAS[7]  # eval-mr-tan-wc: empty trace, no preferences at all
    template = QUERY_TEMPLATES[0]
    case = run_case("core", persona, template)
    candidate = CATALOGUE_BY_ID["tai-chi-1"]
    assert _reason_grounded(ReasonBasis.PREFERENCE, candidate, case, False) is False


def test_reasons_grounded_history_basis() -> None:
    persona = CORE_PERSONAS[0]  # eval-mdm-tan: went+enjoyed gardening-1
    template = QUERY_TEMPLATES[0]
    case = run_case("core", persona, template)
    candidate = CATALOGUE_BY_ID["gardening-1"]
    assert _reason_grounded(ReasonBasis.HISTORY, candidate, case, False) is True
    other = CATALOGUE_BY_ID["aqua-1"]
    assert _reason_grounded(ReasonBasis.HISTORY, other, case, False) is False


def test_reasons_grounded_context_basis_can_fail_and_does_for_an_uncovered_listing() -> None:
    """E6: the CONTEXT check used to be `case.template.rain_forecast`, and every template sets that
    to True -- 433 core reason lines counted as grounded without anyone asking whether the listing
    was under cover. The line claims "a better fit with rain around today", so all three of its
    premises are checked now, and the metric can fail.
    """
    template = next(t for t in QUERY_TEMPLATES if t.name == "unconstrained")
    case = run_case("core", CORE_PERSONAS[0], template)
    assert template.rain_forecast is True
    covered = CATALOGUE_BY_ID["aqua-1"]  # indoor
    uncovered = CATALOGUE_BY_ID["tai-chi-1"]  # outdoor
    assert _reason_grounded(ReasonBasis.CONTEXT, covered, case, False) is True
    assert _reason_grounded(ReasonBasis.CONTEXT, uncovered, case, False) is False

    # ...and an explicit environment ask means the rain nudge never applied, so a CONTEXT line on
    # that case would not be grounded either, whatever the forecast says.
    explicit = run_case(
        "core",
        CORE_PERSONAS[0],
        next(t for t in QUERY_TEMPLATES if t.name == "tuesday_morning_indoors_gentle"),
    )
    assert _reason_grounded(ReasonBasis.CONTEXT, covered, explicit, False) is False


def test_reasons_grounded_variety_basis_reads_the_flag_passed_in() -> None:
    persona = CORE_PERSONAS[0]
    template = QUERY_TEMPLATES[0]
    case = run_case("core", persona, template)
    candidate = CATALOGUE_BY_ID["tai-chi-1"]
    assert _reason_grounded(ReasonBasis.VARIETY, candidate, case, True) is True
    assert _reason_grounded(ReasonBasis.VARIETY, candidate, case, False) is False


def test_reasons_grounded_catalogue_basis_is_filler_not_scored() -> None:
    persona = CORE_PERSONAS[0]
    template = QUERY_TEMPLATES[0]
    case = run_case("core", persona, template)
    candidate = CATALOGUE_BY_ID["tai-chi-1"]
    assert _reason_grounded(ReasonBasis.CATALOGUE, candidate, case, False) is None


def test_reasons_grounded_rate_is_high_on_the_real_run(result: RankingEvaluationResult) -> None:
    """Production `reasons_for`/`score_candidate` already only emit a positive reason when a
    field backs it; this benchmark's independent verifier should agree on (almost) every case.

    This is only worth pinning because the verifier can now fail: see
    `test_reasons_grounded_context_basis_can_fail_and_does_for_an_uncovered_listing`. The
    PREFERENCE basis remains the weak one -- it asks whether ANY learned dimension applies to the
    listing, not whether the dimension the line cites does -- and is documented as such rather
    than counted as a stronger check than it is.
    """
    assert result.core.reasons_grounded.rate is not None
    assert result.core.reasons_grounded.rate > 0.9
    assert result.holdout.reasons_grounded.rate > 0.9


# --- CLI: --check exits 3 on drift -------------------------------------------------------------


def test_check_exits_3_on_drift(tmp_path: Path, result: RankingEvaluationResult) -> None:
    from silverloop.evaluation.ranking.__main__ import main

    out_dir = tmp_path / "evaluation"
    write_artifacts(result, out_dir)
    assert check_artifacts(result, out_dir)

    (out_dir / "ranking-evaluation.json").write_text("{}", encoding="utf-8")
    exit_code = main(["--out", str(out_dir), "--check"])
    assert exit_code == 3


def test_check_passes_on_a_freshly_written_artifact(tmp_path: Path) -> None:
    from silverloop.evaluation.ranking.__main__ import main

    out_dir = tmp_path / "evaluation"
    exit_code = main(["--out", str(out_dir)])
    assert exit_code == 0
    exit_code = main(["--out", str(out_dir), "--check"])
    assert exit_code == 0


# --- Cross-checks against the committed artifact ----------------------------------------------


def test_committed_artifact_is_not_stale(result: RankingEvaluationResult) -> None:
    """The artifact this task is required to produce; regenerate with `pnpm evaluate` (or
    `pnpm evaluate:check` to see this exact failure) if it goes stale.
    """
    docs_dir = Path(__file__).parents[3] / "docs" / "evaluation"
    assert check_artifacts(result, docs_dir), (
        "docs/evaluation/ranking-evaluation.{json,md} are stale; run `pnpm evaluate`"
    )


# --- Grading sanity, independent of the full run -----------------------------------------------


def test_grade_candidate_hard_avoid_beats_taste() -> None:
    from silverloop.evaluation.ranking.labels import GRADE_HARD_AVOID_OR_COOLDOWN, grade_candidate

    persona = next(p for p in ALL_PERSONAS if p.hard_avoids)
    hard_dimension, hard_value = persona.hard_avoids[0]
    matching = next(
        candidate
        for candidate in CATALOGUE_BY_ID.values()
        if _matches(hard_dimension, hard_value, candidate)
    )
    grade = grade_candidate(persona, matching, None, FROZEN_TODAY)
    assert grade == GRADE_HARD_AVOID_OR_COOLDOWN


def _matches(dimension, value, candidate) -> bool:
    from silverloop.evaluation.ranking._dimensions import candidate_dimension_value

    return candidate_dimension_value(dimension, candidate) == value


# ── The evaluation-only helpers must not drift from the production ones they mirror ──────────


def test_evaluation_helpers_import_the_production_feature_extractor() -> None:
    """`_dimensions.py` and `_grounding.py` used to *re-implement* two private production helpers
    so the harness never touched the ranker's internals -- and paid for it with a hand-copied
    2000 m threshold and a hand-copied set of time buckets that could silently drift and regrade
    the whole dataset without a test saying so.

    They import the production helpers now. What is pinned here is that they still do: a harness
    that quietly grew its own copy again would pass every other test in this file.
    """
    from silverloop import activity_search, preferences
    from silverloop.evaluation.ranking import _dimensions, _grounding
    from silverloop.evaluation.ranking.dataset import CATALOGUE
    from silverloop.models import PreferenceDimension

    assert _dimensions.candidate_dimension_value is preferences._candidate_dimension_value
    assert _grounding.environment_compatibility is preferences.environment_compatibility
    assert _grounding._time_window_for_hour is activity_search._time_window_for_hour
    assert not hasattr(_dimensions, "FAR_DISTANCE_M")
    assert not hasattr(_grounding, "_ENVIRONMENT_COMPATIBLE")

    from silverloop.evaluation.ranking import runner

    # One definition of "the same programme": the harness reads `activity_search.series_key`
    # directly and must not grow its own copy again.
    assert not hasattr(runner, "_series_key")
    for candidate in CATALOGUE:
        for dimension in PreferenceDimension:
            assert _dimensions.candidate_dimension_value(
                dimension, candidate
            ) == preferences._candidate_dimension_value(dimension, candidate), (
                candidate.activity_id,
                dimension,
            )


# ── Metamorphic properties of the ranker ──────────────────────────────────────────────────────
#
# Not "is this order good?" -- a benchmark answers that, badly, on six templates that cannot see
# most of what changed. These are properties that must hold for *any* order, on the real
# catalogue, whatever the weights are: if a person says something was too tiring, nothing gentler
# may lose ground; if they confirm a like, nothing that matches it may lose ground. A ranker can
# score well on the benchmark and still break either, and both were breakable before the ordinal
# axes and the evidence split landed.


def _rank_ids(candidates, intent, preferences, *, today):  # noqa: ANN001 - test helper
    from silverloop.activity_search import rank_candidates

    return [
        item.candidate.activity_id
        for item in rank_candidates(list(candidates), intent, preferences, today=today)
    ]


def test_directional_consistency() -> None:
    """After "too tiring" at level L, no candidate *below* L may lose rank.

    The nominal reading could not keep this: a `too_tiring` on a moderate listing wrote
    `intensity=moderate, -0.333`, which said nothing whatever about light listings -- and a
    `too_tiring` on a listing with no intensity at all wrote a fabricated `moderate`, so the
    person's answer moved a belief about a level the listing never claimed.
    """
    from datetime import datetime

    from silverloop.evaluation.ranking.dataset import CATALOGUE, FROZEN_TODAY
    from silverloop.models import (
        ActivityIntensity,
        ActivityIntent,
        ActivityPreferences,
        DeclineReason,
    )
    from silverloop.preferences import apply_decline, intensity_index, resolve

    now = datetime(2026, 9, 1, 9, 0)
    moderate = next(c for c in CATALOGUE if c.intensity is ActivityIntensity.MODERATE)
    intent = ActivityIntent()
    before = _rank_ids(CATALOGUE, intent, ActivityPreferences(person_id="p1"), today=FROZEN_TODAY)

    dimensions = apply_decline([], DeclineReason.TOO_TIRING, moderate, now)
    after = _rank_ids(
        CATALOGUE,
        intent,
        ActivityPreferences(person_id="p1", dimensions=dimensions, resolved=resolve(dimensions)),
        today=FROZEN_TODAY,
    )

    pivot = intensity_index(moderate.intensity)
    assert pivot is not None
    gentler = [
        c.activity_id
        for c in CATALOGUE
        if (index := intensity_index(c.intensity)) is not None and index < pivot
    ]
    assert gentler, "the catalogue must carry something gentler for this to mean anything"
    for activity_id in gentler:
        assert after.index(activity_id) <= before.index(activity_id), activity_id


def test_preference_coverage_is_monotonic() -> None:
    """Adding a confirmed like never lowers a candidate that matches it.

    Summing *matched rows only* and dividing by their own weights broke this: a listing that
    matched one of three stated likes scored exactly what a listing matching all three scored, so
    adding a like could reshuffle the order underneath a candidate it agreed with.
    """
    from datetime import datetime

    from silverloop.evaluation.ranking.dataset import CATALOGUE, FROZEN_TODAY
    from silverloop.models import (
        ActivityIntent,
        ActivityPreferences,
        DimensionPreference,
        PreferenceDimension,
    )
    from silverloop.ontology import ActivityType
    from silverloop.preferences import resolve

    intent = ActivityIntent()
    base = ActivityPreferences(person_id="p1")
    before = _rank_ids(CATALOGUE, intent, base, today=FROZEN_TODAY)

    for activity_type in sorted({c.activity_type for c in CATALOGUE if c.activity_type}):
        like = DimensionPreference(
            dimension=PreferenceDimension.ACTIVITY_TYPE,
            value=activity_type.value,
            strength=1.0,
            source="senior_statement",
            confirmed=True,
            observations=1,
            updated_at=datetime(2026, 9, 1, 9, 0),
        )
        after = _rank_ids(
            CATALOGUE,
            intent,
            ActivityPreferences(person_id="p1", dimensions=[like], resolved=resolve([like])),
            today=FROZEN_TODAY,
        )
        matching = [c.activity_id for c in CATALOGUE if c.activity_type is activity_type]
        for activity_id in matching:
            assert after.index(activity_id) <= before.index(activity_id), (
                activity_type,
                activity_id,
            )
    assert ActivityType.WALKING in {c.activity_type for c in CATALOGUE}


# --- The ranker's engagement input is production's; the grader's is frozen (D19) -------------


def _production_engagement(
    persona: PersonaBrief, *, limit: int | None = None
) -> dict[str, ActivityEngagement]:
    """The rows production would have recorded for this trace, counted by production."""
    from silverloop.activity_search import count_engagement, engagement_by_series, series_keys_for
    from silverloop.evaluation.ranking.dataset import (
        CATALOGUE,
        DeclineEvent,
        EnjoymentEvent,
        InterestEvent,
    )
    from silverloop.evaluation.ranking.traces import trace_prefix

    offers: list[tuple[str, str, date]] = []
    follow_through: list[tuple[str, str]] = []
    verdicts: list[tuple[str, str]] = []
    for event in trace_prefix(persona, limit):
        if isinstance(event, InterestEvent):
            offers.append((event.activity_id, "interested", event.day))
        elif isinstance(event, DeclineEvent):
            offers.append((event.activity_id, "not_for_me", event.day))
        elif isinstance(event, EnjoymentEvent):
            follow_through.append((event.activity_id, "went"))
            verdicts.append((event.activity_id, event.enjoyment.value))
    counted = count_engagement(offers, follow_through, verdicts)
    return engagement_by_series(
        counted.counts, counted.last_declined, counted.answered, series_keys_for(CATALOGUE)
    )


def test_build_engagement_is_the_production_pipeline_on_every_persona() -> None:
    """D19. The benchmark's ranker input used to be a private per-session count with no programme
    roll-up, so it scored a ranker that production never runs. It is now exactly
    `count_engagement` + `engagement_by_series` over the frozen catalogue, for the whole trace
    and for every prefix the learning-curve arms rebuild."""
    from silverloop.evaluation.ranking.traces import build_engagement

    for persona in ALL_PERSONAS:
        assert build_engagement(persona) == _production_engagement(persona), persona.person_id
        for limit in (0, *ablations.TRACE_PREFIX_LENGTHS):
            assert build_engagement(persona, limit=limit) == _production_engagement(
                persona, limit=limit
            ), (persona.person_id, limit)


def test_a_decline_reaches_every_session_of_the_programme_for_the_ranker() -> None:
    """The observable consequence: a "not for me" on one session holds back its sibling sessions
    in what the ranker sees, exactly as it does in the product."""
    from datetime import timedelta

    from silverloop.activity_search import DECLINE_COOLDOWN_DAYS, series_key
    from silverloop.evaluation.ranking.dataset import CATALOGUE, DeclineEvent
    from silverloop.evaluation.ranking.traces import build_engagement

    checked = 0
    for persona in ALL_PERSONAS:
        engagement = build_engagement(persona)
        for event in persona.trace:
            if not isinstance(event, DeclineEvent):
                continue
            declined = CATALOGUE_BY_ID[event.activity_id]
            siblings = [
                c
                for c in CATALOGUE
                if series_key(c) == series_key(declined) and c.activity_id != event.activity_id
            ]
            for sibling in siblings:
                seen = engagement[sibling.activity_id]
                assert seen.not_for_me >= 1
                assert seen.own is not None and seen.own.not_for_me == 0
                if FROZEN_TODAY - event.day < timedelta(days=DECLINE_COOLDOWN_DAYS):
                    assert seen.last_not_for_me is not None
                checked += 1
    assert checked > 0


def _inside_cooldown(engagement: ActivityEngagement | None) -> bool:
    from datetime import timedelta

    from silverloop.activity_search import DECLINE_COOLDOWN_DAYS

    return (
        engagement is not None
        and engagement.last_not_for_me is not None
        and FROZEN_TODAY - engagement.last_not_for_me < timedelta(days=DECLINE_COOLDOWN_DAYS)
    )


def test_grades_are_read_from_the_frozen_label_engagement_never_the_ranker_input() -> None:
    """D19's other half. The relevance grades are hand-authored ground truth: moving the ranker's
    input onto production's counting must not move a single grade. Every case grades from
    `label_engagement`, and the one place the two inputs disagree -- a sibling session of a
    declined programme, held back for the ranker and not graded as inside a cooldown -- is
    counted here rather than hidden."""
    from silverloop.evaluation.ranking.dataset import CATALOGUE
    from silverloop.evaluation.ranking.labels import grade_candidate
    from silverloop.evaluation.ranking.traces import build_engagement, label_engagement

    for split, personas in (("core", CORE_PERSONAS), ("holdout", HOLDOUT_PERSONAS)):
        for persona in personas:
            frozen = label_engagement(persona)
            for template in QUERY_TEMPLATES:
                case = run_case(split, persona, template)
                assert case.grades == {
                    candidate.activity_id: grade_candidate(
                        persona, candidate, frozen.get(candidate.activity_id), FROZEN_TODAY
                    )
                    for candidate in case.kept
                }
                assert case.engagement == build_engagement(persona)

    disagreements = []
    for persona in ALL_PERSONAS:
        ranker, grader = build_engagement(persona), label_engagement(persona)
        for candidate in CATALOGUE:
            seen = ranker.get(candidate.activity_id)
            if _inside_cooldown(seen) != _inside_cooldown(grader.get(candidate.activity_id)):
                disagreements.append((persona.person_id, candidate.activity_id, seen))
    assert disagreements, "the sibling roll-up should be visible somewhere in the dataset"
    for _, _, seen in disagreements:
        # Held back for the ranker only because a *sibling* session was declined.
        assert _inside_cooldown(seen)
        assert seen is not None and seen.own is not None and seen.own.not_for_me == 0


# --- Factor arms re-sort on production's own key (X1) ----------------------------------------


def test_a_factor_arm_that_zeroes_nothing_reproduces_production_exactly() -> None:
    """X1. `zero_factor` used to re-sort on a private key: the tier rebuilt from the `intent`
    factor's value, and no matched-axes, start-time or id tie-break. So an arm whose factor
    contributed nothing at all still reordered ties -- a "delta" that was the key, not the
    factor. On production's `sort_key_for` a no-op zeroing is exactly `full`."""
    from silverloop.activity_search import rank_candidates_with_breakdown
    from silverloop.evaluation.ranking.traces import build_engagement, build_preferences

    exercised = 0
    for persona in ALL_PERSONAS:
        preferences, engagement = build_preferences(persona), build_engagement(persona)
        for template in QUERY_TEMPLATES:
            intent = template.build_intent(persona)
            case = run_case("holdout" if persona in HOLDOUT_PERSONAS else "core", persona, template)
            pre = rank_candidates_with_breakdown(
                case.kept,
                intent,
                preferences,
                rain_forecast=template.rain_forecast,
                engagement=engagement,
                today=FROZEN_TODAY,
                diversity=False,
            )
            full = [item.ranked.candidate.activity_id for item in case.arms[ablations.ARM_FULL]]
            for name in ablations.FACTOR_NAMES:
                if any(
                    factor.contribution != 0
                    for item in pre
                    for factor in item.breakdown.factors
                    if factor.name == name
                ):
                    continue
                exercised += 1
                arm = [
                    item.ranked.candidate.activity_id
                    for item in case.arms[ablations.factor_arm(name)]
                ]
                assert arm == full, (persona.person_id, template.name, name)
    assert exercised > 0


def test_zero_factor_breaks_ties_like_production_soonest_session_first() -> None:
    """Sessions of one programme that tie on everything the old key read (tier, total, distance,
    title): production puts the sooner one first, whatever order they arrive in, and so does the
    re-sort. The old key kept whatever order they arrived in."""
    from silverloop.activity_search import RankedScore, rank_candidates_with_breakdown, series_key
    from silverloop.evaluation.ranking.dataset import CATALOGUE
    from silverloop.models import ActivityPreferences

    exercised = 0
    by_series: dict[str, list[ActivityCandidate]] = {}
    for candidate in CATALOGUE:
        if candidate.start_at is not None:
            by_series.setdefault(series_key(candidate), []).append(candidate)
    for sessions in (group for group in by_series.values() if len(group) >= 2):
        ranked = rank_candidates_with_breakdown(
            sessions,
            ActivityIntent(),
            ActivityPreferences(person_id="p"),
            rain_forecast=False,
            engagement={},
            today=FROZEN_TODAY,
            diversity=False,
        )
        latest_first = [
            RankedScore(ranked=item.ranked, breakdown=item.breakdown)
            for item in sorted(
                ranked,
                key=lambda item: item.ranked.candidate.start_at or FROZEN_TODAY,
                reverse=True,
            )
        ]
        for name in ablations.FACTOR_NAMES:
            groups: dict[tuple[float, float, int, int | None, str], list[RankedScore]] = {}
            for item in ablations.zero_factor(latest_first, name):
                tie = (
                    item.breakdown.tier,
                    item.breakdown.total,
                    item.breakdown.matched_axes,
                    item.ranked.candidate.distance_m,
                    item.ranked.candidate.title,
                )
                groups.setdefault(tie, []).append(item)
            for tied in groups.values():
                if len(tied) < 2:
                    continue
                exercised += 1
                starts = [item.ranked.candidate.start_at for item in tied]
                assert starts == sorted(starts), (name, tied[0].ranked.candidate.title)
    assert exercised > 0
