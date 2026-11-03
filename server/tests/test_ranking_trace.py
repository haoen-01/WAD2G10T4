"""The ranking path's pure extractions: the sort key, the per-axis and per-belief detail,
engagement counting and the travel note.

Pure, like `test_activity_search.py`: no database, no network. The traced path
(`activity_search.rank_with_trace`), the planner merge and the integrity classifier these tests
also pinned went with the search route and the ranker inspector in step 7; what is left here is
the ranking `advance` still uses through replanning.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from silverloop.activity_search import (
    ActivityEngagement,
    count_engagement,
    engagement_by_series,
    filter_candidates,
    postprocess,
    rank_candidates_with_breakdown,
    score_and_sort,
    score_and_sort_detailed,
    series_key,
    series_keys_for,
    sort_key_for,
)
from silverloop.fixtures import synthetic_activity_candidates
from silverloop.local_time import at_local
from silverloop.models import (
    ActivityAvailability,
    ActivityCandidate,
    ActivityIntensity,
    ActivityIntent,
    ActivityLocation,
    ActivityPreferences,
    ActivitySource,
    DeclineReason,
    DimensionPreference,
    IndoorOutdoor,
    IntegrationStatus,
    IntentParser,
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


# ── The untraced ranking path ─────────────────────────────────────────────────────────────────


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
    # What the keyword parser (removed with the search route in step 7) read "something near me" as.
    intent = ActivityIntent(
        raw_text="something near me", max_distance_m=1000, parsed_by=IntentParser.KEYWORD
    )
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


# ── Stated beliefs ────────────────────────────────────────────────────────────────────────────


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
