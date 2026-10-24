"""The traced ranking path (`activity_search.rank_with_trace`) and the pure extractions behind it.

These tests pin each recorded stage -- the sort key, the per-axis and per-belief detail, the
series dedupe and the variety swap -- to what the ranker did, and the traced path's final order to
the wrappers built from the same pieces. Pure, like `test_activity_search.py`: no database, no
network.

They do NOT prove the refactor preserved behaviour: `rank_with_trace` and
`rank_candidates_with_breakdown` now share their pieces, so comparing them is partly
self-referential. Preservation is proven against the pre-refactor code by
`test_search_ranking_golden.py` (captured before the refactor).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from silverloop.activity_rerank import merge_planner_order
from silverloop.activity_search import (
    ActivityEngagement,
    _dedupe_series,
    _diversify,
    count_engagement,
    eligible_reasons,
    engagement_by_series,
    filter_candidates,
    postprocess,
    rank_candidates_with_breakdown,
    rank_with_trace,
    score_and_sort,
    score_and_sort_detailed,
    series_key,
    series_keys_for,
    sort_key_for,
)
from silverloop.agent.planner import ActivityPlanRun
from silverloop.fixtures import synthetic_activity_candidates
from silverloop.intent import parse_intent
from silverloop.local_time import at_local
from silverloop.models import (
    ActivityAvailability,
    ActivityCandidate,
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    ActivityLocation,
    ActivityPreferences,
    ActivitySource,
    DeclineReason,
    DimensionPreference,
    IndoorOutdoor,
    IntegrationStatus,
    PreferenceDimension,
    ReasonBasis,
    SocialPreference,
    TimeWindow,
)
from silverloop.ontology import ActivityType
from silverloop.preferences import (
    Tri,
    apply_decline,
    preference_utility,
    preference_utility_detail,
    resolve,
)

TODAY = date(2026, 9, 10)
NOW = datetime(2026, 9, 10, 8, 0)
_MORNING = at_local(TODAY, 9, 0)


def candidate(
    activity_id: str,
    *,
    title: str | None = None,
    provider: str = "Fixture AAC",
    start_at: datetime | None = _MORNING,
    indoor_outdoor: IndoorOutdoor = IndoorOutdoor.INDOOR,
    intensity: ActivityIntensity | None = ActivityIntensity.LIGHT,
    distance_m: int | None = 500,
    category: str | None = "Group class",
    social_shape: SocialPreference | None = None,
    activity_type: ActivityType | None = None,
    language_tags: list[str] | None = None,
) -> ActivityCandidate:
    return ActivityCandidate(
        activity_id=activity_id,
        source=ActivitySource.AAC_FIXTURE,
        integration_status=IntegrationStatus.FIXTURE,
        title=title or f"Listing {activity_id}",
        provider=provider,
        start_at=start_at,
        location=ActivityLocation(name="Community Club"),
        category=category,
        activity_type=activity_type,
        indoor_outdoor=indoor_outdoor,
        intensity=intensity,
        social_shape=social_shape,
        language_tags=language_tags or [],
        availability=ActivityAvailability.AVAILABLE,
        retrieved_at=datetime(2026, 9, 9, 0, 0),
        distance_m=distance_m,
    )


def _ids(entries) -> list[str]:  # noqa: ANN001 - RankedScore list
    return [entry.ranked.candidate.activity_id for entry in entries]


_REQUESTS = (
    "",
    "something near me",
    "something with other people in the morning",
    "indoor light exercise",
    "no walking, my knee",
    "within 800 m",
    "something outdoors this afternoon",
)


def _fixture_world() -> tuple[list[ActivityCandidate], ActivityPreferences, dict]:
    catalogue = synthetic_activity_candidates(TODAY)
    walk = next(item for item in catalogue if item.activity_type is ActivityType.WALKING)
    rows = apply_decline([], DeclineReason.TOO_FAR, walk, NOW, origin_id="o1")
    rows.append(
        DimensionPreference(
            dimension=PreferenceDimension.SOCIAL,
            value="social",
            strength=1.0,
            source="senior_statement",
            confirmed=True,
            observations=1,
            updated_at=NOW,
            positive_evidence=1.0,
        )
    )
    preferences = ActivityPreferences(person_id="p", dimensions=rows, resolved=resolve(rows, TODAY))
    engagement = {
        catalogue[0].activity_id: ActivityEngagement(
            interested=1, not_for_me=1, last_not_for_me=TODAY - timedelta(days=2)
        ),
        catalogue[3].activity_id: ActivityEngagement(went=1, enjoyed=1),
    }
    return catalogue, preferences, engagement


# ── The traced path is the untraced path ──────────────────────────────────────────────────────


@pytest.mark.parametrize("rain", [False, True])
@pytest.mark.parametrize("text", _REQUESTS)
def test_rank_with_trace_final_is_filter_then_rank_candidates_with_breakdown(
    text: str, rain: bool
) -> None:
    """Consistency of the traced path with its wrappers -- not, on its own, a preservation proof
    (see the module docstring)."""
    catalogue, preferences, engagement = _fixture_world()
    intent = parse_intent(text, today=TODAY) if text else ActivityIntent()
    execution = rank_with_trace(
        catalogue,
        intent,
        preferences,
        rain_forecast=rain,
        engagement=engagement,
        today=TODAY,
    )
    kept, removed = filter_candidates(catalogue, intent, today=TODAY)
    expected = rank_candidates_with_breakdown(
        kept, intent, preferences, rain_forecast=rain, engagement=engagement, today=TODAY
    )
    assert execution.final == expected
    assert execution.kept == kept and execution.removed == removed
    # Every stage snapshot is a permutation of what the filter kept.
    for order in (execution.order_after_sort, execution.order_after_dedupe):
        assert sorted(order) == sorted(item.activity_id for item in kept)


def test_rank_candidates_with_breakdown_never_filters_and_accepts_no_today() -> None:
    full = candidate("full", distance_m=400).model_copy(
        update={"availability": ActivityAvailability.FULL}
    )
    others = [candidate(f"c{n}", distance_m=500 + n) for n in range(3)]
    ranked = rank_candidates_with_breakdown(
        [full, *others], ActivityIntent(), ActivityPreferences(person_id="p")
    )
    assert "full" in _ids(ranked)
    assert ranked == postprocess(
        score_and_sort([full, *others], ActivityIntent(), ActivityPreferences(person_id="p"))
    )


def test_the_recorded_sort_key_is_the_order_the_sort_produced() -> None:
    catalogue, preferences, engagement = _fixture_world()
    intent = parse_intent("something near me", today=TODAY)
    kept, _ = filter_candidates(catalogue, intent, today=TODAY)
    scored = score_and_sort_detailed(
        kept, intent, preferences, engagement=engagement, today=TODAY, rain_forecast=True
    )
    keys = [item.sort_key.ordering() for item in scored]
    assert keys == sorted(keys)
    for position, item in enumerate(scored, start=1):
        factors = {factor.name: factor.value for factor in item.detail.breakdown.factors}
        assert item.entry.ranked.rank == position
        assert item.sort_key.tier == round(factors["intent"] + factors["repetition"], 3)
        assert item.sort_key.total == item.detail.breakdown.total
        assert item.sort_key.matched_axes == item.detail.breakdown.matched_axes
        assert item.sort_key.distance_m == item.entry.ranked.candidate.distance_m
        contributions = [factor.contribution for factor in item.detail.breakdown.factors]
        assert round(sum(contributions), 3) == item.detail.breakdown.total


# ── Per-axis and per-belief detail ────────────────────────────────────────────────────────────


def test_unknown_listing_metadata_stays_unknown_in_the_request_axes() -> None:
    unlabelled = candidate(
        "blank",
        start_at=None,
        intensity=None,
        social_shape=None,
        indoor_outdoor=IndoorOutdoor.UNKNOWN,
        activity_type=None,
        language_tags=[],
        distance_m=None,
    )
    intent = ActivityIntent(
        time_window=TimeWindow.MORNING,
        social_preference=SocialPreference.SOCIAL,
        intensity=ActivityIntensity.LIGHT,
        language="Tamil",
        activity_types=[ActivityType.TAI_CHI],
        max_distance_m=900,
    )
    kept, removed = filter_candidates([unlabelled], intent, today=TODAY)
    assert kept == [unlabelled] and removed == []
    detail = score_and_sort_detailed(kept, intent, ActivityPreferences(person_id="p"))[0].detail
    outcomes = {axis.axis: axis.outcome for axis in detail.request_axes}
    assert outcomes == {
        "distance": Tri.UNKNOWN,
        "time_window": Tri.UNKNOWN,
        "social": Tri.UNKNOWN,
        "environment": None,
        "intensity": Tri.UNKNOWN,
        "language": Tri.UNKNOWN,
        "activity_type": Tri.UNKNOWN,
    }
    assert detail.request_judged == 0 and detail.request_constrained == 6


def test_per_belief_detail_is_the_same_walk_as_preference_utility() -> None:
    listing = candidate(
        "x",
        social_shape=SocialPreference.SOCIAL,
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        activity_type=ActivityType.WALKING,
    )
    rows = [
        DimensionPreference(
            dimension=PreferenceDimension.SOCIAL,
            value="social",
            strength=1.0,
            source="senior_statement",
            observations=1,
            updated_at=NOW,
            positive_evidence=1.0,
        ),
        DimensionPreference(
            dimension=PreferenceDimension.ENVIRONMENT,
            value="indoor",
            strength=-1.0,
            source="senior_statement",
            observations=1,
            updated_at=NOW,
            negative_evidence=1.0,
        ),
        DimensionPreference(
            dimension=PreferenceDimension.TIMING,
            value="evening",
            strength=1.0,
            source="senior_statement",
            observations=1,
            updated_at=NOW,
            positive_evidence=1.0,
        ),
    ]
    resolved = resolve(rows, TODAY)
    detail = preference_utility_detail(listing, resolved)
    assert (detail.utility, detail.coverage, detail.matched) == preference_utility(
        listing, resolved
    )
    by_dimension = {belief.preference.dimension: belief for belief in detail.beliefs}
    assert by_dimension[PreferenceDimension.SOCIAL].outcome is Tri.MATCH
    # An avoid of indoor, on an outdoor listing: a mismatch that contributes positively.
    assert by_dimension[PreferenceDimension.ENVIRONMENT].outcome is Tri.MISMATCH
    assert by_dimension[PreferenceDimension.ENVIRONMENT].contribution > 0
    assert by_dimension[PreferenceDimension.TIMING].outcome is Tri.MISMATCH
    assert round(sum(belief.contribution for belief in detail.beliefs), 3) == detail.utility


# ── Post-processing records ───────────────────────────────────────────────────────────────────


def test_series_dedupe_records_each_deferral_and_its_series_holder() -> None:
    sessions = [
        candidate(
            f"yoga-{n}", title="Chair Yoga", start_at=at_local(TODAY + timedelta(days=n), 9, 0)
        )
        for n in range(3)
    ]
    walk = candidate("walk", title="Park Walk", category="Walking", distance_m=600)
    craft = candidate("craft", title="Craft Corner", category="Crafts", distance_m=700)
    execution = rank_with_trace(
        [*sessions, walk, craft], ActivityIntent(), ActivityPreferences(person_id="p"), today=TODAY
    )
    assert execution.order_after_sort == ["yoga-0", "yoga-1", "yoga-2", "walk", "craft"]
    assert execution.order_after_dedupe == ["yoga-0", "walk", "craft", "yoga-1", "yoga-2"]
    record = execution.dedupe
    assert record.ran and record.changed and record.refilled == ()
    assert [
        (d.activity_id, d.series_holder_id, d.from_position, d.to_position) for d in record.deferred
    ] == [
        ("yoga-1", "yoga-0", 2, 4),
        ("yoga-2", "yoga-0", 3, 5),
    ]
    flagged = [
        entry.ranked.candidate.activity_id
        for entry in execution.final
        if entry.breakdown.series_deferred
    ]
    assert flagged == [d.activity_id for d in record.deferred]
    assert _ids(_dedupe_series([item.entry for item in execution.scored])) == (
        execution.order_after_dedupe
    )


def test_a_refilled_session_is_not_recorded_as_deferred() -> None:
    sessions = [
        candidate(
            f"yoga-{n}", title="Chair Yoga", start_at=at_local(TODAY + timedelta(days=n), 9, 0)
        )
        for n in range(3)
    ]
    walk = candidate("walk", title="Park Walk", category="Walking", distance_m=600)
    execution = rank_with_trace(
        [*sessions, walk], ActivityIntent(), ActivityPreferences(person_id="p"), today=TODAY
    )
    assert execution.dedupe.refilled == ("yoga-1",)
    assert [d.activity_id for d in execution.dedupe.deferred] == ["yoga-2"]
    assert execution.order_after_dedupe[:3] == ["yoga-0", "walk", "yoga-1"]


def test_the_variety_swap_is_recorded_with_margin_tier_and_reasons() -> None:
    same = [
        candidate("a", distance_m=500, category="Group class"),
        candidate("b", distance_m=600, category="Group class"),
        candidate("c", distance_m=700, category="Group class"),
    ]
    different = candidate("d", distance_m=800, category="Social group")
    execution = rank_with_trace(
        [*same, different], ActivityIntent(), ActivityPreferences(person_id="p"), today=TODAY
    )
    assert execution.order_after_dedupe == ["a", "b", "c", "d"]
    assert execution.order_after_variety == ["a", "b", "d", "c"]
    record = execution.variety
    assert record.status == "swapped" and record.shared_kind == "format:Group class"
    swap = record.swap
    assert swap is not None
    assert (swap.promoted_id, swap.displaced_id, swap.from_position, swap.to_position) == (
        "d",
        "c",
        4,
        3,
    )
    assert swap.promoted_kind == "format:Social group"
    assert swap.margin == round(swap.third_total - swap.promoted_total, 3)
    assert swap.margin <= 0.5
    assert any(reason.basis is ReasonBasis.VARIETY for reason in swap.reasons_after)
    # A catalogue filler is never composed beside a real reason, the variety note included: the
    # promoted card drops its filler -- it is not eligible, so it is not a line behind the card
    # either -- and nothing eligible was left off.
    assert [reason.basis for reason in swap.reasons_after] == [ReasonBasis.VARIETY]
    assert swap.more_reasons_after == ()
    promoted = next(e for e in execution.final if e.ranked.candidate.activity_id == "d")
    assert promoted.breakdown.reasons_suppressed == 0
    assert promoted.ranked.more_reasons == []
    assert _diversify(_dedupe_series([item.entry for item in execution.scored])) == execution.final


def test_a_variety_rebuild_moves_the_line_it_pushes_off_the_face_into_more_reasons() -> None:
    """D11: the promoted card is rebuilt from every eligible line it had plus VARIETY, so one line
    leaves the face -- into `more_reasons`, never nowhere -- and `reasons_suppressed` counts it."""
    request = ActivityIntent(
        time_window=TimeWindow.MORNING,
        social_preference=SocialPreference.SOCIAL,
        environment=ActivityEnvironment.INDOOR,
    )
    same = [
        candidate(
            key,
            distance_m=500 + n,
            category="Group class",
            social_shape=SocialPreference.SOCIAL,
            activity_type=ActivityType.TAI_CHI,
        )
        for n, key in enumerate(("a", "b", "c"))
    ]
    different = candidate(
        "d",
        distance_m=560,
        category="Group class",
        social_shape=SocialPreference.SOCIAL,
        activity_type=ActivityType.GAMES,
    )
    execution = rank_with_trace(
        [*same, different], request, ActivityPreferences(person_id="p"), today=TODAY
    )
    swap = execution.variety.swap
    assert swap is not None and swap.promoted_id == "d"
    assert len(swap.reasons_before) == 3
    promoted = next(entry for entry in execution.final if entry.ranked.candidate.activity_id == "d")
    assert any(reason.basis is ReasonBasis.VARIETY for reason in promoted.ranked.reasons)
    assert len(promoted.ranked.reasons) == 3
    scored = next(s for s in execution.scored if s.entry.ranked.candidate.activity_id == "d")
    # Before the swap the card already had lines behind its face; the rebuild keeps them there and
    # adds the one the VARIETY line displaced.
    assert list(swap.more_reasons_after) == promoted.ranked.more_reasons
    added = [r for r in promoted.ranked.more_reasons if r not in scored.entry.ranked.more_reasons]
    assert all(r in promoted.ranked.more_reasons for r in scored.entry.ranked.more_reasons)
    assert [r.basis for r in added] == [ReasonBasis.INTENT]
    assert promoted.breakdown.reasons_suppressed == len(promoted.ranked.more_reasons)
    contributions = {f.name: f.contribution for f in promoted.breakdown.factors}
    variety = next(r for r in swap.reasons_after if r.basis is ReasonBasis.VARIETY)
    eligible = eligible_reasons([*scored.detail.candidate_reasons, variety], contributions)
    shown = [*promoted.ranked.reasons, *promoted.ranked.more_reasons]
    assert sorted(shown, key=repr) == sorted(eligible, key=repr)
    # The face is exactly what composing over the old face alone would have given.
    from silverloop.activity_search import _compose_reasons

    face_only, _ = _compose_reasons([*swap.reasons_before, variety], contributions)
    assert face_only == promoted.ranked.reasons


def test_no_swap_statuses_are_recorded() -> None:
    mixed = [
        candidate("a", category="Group class"),
        candidate("b", category="Social group"),
        candidate("c", category="Group class"),
        candidate("d", category="Self-guided"),
    ]
    assert (
        rank_with_trace(
            mixed, ActivityIntent(), ActivityPreferences(person_id="p"), today=TODAY
        ).variety.status
        == "top_three_mixed"
    )
    few = mixed[:3]
    assert (
        rank_with_trace(
            few, ActivityIntent(), ActivityPreferences(person_id="p"), today=TODAY
        ).variety.status
        == "not_enough_candidates"
    )
    same = [candidate(key, distance_m=500, category="Group class") for key in ("a", "b", "c")]
    far = candidate("far", distance_m=4800, category="Social group")
    record = rank_with_trace(
        [*same, far], ActivityIntent(), ActivityPreferences(person_id="p"), today=TODAY
    ).variety
    assert record.status == "no_candidate_within_margin"
    assert [(item.activity_id, item.outcome) for item in record.considered] == [
        ("far", "outside_margin")
    ]


# ── Engagement counting and roll-up ───────────────────────────────────────────────────────────


def test_engagement_counting_dedupes_per_day_and_interested_ends_the_cooldown() -> None:
    day = date(2026, 9, 1)
    counted = count_engagement(
        offers=[
            ("m", "not_for_me", day),
            ("m", "not_for_me", day),
            ("m", "not_for_me", day + timedelta(days=1)),
            ("m", "interested", day + timedelta(days=2)),
            ("w", "not_for_me", day),
        ],
        follow_through=[("f", "went"), ("f", "did_not_go")],
        verdicts=[("f", "enjoyed"), ("f", "okay"), ("f", "not_for_me")],
    )
    assert counted.counts["m"] == {"not_for_me": 2, "interested": 1}
    assert "m" not in counted.last_declined and counted.last_declined["w"] == day
    assert counted.answered == {"m", "w"}
    assert counted.counts["f"] == {"went": 1, "did_not_go": 1, "enjoyed": 1, "not_enjoyed": 1}


def test_series_roll_up_hands_every_session_the_total_and_keeps_its_own_word() -> None:
    mon = candidate("chair-1", title="Chair Class")
    wed = candidate("chair-2", title="Chair Class")
    fri = candidate("chair-3", title="Chair Class")
    other = candidate("walk-1", title="Walk")
    day = date(2026, 9, 1)
    counted = count_engagement(
        offers=[("chair-1", "not_for_me", day), ("chair-3", "interested", day)],
        follow_through=[("chair-2", "went")],
        verdicts=[],
    )
    rolled = engagement_by_series(
        counted.counts,
        counted.last_declined,
        counted.answered,
        series_keys_for([mon, wed, fri, other]),
    )
    assert set(rolled) == {"chair-1", "chair-2", "chair-3"}
    for session in rolled.values():
        assert (session.not_for_me, session.interested, session.went) == (1, 1, 1)
    assert rolled["chair-1"].last_not_for_me == day
    assert rolled["chair-2"].last_not_for_me == day  # not answered itself: the series' decline
    assert rolled["chair-3"].last_not_for_me is None  # its own "interested" wins
    assert rolled["chair-2"].own is not None and rolled["chair-2"].own.went == 1
    assert engagement_by_series({}, {}, set(), series_keys_for([mon])) == {}


# ── Planner merge ─────────────────────────────────────────────────────────────────────────────


def _plan_run(order: list[str], mode: str = "agent") -> ActivityPlanRun:
    return ActivityPlanRun(
        evidence_id="agent-test",
        agent_version="v",
        mode=mode,  # type: ignore[arg-type]
        started_at=NOW,
        max_iterations=4,
        selected_order=order,
    )


def test_merge_records_narrowed_options_and_keeps_the_unseen_tail() -> None:
    catalogue = [candidate(f"k{n:02d}", distance_m=100 + n) for n in range(12)]
    ranked = [
        entry.ranked
        for entry in rank_candidates_with_breakdown(
            catalogue, ActivityIntent(), ActivityPreferences(person_id="p")
        )
    ]
    order = [item.candidate.activity_id for item in ranked]
    merged, narrowed = merge_planner_order(ranked, _plan_run([order[1], order[0], *order[2:9]]))
    assert [item.candidate.activity_id for item in merged] == [
        order[1],
        order[0],
        *order[2:9],
        *order[10:],
    ]
    assert [outcome.activity_id for outcome in narrowed] == [order[9]]
    # D3: only what the model was shown and kept is the agent's; the unseen tail is the ranker's.
    by_id = {item.candidate.activity_id: item.selected_by for item in merged}
    assert all(by_id[key] == "agent" for key in [order[1], order[0], *order[2:9]])
    assert all(by_id[key] == "ranker" for key in order[10:])
    fallback, _ = merge_planner_order(ranked, _plan_run(order[:10], mode="fallback_exhausted"))
    assert all(item.selected_by == "ranker" for item in fallback)
    unchanged, none = merge_planner_order(ranked, _plan_run([]))
    assert unchanged is ranked and none == []


# ── The integrity classifier, on constructed cases ────────────────────────────────────────────


def _stated(dimension: PreferenceDimension, value: str, strength: float) -> DimensionPreference:
    return DimensionPreference(
        dimension=dimension,
        value=value,
        strength=strength,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
        positive_evidence=1.0 if strength > 0 else 0.0,
        negative_evidence=0.0 if strength > 0 else 1.0,
    )


def _classified(
    catalogue: list[ActivityCandidate],
    intent: ActivityIntent,
    rows: list[DimensionPreference],
    *,
    engagement: dict[str, ActivityEngagement] | None = None,
    rain: bool = False,
    target: str,
):  # noqa: ANN202 - returns a CandidateIntegrity
    from silverloop.ranker_inspector import classify_integrity

    preferences = ActivityPreferences(person_id="p", dimensions=rows, resolved=resolve(rows, TODAY))
    execution = rank_with_trace(
        catalogue, intent, preferences, rain_forecast=rain, engagement=engagement, today=TODAY
    )
    scored = next(s for s in execution.scored if s.entry.ranked.candidate.activity_id == target)
    shown = next(e for e in execution.final if e.ranked.candidate.activity_id == target)
    return classify_integrity(scored, shown.ranked), scored, shown


def _by_factor(integrity) -> dict[str, tuple[str, str | None]]:  # noqa: ANN001
    return {f.factor: (f.classification, f.silent_reason) for f in integrity.findings}


def test_a_contradicted_avoid_is_silent_by_design() -> None:
    outdoor = candidate("out", indoor_outdoor=IndoorOutdoor.OUTDOOR)
    integrity, _, _ = _classified(
        [outdoor],
        ActivityIntent(),
        [_stated(PreferenceDimension.ENVIRONMENT, "indoor", -1.0)],
        target="out",
    )
    assert _by_factor(integrity)["preference"] == ("silent_by_design", "contradicted_avoid_belief")


def test_history_silenced_by_a_not_enjoyed_visit_is_silent_by_design() -> None:
    listing = candidate("x")
    integrity, _, shown = _classified(
        [listing],
        ActivityIntent(),
        [],
        engagement={"x": ActivityEngagement(interested=3, went=1, not_enjoyed=1)},
        target="x",
    )
    assert _by_factor(integrity)["engagement"] == (
        "silent_by_design",
        "history_silenced_not_enjoyed",
    )
    assert all(reason.basis is not ReasonBasis.HISTORY for reason in shown.ranked.reasons)


def test_an_unjudged_request_fit_earns_no_credit_so_nothing_is_owed() -> None:
    """D13: a listing that answers none of the request keeps the unjudged tier but earns no intent
    credit, so there is no positive intent factor for a card to explain."""
    blank = candidate("blank", social_shape=None)
    integrity, scored, _ = _classified(
        [blank], ActivityIntent(social_preference=SocialPreference.SOCIAL), [], target="blank"
    )
    assert "intent" not in _by_factor(integrity)
    assert "intent" not in integrity.positive_factors
    assert scored.detail.breakdown.tier == 1.0 and scored.sort_key.tier == 1.0


def test_a_line_the_card_had_no_room_for_is_shown_on_expand() -> None:
    listing = candidate(
        "x",
        social_shape=SocialPreference.SOCIAL,
        activity_type=ActivityType.GARDENING,
        indoor_outdoor=IndoorOutdoor.INDOOR,
    )
    integrity, scored, shown = _classified(
        [listing],
        ActivityIntent(social_preference=SocialPreference.SOCIAL),
        [_stated(PreferenceDimension.ACTIVITY_TYPE, "gardening", 1.0)],
        engagement={"x": ActivityEngagement(went=1, enjoyed=1)},
        rain=True,
        target="x",
    )
    factors = _by_factor(integrity)
    contributions = {f.name: f.contribution for f in shown.breakdown.factors}
    assert (contributions["intent"], contributions["preference"], contributions["context"]) == (
        7.0,
        2.0,
        1.5,
    )
    assert contributions["engagement"] == 1.125
    # Four positive bases, three slots: the smallest contributor's line moves behind the face and
    # is shown when the card is opened (D12).
    assert factors["engagement"] == ("on_expand", None)
    assert factors["intent"][0] == factors["preference"][0] == factors["context"][0] == "grounded"
    assert shown.breakdown.reasons_suppressed == 1
    assert [r.basis for r in shown.ranked.more_reasons] == [ReasonBasis.HISTORY]
    assert any(r.basis is ReasonBasis.HISTORY for r in scored.detail.candidate_reasons)
    assert [r.basis for r in shown.ranked.reasons] == [
        ReasonBasis.INTENT,
        ReasonBasis.CONTEXT,
        ReasonBasis.PREFERENCE,
    ]


def test_a_positive_factor_with_no_line_anywhere_is_unsupported() -> None:
    from dataclasses import replace

    from silverloop.ranker_inspector import classify_integrity

    listing = candidate("x", social_shape=SocialPreference.SOCIAL)
    _, scored, shown = _classified(
        [listing], ActivityIntent(social_preference=SocialPreference.SOCIAL), [], target="x"
    )
    stripped = replace(scored, detail=replace(scored.detail, candidate_reasons=[]))
    integrity = classify_integrity(
        stripped, shown.ranked.model_copy(update={"reasons": [], "more_reasons": []})
    )
    assert _by_factor(integrity)["intent"] == ("unsupported", None)


def test_a_line_that_existed_only_before_composition_is_not_an_explanation() -> None:
    """The classifier reads the card alone. A scoring-time line that reached neither the face nor
    `more_reasons` explains nothing to anyone, so the factor behind it is `unsupported`."""
    from silverloop.ranker_inspector import classify_integrity

    listing = candidate("x", social_shape=SocialPreference.SOCIAL)
    _, scored, shown = _classified(
        [listing], ActivityIntent(social_preference=SocialPreference.SOCIAL), [], target="x"
    )
    assert any(r.basis is ReasonBasis.INTENT for r in scored.detail.candidate_reasons)
    integrity = classify_integrity(
        scored, shown.ranked.model_copy(update={"reasons": [], "more_reasons": []})
    )
    assert _by_factor(integrity)["intent"] == ("unsupported", None)


def test_a_line_behind_the_face_without_a_positive_factor_is_reported() -> None:
    """The inverse check scans `more_reasons` as well as the face."""
    from silverloop.models import ActivityReason
    from silverloop.ranker_inspector import classify_integrity

    listing = candidate("x")
    integrity, scored, shown = _classified(
        [listing],
        ActivityIntent(),
        [],
        engagement={"x": ActivityEngagement(interested=1, not_for_me=2)},
        target="x",
    )
    assert integrity.reasons_without_positive_factor == []
    history = ActivityReason(text="You said you were interested.", basis=ReasonBasis.HISTORY)
    integrity = classify_integrity(
        scored, shown.ranked.model_copy(update={"more_reasons": [history]})
    )
    assert [(r.basis, r.factor) for r in integrity.reasons_without_positive_factor] == [
        (ReasonBasis.HISTORY, "engagement")
    ]


def test_no_history_line_is_shown_beside_net_negative_engagement() -> None:
    """D15: "You said you were interested in this before." is not a reason something suits someone
    when the same history scores against it."""
    listing = candidate("x")
    integrity, scored, shown = _classified(
        [listing],
        ActivityIntent(),
        [],
        engagement={"x": ActivityEngagement(interested=1, not_for_me=2)},
        target="x",
    )
    assert any(r.basis is ReasonBasis.HISTORY for r in scored.detail.candidate_reasons)
    assert {f.name: f.contribution for f in shown.breakdown.factors}["engagement"] < 0
    assert all(r.basis is not ReasonBasis.HISTORY for r in shown.ranked.reasons)
    # Nothing else grounds the card, so the catalogue filler stands in -- and nothing is counted.
    assert [r.basis for r in shown.ranked.reasons] == [ReasonBasis.CATALOGUE]
    # The filler says what the listing is and nothing it has not checked: no "near you".
    assert [r.text for r in shown.ranked.reasons] == ["Group class."]
    assert shown.breakdown.reasons_suppressed == 0
    assert integrity.reasons_without_positive_factor == []


# ── Named constants and the travel note ───────────────────────────────────────────────────────


def test_factor_descriptions_and_engagement_weights_are_the_rankers_own() -> None:
    from silverloop.activity_search import (
        ENGAGEMENT_WEIGHTS,
        RANKING_FACTOR_DESCRIPTIONS,
        RANKING_WEIGHTS,
        _engagement,
    )

    assert list(RANKING_FACTOR_DESCRIPTIONS) == list(RANKING_WEIGHTS)
    assert all(
        text.strip() and "probab" not in text for text in RANKING_FACTOR_DESCRIPTIONS.values()
    )
    assert list(ENGAGEMENT_WEIGHTS) == [
        "interested",
        "attended",
        "enjoyed",
        "durable_not_for_me",
        "not_enjoyed",
    ]
    engagement = ActivityEngagement(
        interested=1, went=2, enjoyed=1, not_enjoyed=1, not_for_me=2, last_not_for_me=TODAY
    )
    value, _ = _engagement(engagement, TODAY)
    expected = (0.25 * 1 + 0.35 * 1 + 0.4 * 1) - (0.5 * 1 + 0.5 * 1)
    assert value == round(max(-1.0, min(1.0, expected)), 3)


def _distance_line(pivot: float, direction: str) -> DimensionPreference:
    return DimensionPreference(
        dimension=PreferenceDimension.DISTANCE,
        value=direction,
        strength=1 / 3,
        source="decline_reason" if direction == "lower" else "inferred",
        observations=1,
        updated_at=NOW,
        positive_evidence=1.0,
        pivot=pivot,
        direction=direction,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("floor", [None, 300.0, 500.0, 900.0])
@pytest.mark.parametrize("ceiling", [None, 0.0, 400.0, 500.0, 700.0, 1200.0])
def test_the_tolerance_basis_names_the_line_that_set_the_tolerance(
    floor: float | None, ceiling: float | None
) -> None:
    from silverloop.preferences import (
        DEFAULT_TRAVEL_TOLERANCE_M,
        travel_tolerance_basis,
        travel_tolerance_m,
    )

    rows = [
        *([_distance_line(floor, "higher")] if floor is not None else []),
        *([_distance_line(ceiling, "lower")] if ceiling is not None else []),
    ]
    resolved = resolve(rows, TODAY)
    tolerance, basis = travel_tolerance_m(resolved), travel_tolerance_basis(resolved)
    if basis == "default":
        assert tolerance == DEFAULT_TRAVEL_TOLERANCE_M
        assert floor is None or floor < DEFAULT_TRAVEL_TOLERANCE_M
        assert ceiling is None or ceiling > DEFAULT_TRAVEL_TOLERANCE_M
    elif basis == "learned_ceiling":
        assert ceiling is not None and tolerance == max(1, int(ceiling))
    else:
        assert floor is not None and tolerance == int(floor)
        assert ceiling is None or ceiling > floor


@pytest.mark.parametrize("floor", [None, 300.0, 900.0, 2000.0])
@pytest.mark.parametrize("ceiling", [None, 400.0, 700.0, 1000.0, 1500.0])
@pytest.mark.parametrize("near", [False, True])
def test_a_stated_near_is_the_last_narrowing_step_and_its_basis_only_when_it_binds(
    floor: float | None, ceiling: float | None, near: bool
) -> None:
    from silverloop.preferences import (
        NEARBY_RADIUS_M,
        travel_tolerance_basis,
        travel_tolerance_m,
    )

    lines = [
        *([_distance_line(floor, "higher")] if floor is not None else []),
        *([_distance_line(ceiling, "lower")] if ceiling is not None else []),
    ]
    statement = DimensionPreference(
        dimension=PreferenceDimension.DISTANCE,
        value="near",
        strength=1.0,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
        positive_evidence=1.0,
    )
    without = resolve(lines, TODAY)
    resolved = resolve([*lines, statement] if near else lines, TODAY)
    tolerance, basis = travel_tolerance_m(resolved), travel_tolerance_basis(resolved)
    if not near:
        assert basis != "stated_near"
        return
    assert tolerance == min(travel_tolerance_m(without), NEARBY_RADIUS_M)
    if basis == "stated_near":
        assert tolerance == NEARBY_RADIUS_M <= travel_tolerance_m(without)
    else:
        assert basis == travel_tolerance_basis(without)
        assert tolerance == travel_tolerance_m(without) < NEARBY_RADIUS_M


def test_the_friction_note_names_a_stated_near() -> None:
    far = candidate("far", distance_m=1800)
    near = candidate("near", distance_m=900)
    rows = [
        _distance_line(2500.0, "higher"),
        DimensionPreference(
            dimension=PreferenceDimension.DISTANCE,
            value="near",
            strength=1.0,
            source="senior_statement",
            confirmed=True,
            observations=1,
            updated_at=NOW,
            positive_evidence=1.0,
        ),
    ]
    preferences = ActivityPreferences(person_id="p", dimensions=rows, resolved=resolve(rows, TODAY))
    ranked = rank_candidates_with_breakdown([far, near], ActivityIntent(), preferences)
    notes = {
        e.ranked.candidate.activity_id: {f.name: f for f in e.breakdown.factors}["friction"]
        for e in ranked
    }
    assert "past the 1 km a stated preference for somewhere near allows" in notes["far"].note
    assert "inside the 1 km a stated preference for somewhere near allows" in notes["near"].note
    assert {f.name: f for f in next(iter(ranked)).breakdown.factors}["friction"].value <= 0


def test_the_friction_note_names_the_default_when_nothing_learned_moved_it() -> None:
    far = candidate("far", distance_m=900)
    near = candidate("near", distance_m=300)
    plain = rank_candidates_with_breakdown(
        [far, near], ActivityIntent(), ActivityPreferences(person_id="p")
    )
    notes = {
        e.ranked.candidate.activity_id: {f.name: f for f in e.breakdown.factors}["friction"]
        for e in plain
    }
    assert "past the 500 m default comfortable distance" in notes["far"].note
    assert "that has suited you" not in notes["far"].note
    assert "within the 500 m default comfortable distance" in notes["near"].note

    rows = [_distance_line(400.0, "lower")]
    learned = rank_candidates_with_breakdown(
        [far],
        ActivityIntent(),
        ActivityPreferences(person_id="p", dimensions=rows, resolved=resolve(rows, TODAY)),
    )
    friction = {f.name: f for f in learned[0].breakdown.factors}["friction"]
    assert "past the 400 m line set by a learned \u201ctoo far\u201d" in friction.note
    assert "suited you" not in friction.note
    # A ceiling above the default binds nothing, so the note still names the default.
    rows = [_distance_line(700.0, "lower")]
    unbound = rank_candidates_with_breakdown(
        [far],
        ActivityIntent(),
        ActivityPreferences(person_id="p", dimensions=rows, resolved=resolve(rows, TODAY)),
    )
    assert (
        "default comfortable distance"
        in {f.name: f for f in unbound[0].breakdown.factors}["friction"].note
    )
    # The wording moved; the number did not.
    assert notes["far"].value == round(-(900 - 500) / 4500, 3)


# ── Where travel starts to cost, and why an outcome is unknown ────────────────────────────────


@pytest.mark.parametrize("tolerance", [1, 300, 500, 1000, 4200])
@pytest.mark.parametrize("asked", [None, -50, 0, 1, 299, 300, 800, 1000, 5000])
def test_travel_cost_start_is_where_travel_utility_starts_charging(
    tolerance: int, asked: int | None
) -> None:
    from silverloop.activity_search import travel_cost_start, travel_utility

    starts_m, asked_binds = travel_cost_start(tolerance, asked)
    assert asked_binds == (asked is not None and 0 < asked < tolerance)
    assert starts_m == (asked if asked_binds else tolerance)
    for distance in (0, starts_m - 1, starts_m, starts_m + 1, starts_m + 2250, starts_m + 9000):
        if distance < 0:
            continue
        value, note = travel_utility(distance, tolerance, asked_radius_m=asked)
        expected = (
            0.0 if distance <= starts_m else round(-min(1.0, (distance - starts_m) / 4500), 3)
        )
        assert value == expected
        assert ("you asked for" in note) == (asked_binds and distance > starts_m)


def test_travel_cost_start_for_names_what_set_the_start() -> None:
    from silverloop.activity_search import travel_cost_start_for

    empty = ActivityPreferences(person_id="p")
    near = ActivityIntent(max_distance_m=300, distance_is_explicit=False)
    explicit = ActivityIntent(max_distance_m=300, distance_is_explicit=True)
    assert (
        travel_cost_start_for(empty, ActivityIntent()).starts_m,
        travel_cost_start_for(empty, ActivityIntent()).basis,
    ) == (500, "default")
    phrase = travel_cost_start_for(empty, near)
    assert (phrase.starts_m, phrase.basis, phrase.asked_radius_m) == (300, "asked_radius", 300)
    number = travel_cost_start_for(empty, explicit)
    assert (number.starts_m, number.basis, number.asked_radius_m) == (500, "default", None)
    rows = [_distance_line(400.0, "lower")]
    ceiling = ActivityPreferences(person_id="p", dimensions=rows, resolved=resolve(rows, TODAY))
    wider = travel_cost_start_for(ceiling, ActivityIntent(max_distance_m=1000))
    assert (wider.starts_m, wider.basis, wider.asked_radius_m) == (400, "learned_ceiling", 1000)


def _like(dimension: PreferenceDimension, value: str) -> DimensionPreference:
    return _stated(dimension, value, 1.0)


@pytest.mark.parametrize(
    ("dimension", "value", "listing", "expected"),
    [
        (
            PreferenceDimension.ACTIVITY_TYPE,
            "walking",
            {"activity_type": ActivityType.WALKING},
            (Tri.MATCH, None),
        ),
        (
            PreferenceDimension.ACTIVITY_TYPE,
            "walking",
            {"activity_type": ActivityType.TAI_CHI},
            (Tri.UNKNOWN, "mismatch_not_counted"),
        ),
        (
            PreferenceDimension.ACTIVITY_TYPE,
            "walking",
            {"activity_type": ActivityType.OTHER},
            (Tri.UNKNOWN, "mismatch_not_counted"),
        ),
        (
            PreferenceDimension.ACTIVITY_TYPE,
            "walking",
            {"activity_type": None},
            (Tri.UNKNOWN, "listing_silent"),
        ),
        (
            PreferenceDimension.ENVIRONMENT,
            "indoor",
            {"indoor_outdoor": IndoorOutdoor.OUTDOOR},
            (Tri.MISMATCH, None),
        ),
        (
            PreferenceDimension.ENVIRONMENT,
            "indoor",
            {"indoor_outdoor": IndoorOutdoor.UNKNOWN},
            (Tri.UNKNOWN, "listing_silent"),
        ),
        (
            PreferenceDimension.SOCIAL,
            "social",
            {"social_shape": None},
            (Tri.UNKNOWN, "listing_silent"),
        ),
        (
            PreferenceDimension.SOCIAL,
            "social",
            {"social_shape": SocialPreference.SOLO},
            (Tri.MISMATCH, None),
        ),
        (
            PreferenceDimension.TIMING,
            "morning",
            {"start_at": None},
            (Tri.UNKNOWN, "listing_silent"),
        ),
    ],
)
def test_a_belief_outcome_says_why_it_is_unknown(
    dimension: PreferenceDimension, value: str, listing: dict, expected: tuple
) -> None:
    from silverloop.preferences import candidate_match_detail, candidate_matches

    belief = resolve([_like(dimension, value)], TODAY)[0]
    listing_candidate = candidate("x", **listing)
    assert candidate_match_detail(belief, listing_candidate) == expected
    assert candidate_matches(belief, listing_candidate) is expected[0]


def test_ordinal_intensity_unknown_is_the_listing_being_silent() -> None:
    from silverloop.preferences import candidate_match_detail

    rows = apply_decline(
        [],
        DeclineReason.TOO_TIRING,
        candidate("m", intensity=ActivityIntensity.MODERATE),
        NOW,
        origin_id="o",
    )
    belief = resolve(rows, TODAY)[0]
    assert candidate_match_detail(belief, candidate("x", intensity=None)) == (
        Tri.UNKNOWN,
        "listing_silent",
    )
    assert candidate_match_detail(belief, candidate("x", intensity=ActivityIntensity.LIGHT)) == (
        Tri.MATCH,
        None,
    )


def test_the_utility_walk_carries_the_unknown_reason_on_every_belief() -> None:
    catalogue, preferences, _ = _fixture_world()
    rows = [
        *preferences.dimensions,
        _like(PreferenceDimension.ACTIVITY_TYPE, "walking"),
        _like(PreferenceDimension.ENVIRONMENT, "indoor"),
    ]
    resolved = resolve(rows, TODAY)
    for listing in [*catalogue, candidate("other", activity_type=ActivityType.OTHER)]:
        for belief in preference_utility_detail(listing, resolved).beliefs:
            assert (belief.unknown_reason is None) == (belief.outcome is not Tri.UNKNOWN)


def test_request_axes_name_why_they_are_unknown() -> None:
    intent = ActivityIntent(
        time_window=TimeWindow.MORNING,
        activity_types=[ActivityType.TAI_CHI],
        language="Tamil",
    )
    preferences = ActivityPreferences(person_id="p")
    listings = [
        candidate("other", activity_type=ActivityType.OTHER, start_at=None),
        candidate("blank", activity_type=None),
        candidate("walk", activity_type=ActivityType.WALKING),
    ]
    scored = {
        item.entry.ranked.candidate.activity_id: {a.axis: a for a in item.detail.request_axes}
        for item in score_and_sort_detailed(listings, intent, preferences)
    }
    assert scored["other"]["activity_type"].unknown_reason == "mismatch_not_counted"
    assert scored["other"]["time_window"].unknown_reason == "listing_silent"
    assert scored["blank"]["activity_type"].unknown_reason == "listing_silent"
    assert scored["walk"]["activity_type"].outcome is Tri.MISMATCH
    for axes in scored.values():
        for axis in axes.values():
            assert (axis.unknown_reason is None) == (axis.outcome is not Tri.UNKNOWN)


@pytest.mark.parametrize(
    ("rows", "asked", "past", "within"),
    [
        ([], None, "past the 500 m default comfortable distance", "within the 500 m default"),
        (
            [("lower", 400.0)],
            None,
            "past the 400 m line set by a learned \u201ctoo far\u201d",
            "inside the 400 m line set by a learned",
        ),
        (
            [("higher", 900.0)],
            None,
            "past the 900 m that has suited you",
            "within your usual range",
        ),
        ([("higher", 4600.0)], 1000, "past the 1 km you asked for", "within your usual range"),
        ([("lower", 400.0)], 300, "past the 300 m you asked for", "within your usual range"),
    ],
)
def test_the_friction_note_names_the_basis_that_set_where_travel_costs(
    rows: list[tuple[str, float]], asked: int | None, past: str, within: str
) -> None:
    from silverloop.activity_search import travel_cost_start_for, travel_utility

    dimensions = [_distance_line(pivot, direction) for direction, pivot in rows]
    preferences = ActivityPreferences(
        person_id="p", dimensions=dimensions, resolved=resolve(dimensions, TODAY)
    )
    intent = ActivityIntent(max_distance_m=asked) if asked is not None else ActivityIntent()
    start = travel_cost_start_for(preferences, intent)
    far = candidate("far", distance_m=start.starts_m + 900)
    near = candidate("near", distance_m=max(0, start.starts_m - 100))
    ranked = rank_candidates_with_breakdown([far, near], intent, preferences)
    notes = {
        entry.ranked.candidate.activity_id: {f.name: f for f in entry.breakdown.factors}["friction"]
        for entry in ranked
    }
    assert past in notes["far"].note
    assert within in notes["near"].note
    # Only the wording depends on the basis: the value is the same with or without it.
    for key, listing in (("far", far), ("near", near)):
        assert (
            notes[key].value
            == travel_utility(
                listing.distance_m, start.tolerance_m, asked_radius_m=start.asked_radius_m
            )[0]
        )
    if start.basis == "learned_ceiling":
        assert "suited you" not in notes["far"].note


# ── D13 / D12 / D15 / D11 / D18 ───────────────────────────────────────────────────────────────


def _compose(lines: list[tuple[ReasonBasis, str]], contributions: dict[str, float]):  # noqa: ANN202
    from silverloop.activity_search import _compose_reasons
    from silverloop.models import ActivityReason

    return _compose_reasons(
        [ActivityReason(text=text, basis=basis) for basis, text in lines], contributions
    )


_ZERO = {"intent": 0.0, "preference": 0.0, "engagement": 0.0, "context": 0.0}


def test_composition_gives_each_positive_basis_a_line_largest_first() -> None:
    lines = [
        (ReasonBasis.INTENT, "i1"),
        (ReasonBasis.INTENT, "i2"),
        (ReasonBasis.INTENT, "i3"),
        (ReasonBasis.PREFERENCE, "p1"),
        (ReasonBasis.HISTORY, "h1"),
        (ReasonBasis.CONTEXT, "c1"),
    ]
    contributions = {**_ZERO, "intent": 7.0, "preference": 2.0, "engagement": 0.5, "context": 1.5}
    kept, more = _compose(lines, contributions)
    # Three slots, four positive bases: the smallest (history) moves behind the face, with the
    # intent lines there was no room for, in basis order.
    assert [r.text for r in kept] == ["i1", "c1", "p1"]
    assert [r.text for r in more] == ["i2", "i3", "h1"]

    # Fewer bases than slots: every basis gets a line, free slots go in basis order.
    kept, more = _compose(lines[:4], {**contributions, "context": 0.0, "engagement": 0.0})
    assert [r.text for r in kept] == ["i1", "i2", "p1"] and [r.text for r in more] == ["i3"]

    # A line whose factor did not contribute positively is neither shown nor behind the face.
    kept, more = _compose(lines, {**contributions, "engagement": -0.75, "context": 0.0})
    assert [r.text for r in kept] == ["i1", "i2", "p1"] and [r.text for r in more] == ["i3"]

    # Ties fall back to basis order; VARIETY always keeps its slot.
    tied = {**_ZERO, "preference": 1.5, "context": 1.5, "engagement": 1.5}
    kept, more = _compose(
        [
            (ReasonBasis.PREFERENCE, "p"),
            (ReasonBasis.CONTEXT, "c"),
            (ReasonBasis.HISTORY, "h"),
            (ReasonBasis.VARIETY, "v"),
        ],
        tied,
    )
    assert [r.text for r in kept] == ["h", "c", "v"] and [r.text for r in more] == ["p"]

    # A catalogue filler is never behind the face beside a real line.
    kept, more = _compose(
        [(ReasonBasis.INTENT, "i"), (ReasonBasis.CATALOGUE, "cat")], contributions
    )
    assert [r.text for r in kept] == ["i"] and more == []


def test_rebuilding_over_every_eligible_line_leaves_the_face_it_always_had() -> None:
    """The variety rebuild composes over face + `more_reasons` + VARIETY. Its face must be exactly
    what composing over the old face + VARIETY gave, so no visible line changes; the difference is
    only that nothing eligible disappears."""
    import itertools
    import random

    from silverloop.activity_search import _compose_reasons
    from silverloop.models import ActivityReason

    rng = random.Random(20260915)
    bases = [ReasonBasis.INTENT, ReasonBasis.HISTORY, ReasonBasis.CONTEXT, ReasonBasis.PREFERENCE]
    variety = ActivityReason(text="v", basis=ReasonBasis.VARIETY)
    for trial in range(3000):
        lines = [
            ActivityReason(text=f"{basis.value}{n}-{trial}", basis=basis)
            for basis in bases
            for n in range(rng.randint(0, 3))
        ]
        if rng.random() < 0.2:
            lines.append(ActivityReason(text="cat", basis=ReasonBasis.CATALOGUE))
        rng.shuffle(lines)
        contributions = {
            factor: rng.choice([-0.5, 0.0, 0.5, 1.0, 1.5, 2.0])
            for factor in ("intent", "preference", "engagement", "context")
        }
        face, more = _compose_reasons(lines, contributions)
        assert len(face) <= 3
        rebuilt_face, rebuilt_more = _compose_reasons([*face, *more, variety], contributions)
        old_face, _ = _compose_reasons([*face, variety], contributions)
        assert rebuilt_face == old_face
        assert len(rebuilt_face) <= 3
        everything = [*rebuilt_face, *rebuilt_more]
        assert len(everything) == len({id(r) for r in everything})
        assert all(
            any(r is line for line in everything)
            for r in itertools.chain(face, more, [variety])
            if r.basis is not ReasonBasis.CATALOGUE
        )


def test_an_unjudged_listing_keeps_its_tier_but_not_the_intent_credit() -> None:
    blank = candidate("blank", social_shape=None, category=None)
    fits = candidate("fits", social_shape=SocialPreference.SOCIAL, distance_m=3000)
    contradicts = candidate("contra", social_shape=SocialPreference.SOLO)
    request = ActivityIntent(social_preference=SocialPreference.EITHER)
    request = request.model_copy(update={"social_preference": SocialPreference.SOCIAL})
    ranked = rank_candidates_with_breakdown(
        [blank, fits, contradicts],
        request,
        ActivityPreferences(person_id="p"),
        engagement={"blank": ActivityEngagement(not_for_me=1, last_not_for_me=TODAY)},
        today=TODAY,
    )
    by_id = {e.ranked.candidate.activity_id: e.breakdown for e in ranked}
    blank_factors = {f.name: f for f in by_id["blank"].factors}
    assert blank_factors["intent"].contribution == 0.0
    assert by_id["blank"].tier == round(1.0 + blank_factors["repetition"].value, 3) == 0.0
    assert by_id["fits"].tier == 1.0
    assert sort_key_for(blank, by_id["blank"]).tier == by_id["blank"].tier


def test_equal_scoring_sessions_of_a_programme_rank_soonest_first() -> None:
    later = candidate(
        "s-a", title="Chair Class", start_at=at_local(TODAY + timedelta(days=4), 9, 0)
    )
    sooner = candidate(
        "s-b", title="Chair Class", start_at=at_local(TODAY + timedelta(days=1), 9, 0)
    )
    undated = candidate("s-0", title="Chair Class", start_at=None)
    ranked = rank_candidates_with_breakdown(
        [later, undated, sooner],
        ActivityIntent(),
        ActivityPreferences(person_id="p"),
        diversity=False,
    )
    assert [
        e.ranked.candidate.activity_id
        for e in score_and_sort(
            [later, undated, sooner], ActivityIntent(), ActivityPreferences(person_id="p")
        )
    ] == ["s-b", "s-a", "s-0"]
    keys = {e.ranked.series_key for e in ranked}
    assert keys == {series_key(later)} and "\x1f" in series_key(later)
    assert series_keys_for([later, sooner]) == {"s-a": series_key(later), "s-b": series_key(sooner)}
