"""`silverloop.activity_search` -- the deterministic filter, ranker and reason generator for the
user-initiated loop (F27).

Everything here is pure, so every test constructs its own inputs and asserts on the return value
directly -- no database, no fixtures, no network. That is deliberate: this module's entire safety
argument is that the filter runs before anything else (model or ranker) sees a candidate, and
that argument only holds if the filter's behaviour is provable in exactly this style.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from silverloop.activity_search import filter_candidates, rank_candidates, reasons_for
from silverloop.context_question import QUESTION_ID, memory_from_answer
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
    Enjoyment,
    IndoorOutdoor,
    IntegrationStatus,
    IntentParser,
    LikedAspect,
    PreferenceDimension,
    ReasonBasis,
    SocialPreference,
    TimeWindow,
)
from silverloop.ontology import ActivityType
from silverloop.preferences import apply_decline, apply_enjoyment, resolve

TODAY = date(2026, 9, 10)
NOW = datetime(2026, 9, 10, 8, 0)


def candidate(
    activity_id: str = "act-1",
    *,
    title: str = "Chair Yoga",
    start_at: datetime | None = datetime(2026, 9, 10, 9, 0),
    indoor_outdoor: IndoorOutdoor = IndoorOutdoor.INDOOR,
    intensity: ActivityIntensity | None = ActivityIntensity.LIGHT,
    distance_m: int | None = 500,
    availability: ActivityAvailability = ActivityAvailability.AVAILABLE,
    language_tags: list[str] | None = None,
    category: str | None = "Movement",
    social_shape: SocialPreference | None = None,
    activity_type: ActivityType | None = None,
) -> ActivityCandidate:
    return ActivityCandidate(
        activity_id=activity_id,
        source=ActivitySource.AAC_FIXTURE,
        integration_status=IntegrationStatus.FIXTURE,
        title=title,
        provider="Fixture AAC",
        start_at=start_at,
        location=ActivityLocation(name="Community Club"),
        category=category,
        activity_type=activity_type,
        indoor_outdoor=indoor_outdoor,
        intensity=intensity,
        social_shape=social_shape,
        accessibility_tags=[],
        language_tags=language_tags or [],
        capacity=10,
        availability=availability,
        price=None,
        source_url=None,
        retrieved_at=datetime(2026, 9, 9, 0, 0),
        distance_m=distance_m,
    )


def intent(**overrides: object) -> ActivityIntent:
    base: dict[str, object] = {}
    base.update(overrides)
    return ActivityIntent(**base)


def preferences(dimensions: list[DimensionPreference] | None = None) -> ActivityPreferences:
    return ActivityPreferences(person_id="p1", dimensions=dimensions or [])


# ── filter_candidates ─────────────────────────────────────────────────────────────────────────


def test_no_constraints_keeps_everything() -> None:
    candidates = [candidate("a"), candidate("b", start_at=None, distance_m=None)]
    kept, removed = filter_candidates(candidates, intent(), today=TODAY)
    assert [c.activity_id for c in kept] == ["a", "b"]
    assert removed == []


def test_too_far_is_removed_with_a_named_rule() -> None:
    far = candidate("far", distance_m=5000)
    near = candidate("near", distance_m=200)
    kept, removed = filter_candidates(
        [far, near], intent(max_distance_m=1000, distance_is_explicit=True), today=TODAY
    )
    assert [c.activity_id for c in kept] == ["near"]
    assert len(removed) == 1
    assert removed[0].activity_id == "far"
    assert removed[0].rule == "too_far"
    assert "5" in removed[0].detail or "5000" in removed[0].detail


def test_unknown_distance_is_never_excluded_as_too_far() -> None:
    """Absence of information must never be treated as a match failure."""
    unknown = candidate("unknown", distance_m=None)
    kept, removed = filter_candidates(
        [unknown], intent(max_distance_m=500, distance_is_explicit=True), today=TODAY
    )
    assert [c.activity_id for c in kept] == ["unknown"]
    assert removed == []


def test_wrong_day_is_removed_when_a_specific_day_was_requested() -> None:
    wrong_day = candidate("wrong", start_at=datetime(2026, 9, 12, 9, 0))
    right_day = candidate("right", start_at=datetime(2026, 9, 10, 9, 0))
    kept, removed = filter_candidates(
        [wrong_day, right_day], intent(on_date=date(2026, 9, 10)), today=TODAY
    )
    assert [c.activity_id for c in kept] == ["right"]
    assert removed[0].rule == "wrong_day"


def test_already_run_listings_are_closed_even_without_a_specific_day_request() -> None:
    past = candidate("past", start_at=datetime(2026, 9, 1, 9, 0))
    kept, removed = filter_candidates([past], intent(), today=TODAY)
    assert kept == []
    assert removed[0].rule == "wrong_day"
    assert "Already ran" in removed[0].detail


def test_undated_listing_is_never_filtered_on_day() -> None:
    """An ongoing/drop-in listing with no `start_at` cannot be judged against a day at all."""
    undated = candidate("undated", start_at=None)
    kept, removed = filter_candidates([undated], intent(on_date=date(2026, 9, 10)), today=TODAY)
    assert [c.activity_id for c in kept] == ["undated"]
    assert removed == []


def test_wrong_time_window_is_removed() -> None:
    # Built in local wall-clock time, because that is what "morning" and "evening" mean to the
    # person reading the card. Written as bare UTC these were 5pm and 3am local, and the filter
    # agreed with neither the name nor the rendered time.
    morning = candidate("morning", start_at=at_local(date(2026, 9, 10), 9, 0))
    evening = candidate("evening", start_at=at_local(date(2026, 9, 10), 19, 0))
    kept, removed = filter_candidates(
        [morning, evening], intent(time_window=TimeWindow.EVENING), today=TODAY
    )
    assert [c.activity_id for c in kept] == ["evening"]
    assert removed[0].rule == "wrong_time_window"


def test_wrong_environment_is_removed_but_sheltered_satisfies_indoor_or_outdoor() -> None:
    indoor = candidate("indoor", indoor_outdoor=IndoorOutdoor.INDOOR)
    outdoor = candidate("outdoor", indoor_outdoor=IndoorOutdoor.OUTDOOR)
    sheltered = candidate("sheltered", indoor_outdoor=IndoorOutdoor.SHELTERED)

    kept, removed = filter_candidates(
        [indoor, outdoor, sheltered], intent(environment=ActivityEnvironment.INDOOR), today=TODAY
    )
    assert {c.activity_id for c in kept} == {"indoor", "sheltered"}
    assert removed[0].activity_id == "outdoor"
    assert removed[0].rule == "wrong_environment"


def test_unknown_environment_is_never_excluded() -> None:
    unknown = candidate("unknown", indoor_outdoor=IndoorOutdoor.UNKNOWN)
    kept, removed = filter_candidates(
        [unknown], intent(environment=ActivityEnvironment.OUTDOOR), today=TODAY
    )
    assert [c.activity_id for c in kept] == ["unknown"]
    assert removed == []


def test_full_activity_is_removed() -> None:
    full = candidate("full", availability=ActivityAvailability.FULL)
    kept, removed = filter_candidates([full], intent(), today=TODAY)
    assert kept == []
    assert removed[0].rule == "full"


def test_language_mismatch_is_inaccessible() -> None:
    mandarin_only = candidate("mandarin", language_tags=["Mandarin"])
    kept, removed = filter_candidates([mandarin_only], intent(language="English"), today=TODAY)
    assert kept == []
    assert removed[0].rule == "inaccessible"


def test_unlisted_language_is_never_excluded() -> None:
    """A candidate with no language tags at all is an honest 'not listed', not a mismatch."""
    unlisted = candidate("unlisted", language_tags=[])
    kept, removed = filter_candidates([unlisted], intent(language="English"), today=TODAY)
    assert [c.activity_id for c in kept] == ["unlisted"]
    assert removed == []


def test_only_the_first_matching_rule_is_recorded() -> None:
    """A candidate failing several rules is reported once, for the rule that decided it."""
    bad = candidate(
        "bad",
        distance_m=9000,
        availability=ActivityAvailability.FULL,
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
    )
    _, removed = filter_candidates(
        [bad],
        intent(
            max_distance_m=100,
            distance_is_explicit=True,
            environment=ActivityEnvironment.INDOOR,
        ),
        today=TODAY,
    )
    assert len(removed) == 1
    assert removed[0].rule == "too_far"


# ── reasons_for ────────────────────────────────────────────────────────────────────────────────


def test_reasons_cap_at_three_and_cite_only_populated_fields() -> None:
    c = candidate(
        distance_m=300,
        indoor_outdoor=IndoorOutdoor.INDOOR,
        intensity=ActivityIntensity.LIGHT,
        language_tags=["English"],
    )
    request = intent(
        max_distance_m=1000,
        time_window=TimeWindow.MORNING,
        environment=ActivityEnvironment.INDOOR,
        intensity=ActivityIntensity.LIGHT,
        language="English",
    )
    reasons = reasons_for(c, request, preferences())
    assert len(reasons) <= 3
    assert all(reason.basis == ReasonBasis.INTENT for reason in reasons)


def test_no_reason_asserts_an_unknown_field() -> None:
    c = candidate(distance_m=None, indoor_outdoor=IndoorOutdoor.UNKNOWN, intensity=None)
    request = intent(
        max_distance_m=1000,
        environment=ActivityEnvironment.INDOOR,
        intensity=ActivityIntensity.LIGHT,
    )
    reasons = reasons_for(c, request, preferences())
    joined = " ".join(reason.text for reason in reasons)
    assert "Indoors" not in joined
    assert "km" not in joined and " m " not in joined


def test_catalogue_fallback_only_appears_when_nothing_else_grounds_a_reason() -> None:
    c = candidate(distance_m=None, indoor_outdoor=IndoorOutdoor.UNKNOWN, intensity=None)
    reasons = reasons_for(c, intent(), preferences())
    assert len(reasons) == 1
    assert reasons[0].basis == ReasonBasis.CATALOGUE


def test_preference_dimension_grounds_a_reason_when_it_matches_a_populated_field() -> None:
    c = candidate(indoor_outdoor=IndoorOutdoor.INDOOR)
    prefs = preferences(
        [
            DimensionPreference(
                dimension=PreferenceDimension.ENVIRONMENT,
                value="indoor",
                strength=0.6,
                source="decline_reason",
                updated_at=datetime(2026, 9, 1, 0, 0),
            )
        ]
    )
    reasons = reasons_for(c, intent(), prefs)
    assert any(reason.basis == ReasonBasis.PREFERENCE for reason in reasons)


def test_negative_preference_never_grounds_a_why_this_fits_reason() -> None:
    c = candidate(indoor_outdoor=IndoorOutdoor.INDOOR)
    prefs = preferences(
        [
            DimensionPreference(
                dimension=PreferenceDimension.ENVIRONMENT,
                value="indoor",
                strength=-0.6,
                source="decline_reason",
                updated_at=datetime(2026, 9, 1, 0, 0),
            )
        ]
    )
    reasons = reasons_for(c, intent(), prefs)
    assert all(reason.basis != ReasonBasis.PREFERENCE for reason in reasons)


def test_social_preference_never_grounds_a_reason_when_the_listing_does_not_say() -> None:
    """`social_shape=None` is an honest "not listed" -- SOCIAL must never be asserted against it,
    same discipline every other axis follows for a field the catalogue left unset.
    """
    c = candidate(social_shape=None)
    prefs = preferences(
        [
            DimensionPreference(
                dimension=PreferenceDimension.SOCIAL,
                value="social",
                strength=0.9,
                source="senior_statement",
                confirmed=True,
                updated_at=datetime(2026, 9, 1, 0, 0),
            )
        ]
    )
    reasons = reasons_for(c, intent(social_preference=SocialPreference.SOCIAL), prefs)
    assert all(reason.basis != ReasonBasis.PREFERENCE for reason in reasons)


def test_social_preference_grounds_a_reason_when_the_candidate_confirms_it() -> None:
    """The defect this test exists to close: a senior confirms `PreferenceDimension.SOCIAL` via
    `context_question.memory_from_answer` ("lean towards suggestions with company"), and a
    candidate that actually is social must be shown a PREFERENCE-basis line for it -- not silently
    ignored the way it was when `_preference_reason` had no SOCIAL branch at all.
    """
    c = candidate(social_shape=SocialPreference.SOCIAL)
    prefs = preferences(
        [
            DimensionPreference(
                dimension=PreferenceDimension.SOCIAL,
                value=SocialPreference.SOCIAL.value,
                strength=0.9,
                source="senior_statement",
                confirmed=True,
                updated_at=datetime(2026, 9, 1, 0, 0),
            )
        ]
    )
    reasons = reasons_for(c, intent(), prefs)
    assert any(reason.basis == ReasonBasis.PREFERENCE for reason in reasons)


def test_solo_candidate_never_grounds_a_confirmed_social_reason() -> None:
    """A confirmed preference for company must not paint a solo listing as a match."""
    c = candidate(social_shape=SocialPreference.SOLO)
    prefs = preferences(
        [
            DimensionPreference(
                dimension=PreferenceDimension.SOCIAL,
                value=SocialPreference.SOCIAL.value,
                strength=0.9,
                source="senior_statement",
                confirmed=True,
                updated_at=datetime(2026, 9, 1, 0, 0),
            )
        ]
    )
    reasons = reasons_for(c, intent(), prefs)
    assert all(reason.basis != ReasonBasis.PREFERENCE for reason in reasons)


def test_an_activity_type_preference_grounds_a_reason_when_it_matches() -> None:
    """`NOT_FOR_ME` writes `ACTIVITY_TYPE`, and `LikedAspect.ACTIVITY` too. The line names the
    kind of thing in the reader's own words ("Tai chi"), never the enum value."""
    c = candidate(activity_type=ActivityType.TAI_CHI, category="Group class")
    prefs = preferences(
        [
            DimensionPreference(
                dimension=PreferenceDimension.ACTIVITY_TYPE,
                value=ActivityType.TAI_CHI.value,
                strength=0.4,
                source="inferred",
                observations=2,
                updated_at=datetime(2026, 9, 1, 0, 0),
            )
        ]
    )
    reasons = reasons_for(c, intent(), prefs)
    assert any(
        reason.basis == ReasonBasis.PREFERENCE and "tai chi" in reason.text.lower()
        for reason in reasons
    )


def test_a_format_label_never_grounds_a_reason_any_more() -> None:
    """`CATEGORY` is deprecated: its values are format labels ("Group class"), so one belief about
    them covered nine unrelated programmes. A row written before the split is still readable and
    still forgettable, but it neither scores nor speaks."""
    c = candidate(category="Group class", activity_type=None)
    prefs = preferences(
        [
            DimensionPreference(
                dimension=PreferenceDimension.CATEGORY,
                value="Group class",
                strength=1.0,
                source="senior_statement",
                confirmed=True,
                observations=1,
                updated_at=datetime(2026, 9, 1, 0, 0),
            )
        ]
    )
    breakdown, reasons = score_candidate(c, intent(), prefs)
    assert not any(reason.basis == ReasonBasis.PREFERENCE for reason in reasons)
    assert _factors_of(breakdown)["preference"].value == 0.0


def test_negative_category_preference_never_grounds_a_why_this_fits_reason() -> None:
    c = candidate(category="Tai Chi")
    prefs = preferences(
        [
            DimensionPreference(
                dimension=PreferenceDimension.CATEGORY,
                value="Tai Chi",
                strength=-0.6,
                source="decline_reason",
                updated_at=datetime(2026, 9, 1, 0, 0),
            )
        ]
    )
    reasons = reasons_for(c, intent(), prefs)
    assert all(reason.basis != ReasonBasis.PREFERENCE for reason in reasons)


def test_environment_preference_matches_indoor_outdoor_never_category() -> None:
    """The reconciled definition: ENVIRONMENT is `indoor_outdoor` only. A candidate whose
    `category` happens to collide with the stored value, but whose `indoor_outdoor` does not
    match, must not be treated as a match -- and one whose `indoor_outdoor` does match, despite an
    unrelated `category`, must be. Pins `preferences._environment_value` against the definition
    `activity_search._preference_reason` reads it through.
    """
    category_collides_but_indoor_outdoor_does_not = candidate(
        category="indoor", indoor_outdoor=IndoorOutdoor.OUTDOOR
    )
    prefs = preferences(
        [
            DimensionPreference(
                dimension=PreferenceDimension.ENVIRONMENT,
                value="indoor",
                strength=0.6,
                source="decline_reason",
                updated_at=datetime(2026, 9, 1, 0, 0),
            )
        ]
    )
    reasons = reasons_for(category_collides_but_indoor_outdoor_does_not, intent(), prefs)
    assert all(reason.basis != ReasonBasis.PREFERENCE for reason in reasons)

    matches_via_indoor_outdoor_despite_unrelated_category = candidate(
        category="Tai Chi", indoor_outdoor=IndoorOutdoor.INDOOR
    )
    reasons = reasons_for(matches_via_indoor_outdoor_despite_unrelated_category, intent(), prefs)
    assert any(reason.basis == ReasonBasis.PREFERENCE for reason in reasons)


# ── rank_candidates ────────────────────────────────────────────────────────────────────────────


def test_ranking_is_stable_and_assigns_sequential_ranks() -> None:
    candidates = [candidate("a"), candidate("b")]
    ranked = rank_candidates(candidates, intent(), preferences())
    assert [item.rank for item in ranked] == [1, 2]


def test_more_intent_matches_rank_higher() -> None:
    """Both listings answer all three asks, so "more matches" is unambiguous: one contradicts
    none of them and the other contradicts two."""
    good_fit = candidate(
        "good",
        distance_m=200,
        start_at=_MORNING,
        indoor_outdoor=IndoorOutdoor.INDOOR,
    )
    weak_fit = candidate(
        "weak",
        distance_m=900,
        start_at=at_local(TODAY, 15, 0),
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
    )
    request = intent(
        max_distance_m=1000, time_window=TimeWindow.MORNING, environment=ActivityEnvironment.INDOOR
    )
    ranked = rank_candidates([weak_fit, good_fit], request, preferences())
    assert [item.candidate.activity_id for item in ranked] == ["good", "weak"]


def test_an_unlisted_field_never_lowers_the_request_fit() -> None:
    """B-F3. An axis a listing does not answer is out of the numerator *and* the denominator. It
    used to land in the denominator as a miss, and because the tier is the primary sort key, no
    learned like, history or weather could ever lift that listing back -- the one place the code
    made "not listed" behave exactly like "no"."""
    listed = candidate("listed", distance_m=200, start_at=_MORNING, language_tags=["English"])
    unlisted = candidate("unlisted", distance_m=200, start_at=_MORNING, language_tags=[])
    request = intent(max_distance_m=1000, time_window=TimeWindow.MORNING, language="English")

    ranked = rank_candidates_with_breakdown([unlisted, listed], request, preferences())
    by_id = {item.ranked.candidate.activity_id: item for item in ranked}
    assert _factors(by_id["unlisted"])["intent"].value == _factors(by_id["listed"])["intent"].value
    assert "not listed" in _factors(by_id["unlisted"])["intent"].note


def test_at_equal_fit_the_candidate_with_more_matched_axes_ranks_first() -> None:
    """The other half of the same rule. Excluding UNKNOWN from the denominator alone would trade
    one error for its mirror -- an unanswerable listing scoring exactly like a confirmed match --
    so at equal fit and equal total the one that actually matches more ranks first."""
    listed = candidate("listed", distance_m=200, start_at=_MORNING, language_tags=["English"])
    unlisted = candidate("unlisted", distance_m=200, start_at=_MORNING, language_tags=[])
    request = intent(max_distance_m=1000, time_window=TimeWindow.MORNING, language="English")

    ranked = rank_candidates_with_breakdown([unlisted, listed], request, preferences())
    assert [item.ranked.candidate.activity_id for item in ranked] == ["listed", "unlisted"]
    assert ranked[0].breakdown.total == ranked[1].breakdown.total
    assert ranked[0].breakdown.matched_axes > ranked[1].breakdown.matched_axes


def test_a_listing_that_can_answer_nothing_is_not_scored_as_a_contradiction() -> None:
    """Red team P2-6, the `judged == 0` corner of the same rule.

    `matched / judged` fell to `0.0` when *every* constrained axis was UNKNOWN -- the same value
    a listing that contradicts everything earns, on the primary sort key. So a listing that said
    nothing about the one thing asked for tied, on tier and on total, with one that said the
    opposite, and the order between them fell through to the title. The breakdown note said the
    axis was "scored neither way" while the score said it was a miss.

    A listing whose only judgeable axis matched scores `1.0`; one that judges nothing is the
    limit of that, not its opposite -- on the *tier*. It earns no intent *credit* (D13): paying it
    the full intent weight for saying nothing out-scored listings that actually fit, with no line
    on its card to say why. The genuine match ranks first on total.
    """
    matches = candidate("a-match", start_at=None, language_tags=["Mandarin"])
    mismatches = candidate("b-mismatch", start_at=None, language_tags=["Tamil"])
    unlisted = candidate("c-unlisted", start_at=None, language_tags=[])
    request = intent(language="Mandarin")

    ranked = rank_candidates_with_breakdown([matches, mismatches, unlisted], request, preferences())
    assert [item.ranked.candidate.activity_id for item in ranked] == [
        "a-match",
        "c-unlisted",
        "b-mismatch",
    ]

    by_id = {item.ranked.candidate.activity_id: item for item in ranked}
    # The tier keeps "not listed" level with a match and above a contradiction ...
    assert by_id["c-unlisted"].breakdown.tier == by_id["a-match"].breakdown.tier == 1.0
    assert by_id["b-mismatch"].breakdown.tier == 0.0
    # ... while the credit pays only for what the listing is known to satisfy.
    assert _factors(by_id["c-unlisted"])["intent"].value == 0.0
    assert _factors(by_id["c-unlisted"])["intent"].contribution == 0.0
    assert _factors(by_id["a-match"])["intent"].value == 1.0
    assert _factors(by_id["b-mismatch"])["intent"].value == 0.0
    assert by_id["c-unlisted"].breakdown.total == round(by_id["a-match"].breakdown.total - 7.0, 3)
    assert by_id["c-unlisted"].breakdown.matched_axes == 0
    assert by_id["a-match"].breakdown.matched_axes == 1
    assert "earns no credit" in _factors(by_id["c-unlisted"])["intent"].note
    # No INTENT line is owed for a contribution that is not there.
    assert all(r.basis is not ReasonBasis.INTENT for r in by_id["c-unlisted"].ranked.reasons)


def test_an_unconstrained_request_still_scores_every_listing_the_same() -> None:
    """The neutral value is for a request that asked for something this listing cannot answer.
    When nobody asked for anything there is nothing to be neutral about, and every listing takes
    the same value either way -- so it is left where it was rather than raised with it."""
    ranked = rank_candidates_with_breakdown(
        [candidate("a", start_at=None), candidate("b", start_at=None, language_tags=[])],
        intent(),
        preferences(),
    )
    assert {_factors(item)["intent"].value for item in ranked} == {0.0}


def test_closer_candidate_breaks_a_tie() -> None:
    far = candidate("far", distance_m=900, start_at=None, indoor_outdoor=IndoorOutdoor.UNKNOWN)
    near = candidate("near", distance_m=100, start_at=None, indoor_outdoor=IndoorOutdoor.UNKNOWN)
    ranked = rank_candidates([far, near], intent(), preferences())
    assert [item.candidate.activity_id for item in ranked] == ["near", "far"]


def test_a_confirmed_social_preference_actually_changes_the_ranking() -> None:
    """The loop the rest of this file's SOCIAL/CATEGORY tests exist to prove is wired end to end,
    not just reachable in isolation: a senior answers the quiet-day check-in, names being alone as
    the reason, `context_question.memory_from_answer` proposes exactly the memory the confirmation
    dialog shows ("lean towards suggestions with company"), and once that proposal is confirmed and
    stored as a `senior_statement` `DimensionPreference`, the very next search reorders its results
    because of it -- not merely describes the preference on some other screen.

    Before `_preference_reason` grew a SOCIAL branch, this test would have failed: the two
    candidates tie on everything `rank_candidates` could see, so confirming the preference would
    have made no observable difference to the order at all.
    """
    proposal = memory_from_answer(
        QUESTION_ID, "not_feeling_it", "I don't like going out on my own", NOW
    )
    assert proposal is not None
    assert proposal.dimension is PreferenceDimension.SOCIAL
    assert proposal.value == SocialPreference.SOCIAL.value

    confirmed_preference = DimensionPreference(
        dimension=proposal.dimension,
        value=proposal.value,
        strength=1.0,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
    )

    # Identical in every way `rank_candidates` can otherwise see, and titled so the tie-break
    # alone -- absent any preference -- would favour the solo one.
    solo = candidate(
        "solo-circle", title="AAA solo circle", social_shape=SocialPreference.SOLO, distance_m=500
    )
    social = candidate(
        "social-circle",
        title="ZZZ social circle",
        social_shape=SocialPreference.SOCIAL,
        distance_m=500,
    )

    before = rank_candidates([solo, social], intent(), preferences())
    assert [item.candidate.activity_id for item in before] == ["solo-circle", "social-circle"]

    after = rank_candidates([solo, social], intent(), preferences([confirmed_preference]))
    assert [item.candidate.activity_id for item in after] == ["social-circle", "solo-circle"]

    winner = after[0]
    # A confirmed statement is named as what the person said, never as something "before".
    assert [reason.text for reason in winner.reasons if reason.basis == ReasonBasis.PREFERENCE] == [
        "With other people, which you said you like."
    ]


def test_rain_forecast_ranks_indoor_and_sheltered_above_outdoor_when_environment_is_open() -> None:
    outdoor = candidate("outdoor", indoor_outdoor=IndoorOutdoor.OUTDOOR, distance_m=100)
    indoor = candidate("indoor", indoor_outdoor=IndoorOutdoor.INDOOR, distance_m=900)
    ranked = rank_candidates(
        [outdoor, indoor],
        intent(environment=ActivityEnvironment.EITHER),
        preferences(),
        rain_forecast=True,
    )
    assert [item.candidate.activity_id for item in ranked] == ["indoor", "outdoor"]
    top = ranked[0]
    assert any(reason.basis == ReasonBasis.CONTEXT for reason in top.reasons)


def test_rain_forecast_never_overrides_an_explicit_outdoor_request() -> None:
    """F35: rain nudges an open request, it does not override a stated one."""
    outdoor = candidate("outdoor", indoor_outdoor=IndoorOutdoor.OUTDOOR, distance_m=100)
    indoor = candidate("indoor", indoor_outdoor=IndoorOutdoor.INDOOR, distance_m=900)
    ranked = rank_candidates(
        [outdoor, indoor],
        intent(environment=ActivityEnvironment.OUTDOOR),
        preferences(),
        rain_forecast=True,
    )
    assert ranked[0].candidate.activity_id == "outdoor"
    assert all(reason.basis != ReasonBasis.CONTEXT for item in ranked for reason in item.reasons)


def test_rain_forecast_false_never_reorders_on_environment() -> None:
    outdoor = candidate("outdoor", indoor_outdoor=IndoorOutdoor.OUTDOOR, distance_m=900)
    indoor = candidate("indoor", indoor_outdoor=IndoorOutdoor.INDOOR, distance_m=100)
    ranked = rank_candidates(
        [outdoor, indoor], intent(environment=ActivityEnvironment.EITHER), preferences()
    )
    # No rain bias: pure distance/other scoring decides, and the closer one (indoor, 100m) wins
    # on its own merits -- but no CONTEXT reason should appear anywhere.
    assert all(reason.basis != ReasonBasis.CONTEXT for item in ranked for reason in item.reasons)


@pytest.mark.parametrize("count", [0, 1])
def test_rank_candidates_handles_small_lists(count: int) -> None:
    candidates = [candidate(str(i)) for i in range(count)]
    ranked = rank_candidates(candidates, intent(), preferences())
    assert len(ranked) == count


# ── score_candidate / rank_candidates v2: named factors ───────────────────────────────────────
#
# The order used to be a weighted count of the positive reason lines a person is shown, which
# meant a learned dislike could never demote anything: `_preference_reason` returns nothing for a
# negative strength (correctly -- a dislike is not a reason something fits), and the score was
# built only from what it returned. Three "too far" declines therefore changed nothing about the
# order. The ranker now scores six named, bounded factors (`RANKING_WEIGHTS`), returned beside
# each result by `rank_candidates_with_breakdown` -- never inside the senior's own payload -- and
# the reasons stay exactly what they were.

from datetime import timedelta  # noqa: E402

from silverloop.activity_search import (  # noqa: E402
    DECLINE_COOLDOWN_DAYS,
    RANKING_WEIGHTS,
    ActivityEngagement,
    rank_candidates_with_breakdown,
    score_candidate,
)


def _factors(item) -> dict:  # noqa: ANN001 - test helper over RankedScore
    return {factor.name: factor for factor in item.breakdown.factors}


def _comfortable_out_to(metres: int) -> list[DimensionPreference]:
    """A travel tolerance this wide, the only way one is ever widened: the person enjoyed getting
    somewhere this far. A "too far" at this distance would not do it -- a ceiling only narrows."""
    return apply_enjoyment(
        [], Enjoyment.ENJOYED, [LikedAspect.LOCATION], candidate("floor", distance_m=metres), NOW
    )


def _too_far_at(pivot_m: float, observations: int = 3) -> DimensionPreference:
    """What `apply_decline` writes for a "too far": a ceiling in metres, not a near/far bucket.

    The bucket is the defect. A "too far" at 1.2 km was stored as the bucket the listing fell in
    (`near`), which taught the system to avoid everything under 2 km and left everything beyond it
    untouched -- the exact opposite of what the person said.
    """
    return DimensionPreference(
        dimension=PreferenceDimension.DISTANCE,
        value="lower",
        strength=0.6,
        source="decline_reason",
        confirmed=False,
        observations=observations,
        positive_evidence=float(observations),
        pivot=pivot_m,
        direction="lower",
        updated_at=NOW,
    )


def test_every_factor_is_bounded_and_named() -> None:
    breakdown, _ = score_candidate(candidate("a"), intent(), preferences())
    assert [factor.name for factor in breakdown.factors] == list(RANKING_WEIGHTS)
    for factor in breakdown.factors:
        assert -1.0 <= factor.value <= 1.0
        assert factor.contribution == round(factor.value * factor.weight, 3)
        assert factor.note
    assert breakdown.total == round(sum(f.contribution for f in breakdown.factors), 3)


def test_a_learned_dislike_now_demotes_what_it_applies_to() -> None:
    """The defect this rewrite exists for. Two otherwise-identical candidates and a person who has
    said "not for me" about being outdoors three times: the outdoor one must fall, and the
    breakdown must say a learned preference is why.

    Distance is deliberately not the axis here any more. A learned distance ceiling is absorbed
    into `travel_utility`'s tolerance rather than scored a second time as a preference -- see
    `test_too_far_at_1200m_ranks_a_500m_listing_above_a_1600m_one` for that half.
    """
    outdoors = candidate("outdoors", distance_m=300, indoor_outdoor=IndoorOutdoor.OUTDOOR)
    indoors = candidate("indoors", distance_m=300, indoor_outdoor=IndoorOutdoor.INDOOR)
    avoid_outdoors = DimensionPreference(
        dimension=PreferenceDimension.ENVIRONMENT,
        value="outdoor",
        strength=-0.6,
        source="decline_reason",
        observations=3,
        updated_at=NOW,
    )
    without = rank_candidates_with_breakdown([outdoors, indoors], intent(), preferences())
    with_pref = rank_candidates_with_breakdown(
        [outdoors, indoors], intent(), preferences([avoid_outdoors])
    )
    assert [item.ranked.candidate.activity_id for item in with_pref] == ["indoors", "outdoors"]
    outdoor_factors = _factors(with_pref[1])
    assert outdoor_factors["preference"].value < 0
    assert outdoor_factors["preference"].contribution < 0
    # The penalty is real, not just the tie-break both orders would already have given.
    assert with_pref[1].breakdown.total < without[1].breakdown.total
    # And it never leaks into what a senior receives.
    assert not hasattr(with_pref[1].ranked, "score_breakdown")


def test_a_stated_request_outranks_every_learned_preference_combined() -> None:
    """Current explicit input beats inference. Someone who has said "too far" before but today
    asks for company is shown the social option even though it is far."""
    far_social = candidate("far-social", distance_m=3000, social_shape=SocialPreference.SOCIAL)
    near_solo = candidate("near-solo", distance_m=300, social_shape=SocialPreference.SOLO)
    ranked = rank_candidates(
        [near_solo, far_social],
        intent(social_preference=SocialPreference.SOCIAL),
        preferences([_too_far_at(500, observations=10)]),
    )
    # `near-solo` is removed by the filter's company rule in the product; here it survives only
    # because the filter did not run, which is exactly why the ranker must still put intent first.
    assert ranked[0].candidate.activity_id == "far-social"
    # A stated request outweighs everything learned or inferred combined. Only `repetition` --
    # the person's own recent "not for me" on that exact listing -- sits outside that sum.
    assert RANKING_WEIGHTS["intent"] > sum(
        weight for name, weight in RANKING_WEIGHTS.items() if name not in {"intent", "repetition"}
    )


def test_negative_preference_still_grounds_no_reason_line() -> None:
    """A demotion is not a reason something suits someone -- and a learned distance ceiling
    grounds no line either way, because `travel_utility` is never positive and a card owes a
    reason only for a positive contribution."""
    far = candidate("far", distance_m=3000, indoor_outdoor=IndoorOutdoor.OUTDOOR)
    avoid_outdoors = DimensionPreference(
        dimension=PreferenceDimension.ENVIRONMENT,
        value="outdoor",
        strength=-0.6,
        source="decline_reason",
        observations=3,
        updated_at=NOW,
    )
    _, reasons = score_candidate(far, intent(), preferences([_too_far_at(1200), avoid_outdoors]))
    assert all(reason.basis != ReasonBasis.PREFERENCE for reason in reasons)


def test_travel_utility_is_monotonic_in_distance_and_is_the_only_distance_term() -> None:
    """B-F10. Distance used to be scored in four places -- a friction factor, a learned near/far
    bucket, a hard 1 km parser default and an intent reason line -- with no two agreeing on where
    "far" was. `travel_utility` is the one owner, it never rises with distance, and the learned
    ceiling moves where the cost *starts* rather than adding a second term."""
    from silverloop.activity_search import travel_utility

    values = [travel_utility(metres, 500)[0] for metres in range(0, 8000, 250)]
    assert all(later <= earlier for earlier, later in zip(values, values[1:], strict=False))
    assert min(values) >= -1.0 and max(values) <= 0.0
    # The learned ceiling shifts the whole curve, and nothing else scores distance.
    assert travel_utility(1600, 1200)[0] > travel_utility(1600, 500)[0]
    assert travel_utility(500, 1200)[0] == 0.0
    breakdown, _ = score_candidate(
        candidate("far", distance_m=3000), intent(), preferences([_too_far_at(1200)])
    )
    assert _factors_of(breakdown)["preference"].value == 0.0


def test_too_far_at_1200m_ranks_a_500m_listing_above_a_1600m_one() -> None:
    """A-F2/B-F2/D-§3, the defect in one line. A "too far" at 1.2 km used to be stored as the
    bucket the listing fell in (`near`), which penalised everything under 2 km and left everything
    beyond it untouched: it taught the system to avoid activities near home."""
    close = candidate("close", distance_m=500)
    beyond = candidate("beyond", distance_m=1600)
    ranked = rank_candidates_with_breakdown(
        [beyond, close], intent(), preferences([_too_far_at(1200)])
    )
    assert [item.ranked.candidate.activity_id for item in ranked] == ["close", "beyond"]
    assert _factors(ranked[0])["friction"].value == 0.0
    assert _factors(ranked[1])["friction"].value < 0.0


def test_a_second_too_far_at_900m_lowers_the_tolerance_to_900() -> None:
    """`min(pivot)`, not a smoothed estimate. The tightest thing a person has said is the one
    that binds; an average would let one convenient outing quietly undo three "too far"s -- and a
    smoothing constant with no evaluation behind it is exactly what the audits warned against."""
    from silverloop.preferences import travel_tolerance_m

    # A ceiling only narrows, so it is visible only below a floor: this person once enjoyed
    # getting somewhere 5 km away, and the ceilings cap that.
    floor = apply_enjoyment(
        [], Enjoyment.ENJOYED, [LikedAspect.LOCATION], candidate(distance_m=5000), NOW
    )
    first = _too_far_at(1200, observations=1)
    second = _too_far_at(900, observations=1)
    assert travel_tolerance_m(resolve(floor)) == 5000
    assert travel_tolerance_m(resolve(floor + [first])) == 1200
    # One row, folded twice: the pivot moves to the tighter of the two.
    folded = apply_decline(
        apply_decline(floor, DeclineReason.TOO_FAR, candidate(distance_m=1200), NOW),
        DeclineReason.TOO_FAR,
        candidate(distance_m=900),
        NOW,
    )
    assert travel_tolerance_m(resolve(folded)) == 900
    assert travel_tolerance_m(resolve(floor + [second])) == 900


def test_a_too_far_complaint_never_raises_any_score() -> None:
    """Telling Care+ that 1.2 km was too far must not make anything cheaper to reach. Read as
    the tolerance itself, that complaint lifted the 500 m default to 1.2 km and a liked 2 km
    listing rose from 1.667 to 1.822 because the person had complained. The ceiling narrows the
    start of the travel cost or leaves it alone; every total is the same or lower afterwards."""
    from silverloop.preferences import DEFAULT_TRAVEL_TOLERANCE_M, travel_tolerance_m

    listings = [candidate(f"at-{m}", distance_m=m) for m in (300, 900, 1200, 2000, 4000)]
    before = {
        item.ranked.candidate.activity_id: item.breakdown.total
        for item in rank_candidates_with_breakdown(listings, intent(), preferences([]))
    }
    complained = preferences([_too_far_at(1200)])
    after = {
        item.ranked.candidate.activity_id: item.breakdown.total
        for item in rank_candidates_with_breakdown(listings, intent(), complained)
    }
    assert travel_tolerance_m(resolve(complained.dimensions)) == DEFAULT_TRAVEL_TOLERANCE_M
    assert all(after[key] <= before[key] for key in before)
    # And the direction the person meant still holds by score, not by a tie-break.
    scores = [after[f"at-{m}"] for m in (300, 900, 1200, 2000, 4000)]
    assert scores[0] > scores[1] > scores[2] > scores[3] > scores[4]


def test_friction_grows_with_distance_and_costs_nothing_when_unknown() -> None:
    near, _ = score_candidate(candidate("a", distance_m=400), intent(), preferences())
    far, _ = score_candidate(candidate("b", distance_m=4000), intent(), preferences())
    unknown, _ = score_candidate(candidate("c", distance_m=None), intent(), preferences())
    friction = {b.factors[5].name: b.factors[5].value for b in (near,)}
    assert friction == {"friction": 0.0}
    assert far.factors[5].value < near.factors[5].value
    assert unknown.factors[5].value == 0.0
    # An unknown distance still sorts last on a tie, as before.
    ranked = rank_candidates(
        [candidate("c", distance_m=None), candidate("a", distance_m=400)],
        intent(),
        preferences(),
    )
    assert [item.candidate.activity_id for item in ranked] == ["a", "c"]


# ── A distance phrase costs, where a distance number filters ──────────────────────────────────
#
# ADR 0006 §10 says a phrase is soft and a number is hard, and §12 says distance is scored in
# exactly one place. Both hold -- but "soft" had quietly become "free": `travel_utility` charged
# from the person's *learned* tolerance, so someone whose own answers had widened that tolerance
# (or who had answered nothing and sat on the default) paid the same nothing for a 4 km listing on
# a request that opened with "somewhere close by" as for one round the corner. The radius the
# phrase implies now narrows the tolerance for that one request, and never widens it.


def test_a_close_by_phrase_charges_travel_from_the_radius_it_asked_for() -> None:
    """The bug, in one ordering. Two listings that tie on every axis the request constrained --
    both beyond the 1 km "close by" implied, so both MISMATCH on the distance axis and both in the
    same tier -- and a person who has happily travelled 4.2 km before. The far one
    carries one "I'm interested", which used to be enough to put a 4 km trip above a 1.1 km one
    because neither paid anything for the distance at all.
    """
    near = candidate("near", distance_m=1100)
    far = candidate("far", distance_m=4000)
    asked = intent(max_distance_m=1000, distance_is_explicit=False)
    wide_tolerance = preferences(_comfortable_out_to(4200))
    ranked = rank_candidates_with_breakdown(
        [far, near],
        asked,
        wide_tolerance,
        engagement={"far": ActivityEngagement(interested=1)},
        today=TODAY,
    )
    assert [item.ranked.candidate.activity_id for item in ranked] == ["near", "far"]
    # Same tier: the phrase is not promoted to a filter, and it is not scored twice either.
    assert _factors(ranked[0])["intent"].value == _factors(ranked[1])["intent"].value
    assert _factors(ranked[1])["friction"].value < _factors(ranked[0])["friction"].value < 0.0
    assert "past the 1 km you asked for" in _factors(ranked[1])["friction"].note


def test_a_soft_radius_narrows_a_travel_tolerance_and_never_widens_one() -> None:
    """A request is not permission. Someone whose own "too far" sits at 650 m keeps that ceiling
    on a request that said "within about a kilometre", and the line they are shown still names
    the limit that actually bound -- their own, not today's phrase."""
    from silverloop.activity_search import travel_utility

    narrowed, narrowed_note = travel_utility(2000, 4200, asked_radius_m=1000)
    assert narrowed == round(-1000 / 4500, 3)
    assert "past the 1 km you asked for" in narrowed_note

    kept, kept_note = travel_utility(900, 650, asked_radius_m=1000)
    assert kept == round(-250 / 4500, 3)
    assert "that has suited you" in kept_note
    # Inside both: no cost, and the same answer with or without a radius.
    assert travel_utility(600, 650, asked_radius_m=1000)[0] == 0.0
    # Degenerate and absent radii change nothing rather than reading as "nowhere is close enough".
    assert travel_utility(2000, 4200, asked_radius_m=0) == travel_utility(2000, 4200)
    assert travel_utility(2000, 4200, asked_radius_m=None) == travel_utility(2000, 4200)
    # Still the one distance term, and still monotone once a radius is in play.
    values = [
        travel_utility(metres, 4200, asked_radius_m=1000)[0] for metres in range(0, 8000, 250)
    ]
    assert all(later <= earlier for earlier, later in zip(values, values[1:], strict=False))
    assert min(values) >= -1.0 and max(values) <= 0.0


def test_a_distance_given_as_a_number_filters_and_is_never_charged_as_well() -> None:
    """The asymmetry stays: a number is a barrier spent in `_too_far`, a phrase is a preference
    spent in `travel_utility`, and neither is spent twice. What survives an explicit radius is
    inside it by definition, so nothing kept pays anything for it."""
    far = candidate("far", distance_m=5000)
    near = candidate("near", distance_m=900)
    asked = intent(max_distance_m=1000, distance_is_explicit=True)
    kept, removed = filter_candidates([far, near], asked, today=TODAY)
    assert [c.activity_id for c in kept] == ["near"]
    assert [entry.rule for entry in removed] == ["too_far"]
    breakdown, _ = score_candidate(near, asked, preferences(_comfortable_out_to(4200)))
    assert _factors_of(breakdown)["friction"].value == 0.0


@pytest.mark.parametrize("explicit", [False, True])
def test_moving_a_listing_further_away_never_raises_it(explicit: bool) -> None:
    """Metamorphic. Distance is scored in one place and that place is monotone, so pushing one
    listing further from the person can only ever cost it position -- whether the radius was a
    phrase (it pays from there) or a number (it is removed beyond it). Held against a fixed rival
    at 800 m, with a learned tolerance wide enough that only the request's own radius binds."""
    rival = candidate("rival", distance_m=800)
    asked = intent(max_distance_m=1000, distance_is_explicit=explicit)
    wide_tolerance = preferences(_comfortable_out_to(4200))
    previous = 1
    for distance_m in (300, 700, 1000, 1400, 2500, 4000, 6000):
        moved = candidate("moved", distance_m=distance_m)
        kept, _ = filter_candidates([moved, rival], asked, today=TODAY)
        ranked = rank_candidates(kept, asked, wide_tolerance)
        positions = [item.rank for item in ranked if item.candidate.activity_id == "moved"]
        # Removed by the hard radius: worse than any position it could still hold.
        position = positions[0] if positions else len(ranked) + 1
        assert position >= previous, (distance_m, position, previous)
        previous = position


def test_the_persons_own_responses_move_the_engagement_factor_and_ground_a_history_line() -> None:
    liked = ActivityEngagement(interested=1, went=1, enjoyed=1)
    declined = ActivityEngagement(not_for_me=2)
    a, a_reasons = score_candidate(
        candidate("a"), intent(), preferences(), engagement=liked, today=TODAY
    )
    b, b_reasons = score_candidate(
        candidate("b"), intent(), preferences(), engagement=declined, today=TODAY
    )
    assert a.factors[2].name == "engagement"
    assert a.factors[2].value > 0 > b.factors[2].value
    assert any(reason.basis == ReasonBasis.HISTORY for reason in a_reasons)
    assert "enjoyed" in a_reasons[0].text
    assert a_reasons[0].text == "You enjoyed this one before."
    # A decline is scored, never explained as a reason something fits.
    assert all(reason.basis != ReasonBasis.HISTORY for reason in b_reasons)


def test_a_sibling_session_says_the_programme_never_this_one() -> None:
    """Counts arrive rolled up to the programme, so Friday's card carries Wednesday's outing.
    Ranking wants exactly that; the *line* on the card must not turn it into "You went to this
    one before." about a session the person never attended."""
    inherited = ActivityEngagement(interested=1, went=1, enjoyed=1, own=ActivityEngagement())
    attended = ActivityEngagement(
        interested=1, went=1, enjoyed=1, own=ActivityEngagement(interested=1, went=1, enjoyed=1)
    )

    _, sibling_reasons = score_candidate(
        candidate("friday"), intent(), preferences(), engagement=inherited, today=TODAY
    )
    _, own_reasons = score_candidate(
        candidate("wednesday"), intent(), preferences(), engagement=attended, today=TODAY
    )

    sibling = next(r for r in sibling_reasons if r.basis == ReasonBasis.HISTORY)
    assert sibling.text == "You enjoyed this programme before."
    assert next(r for r in own_reasons if r.basis == ReasonBasis.HISTORY).text == (
        "You enjoyed this one before."
    )
    # The same rule for the two weaker lines, each read on its own evidence.
    went_only = ActivityEngagement(went=1, own=ActivityEngagement())
    interested_only = ActivityEngagement(interested=1, own=ActivityEngagement())
    _, went_reasons = score_candidate(
        candidate("friday"), intent(), preferences(), engagement=went_only, today=TODAY
    )
    _, interest_reasons = score_candidate(
        candidate("friday"), intent(), preferences(), engagement=interested_only, today=TODAY
    )
    assert next(r for r in went_reasons if r.basis == ReasonBasis.HISTORY).text == (
        "You went to this programme before."
    )
    assert next(r for r in interest_reasons if r.basis == ReasonBasis.HISTORY).text == (
        "You said you were interested in this programme before."
    )


def test_a_listing_with_no_roll_up_behind_it_still_speaks_for_itself() -> None:
    """`own` is `None` when the counts already belong to this listing -- what a caller assembling
    one listing's own responses is describing -- and the wording stays "this one"."""
    _, reasons = score_candidate(
        candidate("solo"),
        intent(),
        preferences(),
        engagement=ActivityEngagement(went=1),
        today=TODAY,
    )
    assert next(r for r in reasons if r.basis == ReasonBasis.HISTORY).text == (
        "You went to this one before."
    )


def test_a_recent_not_for_me_holds_a_listing_back_for_the_cooldown_and_then_releases_it() -> None:
    declined_yesterday = {
        "a": ActivityEngagement(not_for_me=1, last_not_for_me=TODAY - timedelta(days=1))
    }
    ranked = rank_candidates_with_breakdown(
        [candidate("a", distance_m=100), candidate("b", distance_m=900)],
        intent(),
        preferences(),
        engagement=declined_yesterday,
        today=TODAY,
    )
    assert [item.ranked.candidate.activity_id for item in ranked] == ["b", "a"]
    assert _factors(ranked[1])["repetition"].value == -1.0

    later = TODAY + timedelta(days=DECLINE_COOLDOWN_DAYS)
    released = rank_candidates_with_breakdown(
        [candidate("a", distance_m=100), candidate("b", distance_m=900)],
        intent(),
        preferences(),
        engagement=declined_yesterday,
        today=later,
    )
    assert all(_factors(item)["repetition"].value == 0.0 for item in released)
    # Released, but the decline itself is still remembered on the engagement factor.
    assert _factors(released[1])["engagement"].value < 0
    assert released[1].ranked.candidate.activity_id == "a"


def test_no_engagement_and_no_today_changes_nothing() -> None:
    """Every existing caller passes neither, and must keep its exact order."""
    candidates = [candidate("a", distance_m=900), candidate("b", distance_m=100)]
    assert [
        i.candidate.activity_id for i in rank_candidates(candidates, intent(), preferences())
    ] == [
        i.candidate.activity_id
        for i in rank_candidates(candidates, intent(), preferences(), engagement={}, today=None)
    ]


def test_diversity_swaps_a_close_alternative_of_another_kind_into_third_place() -> None:
    same = [
        candidate("a", distance_m=500, category="Group class"),
        candidate("b", distance_m=600, category="Group class"),
        candidate("c", distance_m=700, category="Group class"),
    ]
    different = candidate("d", distance_m=800, category="Social group")
    ranked = rank_candidates_with_breakdown([*same, different], intent(), preferences())
    assert [item.ranked.candidate.activity_id for item in ranked] == ["a", "b", "d", "c"]
    promoted = ranked[2]
    assert promoted.breakdown.variety_promoted is True
    assert any(reason.basis == ReasonBasis.VARIETY for reason in promoted.ranked.reasons)
    assert [item.ranked.rank for item in ranked] == [1, 2, 3, 4]
    # The displaced third keeps everything but its position.
    assert ranked[3].breakdown.variety_promoted is False
    # And the plain ranker agrees with its own breakdown view.
    assert [
        item.candidate.activity_id
        for item in rank_candidates([*same, different], intent(), preferences())
    ] == ["a", "b", "d", "c"]


def test_diversity_never_promotes_a_clearly_worse_fit_or_an_uncategorised_listing() -> None:
    same = [candidate(key, distance_m=500, category="Group class") for key in ("a", "b", "c")]
    too_far_off = candidate("far", distance_m=4800, category="Social group")
    # Sorts after "c" on the final `activity_id` tie-break, so if it reaches the top three it can
    # only have been *promoted* there -- which is the thing this test says must never happen.
    unknown_kind = candidate("z-blank", distance_m=500, category=None)
    ranked = rank_candidates_with_breakdown(
        [*same, too_far_off, unknown_kind], intent(), preferences()
    )
    assert [item.ranked.candidate.activity_id for item in ranked[:3]] == ["a", "b", "c"]
    assert all(item.breakdown.variety_promoted is False for item in ranked)


def test_diversity_leaves_a_mixed_top_three_alone() -> None:
    mixed = [
        candidate("a", distance_m=500, category="Group class"),
        candidate("b", distance_m=600, category="Social group"),
        candidate("c", distance_m=700, category="Group class"),
        candidate("d", distance_m=800, category="Self-guided"),
    ]
    ranked = rank_candidates(mixed, intent(), preferences())
    assert [item.candidate.activity_id for item in ranked] == ["a", "b", "c", "d"]
    assert all(reason.basis != ReasonBasis.VARIETY for item in ranked for reason in item.reasons)


def test_rain_costs_an_outdoor_option_and_is_disclosed_in_the_breakdown_not_the_card() -> None:
    outdoor = candidate("out", indoor_outdoor=IndoorOutdoor.OUTDOOR)
    breakdown, reasons = score_candidate(outdoor, intent(), preferences(), rain_forecast=True)
    context = {f.name: f for f in breakdown.factors}["context"]
    assert context.value < 0
    assert all(reason.basis != ReasonBasis.CONTEXT for reason in reasons)


# ── Ranking v2.1: the intent factor is complete, tiered, and the card keeps its invariant ─────


_MORNING = at_local(date(2026, 9, 10), 9, 0)


def _five_axis_request() -> ActivityIntent:
    return intent(
        max_distance_m=1000,
        time_window=TimeWindow.MORNING,
        social_preference=SocialPreference.SOCIAL,
        environment=ActivityEnvironment.INDOOR,
        intensity=ActivityIntensity.LIGHT,
    )


def test_intent_fit_counts_every_matched_axis_not_only_the_three_lines_the_card_shows() -> None:
    """Regression: the factor used to be read off the three-line card, so five of five matched
    scored exactly like three of five, and the request lost its discriminating power precisely
    when it was most specific."""
    full = candidate(
        "full", distance_m=400, social_shape=SocialPreference.SOCIAL, start_at=_MORNING
    )
    partial = candidate(
        "partial",
        distance_m=400,
        start_at=_MORNING,
        social_shape=SocialPreference.SOLO,
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
    )
    ranked = rank_candidates_with_breakdown([partial, full], _five_axis_request(), preferences())
    by_id = {item.ranked.candidate.activity_id: item for item in ranked}
    assert _factors(by_id["full"])["intent"].value == 1.0
    assert _factors(by_id["partial"])["intent"].value == pytest.approx(0.6)
    assert [item.ranked.candidate.activity_id for item in ranked] == ["full", "partial"]
    # The card's face still shows at most three lines; the rest wait until it is opened, and the
    # breakdown counts them.
    assert len(by_id["full"].ranked.reasons) == 3
    assert len(by_id["full"].ranked.more_reasons) == 2
    assert by_id["full"].breakdown.reasons_suppressed == 2
    assert not any(
        line in by_id["full"].ranked.more_reasons for line in by_id["full"].ranked.reasons
    )


def test_a_fuller_match_is_never_overtaken_by_learned_preference_context_and_history() -> None:
    """The tier rule. A candidate matching one of five asks, backed by a stated category
    preference, rain in its favour and a history of enjoyment, still sits below one matching
    all five with nothing learned about it."""
    full = candidate(
        "full", distance_m=400, social_shape=SocialPreference.SOCIAL, start_at=_MORNING
    )
    weak = candidate(
        "weak",
        distance_m=400,
        social_shape=SocialPreference.SOLO,
        indoor_outdoor=IndoorOutdoor.INDOOR,
        intensity=ActivityIntensity.MODERATE,
        start_at=datetime(2026, 9, 10, 15, 0),
        category="Crafts",
        activity_type=ActivityType.ARTS_CRAFTS,
    )
    loves_crafts = DimensionPreference(
        dimension=PreferenceDimension.ACTIVITY_TYPE,
        value=ActivityType.ARTS_CRAFTS.value,
        strength=1.0,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
    )
    ranked = rank_candidates_with_breakdown(
        [weak, full],
        _five_axis_request(),
        preferences([loves_crafts]),
        rain_forecast=True,
        engagement={"weak": ActivityEngagement(interested=2, went=2, enjoyed=2)},
        today=date(2026, 9, 10),
    )
    assert [item.ranked.candidate.activity_id for item in ranked] == ["full", "weak"]
    weak_factors = _factors(ranked[1])
    assert weak_factors["preference"].value > 0 and weak_factors["engagement"].value > 0


def test_a_recent_not_for_me_can_still_pull_a_full_match_down_a_tier() -> None:
    """The one thing allowed to outrank the request: the person's own recent word on that exact
    listing."""
    declined = candidate(
        "declined", distance_m=400, social_shape=SocialPreference.SOCIAL, start_at=_MORNING
    )
    other = candidate(
        "other",
        distance_m=400,
        social_shape=SocialPreference.SOLO,
        category="Crafts",
        start_at=_MORNING,
    )
    ranked = rank_candidates(
        [declined, other],
        _five_axis_request(),
        preferences(),
        engagement={"declined": ActivityEngagement(not_for_me=1, last_not_for_me=date(2026, 9, 9))},
        today=date(2026, 9, 10),
    )
    assert ranked[0].candidate.activity_id == "other"


def test_a_positive_preference_line_is_shown_even_when_three_intent_lines_exist() -> None:
    """The module's invariant, enforced: every positive contribution is a shown reason. Intent
    keeps at least one line and gives up the others before a preference line is dropped."""
    loves_movement = DimensionPreference(
        dimension=PreferenceDimension.ACTIVITY_TYPE,
        value=ActivityType.TAI_CHI.value,
        strength=0.8,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
    )
    c = candidate(
        "a",
        distance_m=400,
        social_shape=SocialPreference.SOCIAL,
        start_at=_MORNING,
        activity_type=ActivityType.TAI_CHI,
    )
    breakdown, reasons = score_candidate(c, _five_axis_request(), preferences([loves_movement]))
    assert _factors_of(breakdown)["preference"].contribution > 0
    assert any(reason.basis == ReasonBasis.PREFERENCE for reason in reasons)
    assert reasons[0].basis == ReasonBasis.INTENT
    assert len(reasons) == 3
    assert breakdown.reasons_suppressed == 3  # five intent lines, two shown


def _factors_of(breakdown) -> dict:  # noqa: ANN001 - test helper over ScoreBreakdown
    return {factor.name: factor for factor in breakdown.factors}


def test_the_top_three_are_never_three_sessions_of_one_programme() -> None:
    sessions = [
        candidate(f"yoga-{n}", title="Chair Yoga", start_at=datetime(2026, 9, 10 + n, 9, 0))
        for n in range(3)
    ]
    walk = candidate("walk", title="Park Walk", category="Walking", distance_m=600)
    craft = candidate("craft", title="Craft Corner", category="Crafts", distance_m=700)
    ranked = rank_candidates_with_breakdown([*sessions, walk, craft], intent(), preferences())
    titles = [item.ranked.candidate.title for item in ranked[:3]]
    assert titles.count("Chair Yoga") == 1
    assert {"Park Walk", "Craft Corner"} <= set(titles)
    deferred = [item for item in ranked if item.breakdown.series_deferred]
    assert len(deferred) == 2 and all(item.ranked.rank > 3 for item in deferred)
    # Nothing was removed.
    assert len(ranked) == 5


def test_the_top_three_never_repeat_a_series_however_many_sessions_are_offered() -> None:
    """`series_duplication_rate@3` was a row in the ranking artifact reading 0.0000 on every arm,
    because `_dedupe_series` always runs -- a property of this module reported as if it were a
    measurement. It belongs here: the guarantee is asserted directly, over a catalogue that is
    mostly repeats, at several pool sizes.
    """
    # Three distinct series or more: with fewer series than slots the dedupe deliberately refills
    # the top three with a second session rather than showing less (see
    # `test_series_dedupe_fills_the_top_three_when_there_is_nothing_else_to_show`).
    for series_count in (3, 5, 8):
        pool = [
            candidate(
                f"s{group}-{session}",
                title=f"Programme {group}",
                category=f"Kind {group}",
                start_at=datetime(2026, 9, 10 + session, 9, 0),
                distance_m=400 + 10 * group,
            )
            for group in range(series_count)
            for session in range(3)
        ]
        ranked = rank_candidates_with_breakdown(pool, intent(), preferences())
        titles = [item.ranked.candidate.title for item in ranked[:3]]
        assert len(set(titles)) == len(titles), (series_count, titles)
        assert len(ranked) == len(pool)  # nothing is ever removed, only deferred


def test_every_hard_constraint_violation_is_removed_before_ranking_ever_sees_it() -> None:
    """`constraint_satisfaction@3` was a headline row in the ranking artifact computed as
    `1.0 if top else 0.0` -- not computed from anything. The property it was gesturing at is real
    and belongs here: `filter_candidates` runs first, so nothing violating a hard constraint can
    reach the ranked list at all.
    """
    # A distance the person gave as a number is a hard rule; a phrase like "near me" is not.
    asked = intent(
        max_distance_m=1000,
        distance_is_explicit=True,
        environment=ActivityEnvironment.INDOOR,
        social_preference=SocialPreference.SOCIAL,
        language="English",
    )
    ok = candidate(
        "ok", distance_m=400, language_tags=["English"], social_shape=SocialPreference.SOCIAL
    )
    violations = [
        candidate("too-far", distance_m=5000, language_tags=["English"]),
        candidate("outdoor", indoor_outdoor=IndoorOutdoor.OUTDOOR, language_tags=["English"]),
        candidate("solo", social_shape=SocialPreference.SOLO, language_tags=["English"]),
        candidate("wrong-language", language_tags=["Mandarin"]),
        candidate("full", availability=ActivityAvailability.FULL, language_tags=["English"]),
    ]
    kept, filtered_out = filter_candidates([ok, *violations], asked, today=date(2026, 9, 9))
    assert [c.activity_id for c in kept] == ["ok"]
    assert {entry.activity_id for entry in filtered_out} == {c.activity_id for c in violations}
    assert all(entry.rule for entry in filtered_out)
    ranked = rank_candidates(kept, asked, preferences())
    assert [item.candidate.activity_id for item in ranked] == ["ok"]


def test_series_dedupe_fills_the_top_three_when_there_is_nothing_else_to_show() -> None:
    sessions = [
        candidate(f"yoga-{n}", title="Chair Yoga", start_at=datetime(2026, 9, 10 + n, 9, 0))
        for n in range(3)
    ]
    walk = candidate("walk", title="Park Walk", category="Walking", distance_m=600)
    ranked = rank_candidates_with_breakdown([*sessions, walk], intent(), preferences())
    assert [item.ranked.candidate.title for item in ranked[:2]] == ["Chair Yoga", "Park Walk"]
    # The third slot is a second yoga session, honestly unflagged: it was not moved below.
    assert not ranked[2].breakdown.series_deferred
    assert ranked[3].breakdown.series_deferred


def test_series_dedupe_keeps_the_best_scoring_session_in_place() -> None:
    later = candidate("yoga-late", title="Chair Yoga", start_at=at_local(date(2026, 9, 11), 15, 0))
    morning = candidate("yoga-am", title="Chair Yoga", start_at=_MORNING)
    others = [candidate(f"o{n}", title=f"Other {n}", category="Crafts") for n in range(3)]
    ranked = rank_candidates(
        [later, morning, *others], intent(time_window=TimeWindow.MORNING), preferences()
    )
    assert ranked[0].candidate.activity_id == "yoga-am"
    assert "yoga-late" not in [item.candidate.activity_id for item in ranked[:3]]


def test_one_decline_is_charged_once_while_the_cooldown_runs() -> None:
    """A "not for me" inside the cooldown is the repetition factor's; the engagement factor does
    not count the same tap a second time. Once the cooldown lapses it moves across."""
    today = date(2026, 9, 10)
    recent = ActivityEngagement(not_for_me=1, last_not_for_me=today - timedelta(days=2))
    breakdown, _ = score_candidate(
        candidate("a"), intent(), preferences(), engagement=recent, today=today
    )
    assert _factors_of(breakdown)["repetition"].value == -1.0
    assert _factors_of(breakdown)["engagement"].value == 0.0
    lapsed = ActivityEngagement(not_for_me=1, last_not_for_me=today - timedelta(days=30))
    breakdown, _ = score_candidate(
        candidate("a"), intent(), preferences(), engagement=lapsed, today=today
    )
    assert _factors_of(breakdown)["repetition"].value == 0.0
    assert _factors_of(breakdown)["engagement"].value < 0


def test_a_superseded_inferred_like_never_speaks_on_the_card() -> None:
    """Precedence on the card as well as in the score: once the person has stated `avoid
    outdoor`, the inferred `outdoor` like from an earlier enjoyment contributes nothing and is
    not cited. The higher tier wins the axis outright rather than being averaged with it."""
    far = candidate("far", distance_m=3000, indoor_outdoor=IndoorOutdoor.OUTDOOR)
    liked_outdoors = DimensionPreference(
        dimension=PreferenceDimension.ENVIRONMENT,
        value="outdoor",
        strength=0.6,
        source="inferred",
        confirmed=False,
        observations=2,
        updated_at=NOW,
    )
    avoid_outdoors = DimensionPreference(
        dimension=PreferenceDimension.ENVIRONMENT,
        value="outdoor",
        strength=-1.0,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
    )
    breakdown, reasons = score_candidate(
        far, intent(), preferences([liked_outdoors, avoid_outdoors])
    )
    assert _factors_of(breakdown)["preference"].value < 0
    assert not any(reason.basis == ReasonBasis.PREFERENCE for reason in reasons)
    # Without the statement, the inferred like is cited as before.
    _, alone = score_candidate(far, intent(), preferences([liked_outdoors]))
    assert any(reason.basis == ReasonBasis.PREFERENCE for reason in alone)


def test_diversity_never_promotes_a_lower_tier_candidate() -> None:
    """The variety swap may only reorder within a tier. A candidate that matched less of what
    the person asked for sits in a lower tier, and no amount of learned preference or engagement
    can lift it into the top three past a fuller match -- that is the invariant `_tier` exists
    to enforce, and the swap used to compare weighted totals alone."""
    from silverloop.activity_search import ActivityEngagement, rank_candidates_with_breakdown
    from silverloop.fixtures import synthetic_activity_candidates

    today = date(2026, 7, 21)
    morning = at_local(today, 9, 0)
    base = synthetic_activity_candidates(today)[0]

    def make(
        activity_id: str,
        title: str,
        activity_type: ActivityType,
        intensity: ActivityIntensity,
    ):
        return base.model_copy(
            update={
                "activity_id": activity_id,
                "title": title,
                "provider": title,
                "activity_type": activity_type,
                "category": "Group class",
                "intensity": intensity,
                "start_at": morning,
                "distance_m": 400,
                "indoor_outdoor": IndoorOutdoor.INDOOR,
                "social_shape": SocialPreference.SOCIAL,
            }
        )

    candidates = [
        make("g1", "Gentle A", ActivityType.TAI_CHI, ActivityIntensity.LIGHT),
        make("g2", "Gentle B", ActivityType.TAI_CHI, ActivityIntensity.LIGHT),
        make("g3", "Gentle C", ActivityType.TAI_CHI, ActivityIntensity.LIGHT),
        make("s1", "Social Hour", ActivityType.SOCIAL_MEETUP, ActivityIntensity.MODERATE),
    ]
    intent = ActivityIntent(time_window=TimeWindow.MORNING, intensity=ActivityIntensity.LIGHT)
    preferences = ActivityPreferences(
        person_id="p1",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.ACTIVITY_TYPE,
                value=ActivityType.SOCIAL_MEETUP.value,
                strength=1.0,
                source="senior_statement",
                confirmed=True,
                observations=1,
                updated_at=datetime(2026, 7, 21, 9, 0),
            )
        ],
    )
    engagement = {"s1": ActivityEngagement(interested=1, went=1, enjoyed=1)}

    ranked = rank_candidates_with_breakdown(
        candidates, intent, preferences, engagement=engagement, today=today
    )
    top_ids = [item.ranked.candidate.activity_id for item in ranked[:3]]
    assert "s1" not in top_ids, [
        (i.ranked.candidate.activity_id, i.breakdown.total) for i in ranked
    ]
    assert not any(item.breakdown.variety_promoted for item in ranked)

    # The same listing at the person's asked-for intensity sits in the same tier as the gentle
    # classes; a little further away it scores just under the third, and then the swap is
    # allowed to do its job.
    same_tier = [
        *candidates[:3],
        candidates[3].model_copy(update={"intensity": ActivityIntensity.LIGHT, "distance_m": 900}),
    ]
    ranked_same_tier = rank_candidates_with_breakdown(
        same_tier, intent, ActivityPreferences(person_id="p1", dimensions=[]), today=today
    )
    assert ranked_same_tier[2].ranked.candidate.activity_id == "s1"
    assert ranked_same_tier[2].breakdown.variety_promoted


# ── Exclusions, and the one distance that is not a limit ───────────────────────────────────────
#
# Each request is the `ActivityIntent` the keyword parser (`intent.parse_intent`, removed with the
# search route in step 7) produced for that sentence, recorded verbatim, so these still pin what the
# filter does with each meaning the sentence carried.
_PARSED: dict[str, ActivityIntent] = {
    "nothing outdoors": ActivityIntent(
        raw_text="nothing outdoors",
        excluded_environments=[IndoorOutdoor.OUTDOOR],
        parsed_by=IntentParser.KEYWORD,
    ),
    "I don't want a group class": ActivityIntent(
        raw_text="I don't want a group class",
        excluded_social=[SocialPreference.SOCIAL],
        parsed_by=IntentParser.KEYWORD,
    ),
    "no walking, my knee": ActivityIntent(
        raw_text="no walking, my knee",
        excluded_activity_types=[ActivityType.WALKING],
        parsed_by=IntentParser.KEYWORD,
        unparsed_terms=["knee"],
    ),
    "I want a walk": ActivityIntent(
        raw_text="I want a walk",
        activity_types=[ActivityType.WALKING],
        parsed_by=IntentParser.KEYWORD,
    ),
    "near me": ActivityIntent(
        raw_text="near me", max_distance_m=1000, parsed_by=IntentParser.KEYWORD
    ),
    "within 800m": ActivityIntent(
        raw_text="within 800m",
        max_distance_m=800,
        distance_is_explicit=True,
        parsed_by=IntentParser.KEYWORD,
    ),
    "no walking tomorrow": ActivityIntent(
        raw_text="no walking tomorrow",
        excluded_activity_types=[ActivityType.WALKING],
        parsed_by=IntentParser.KEYWORD,
    ),
}


def _parsed(text: str) -> ActivityIntent:
    return _PARSED[text]


def test_nothing_outdoors_excludes_outdoor_rather_than_requiring_it() -> None:
    """End to end, the failure audit C found live: the person was shown the *only* outdoor
    listing and nothing else, and the confirmation card claimed to have understood them."""
    outdoor = candidate("outdoor", indoor_outdoor=IndoorOutdoor.OUTDOOR)
    indoor = candidate("indoor", indoor_outdoor=IndoorOutdoor.INDOOR)
    unlisted = candidate("unlisted", indoor_outdoor=IndoorOutdoor.UNKNOWN)

    kept, removed = filter_candidates(
        [outdoor, indoor, unlisted], _parsed("nothing outdoors"), today=TODAY
    )

    assert [c.activity_id for c in kept] == ["indoor", "unlisted"]
    assert [(r.activity_id, r.rule) for r in removed] == [("outdoor", "excluded_environment")]


def test_i_dont_want_a_group_class_does_not_hard_filter_the_self_guided_listings() -> None:
    """Review N2. The sentence used to set `social_preference=SOCIAL`, so `_wrong_company`
    removed every self-guided listing -- the exact opposite of what was asked for."""
    group = candidate("group", social_shape=SocialPreference.SOCIAL)
    self_guided = candidate("self-guided", social_shape=SocialPreference.SOLO)
    unlisted = candidate("unlisted", social_shape=None)

    kept, removed = filter_candidates(
        [group, self_guided, unlisted], _parsed("I don't want a group class"), today=TODAY
    )

    assert [c.activity_id for c in kept] == ["self-guided", "unlisted"]
    assert [(r.activity_id, r.rule) for r in removed] == [("group", "excluded_social")]


def test_no_walking_removes_walks_and_leaves_every_other_listing_alone() -> None:
    walk = candidate("walk", activity_type=ActivityType.WALKING)
    chair = candidate("chair", activity_type=ActivityType.CHAIR_EXERCISE)
    unlabelled = candidate("unlabelled", activity_type=None)
    other = candidate("other", activity_type=ActivityType.OTHER)

    kept, removed = filter_candidates(
        [walk, chair, unlabelled, other], _parsed("no walking, my knee"), today=TODAY
    )

    assert [c.activity_id for c in kept] == ["chair", "unlabelled", "other"]
    assert [(r.activity_id, r.rule) for r in removed] == [("walk", "excluded_activity_type")]


def test_asking_for_a_walk_hides_nothing() -> None:
    """`activity_types` is soft by design. The catalogue is fourteen programmes; a hard content
    filter would turn most requests into "nothing matched", and the honest failure here is
    showing too much rather than hiding the one thing someone wanted."""
    walk = candidate("walk", activity_type=ActivityType.WALKING)
    chair = candidate("chair", activity_type=ActivityType.CHAIR_EXERCISE)

    kept, removed = filter_candidates([walk, chair], _parsed("I want a walk"), today=TODAY)

    assert [c.activity_id for c in kept] == ["walk", "chair"]
    assert removed == []


def test_other_is_never_what_an_exclusion_matched() -> None:
    """`OTHER` means "labelled, and none of the above", so it cannot be the thing ruled out --
    and an intent can never name it, so this is reachable only through a hand-built request."""
    other = candidate("other", activity_type=ActivityType.OTHER)

    kept, _ = filter_candidates(
        [other], intent(excluded_activity_types=[ActivityType.OTHER]), today=TODAY
    )

    assert [c.activity_id for c in kept] == ["other"]


def test_near_me_never_hard_filters_a_1200m_listing_but_within_800m_does() -> None:
    """B-F6, both halves. A vague phrase used to amputate half the catalogue -- including the
    1.2 km sheltered walk -- from someone who had named no limit at all."""
    far = candidate("far", distance_m=1200)
    near = candidate("near", distance_m=400)

    vague_kept, vague_removed = filter_candidates([far, near], _parsed("near me"), today=TODAY)
    assert [c.activity_id for c in vague_kept] == ["far", "near"]
    assert vague_removed == []

    numbered_kept, numbered_removed = filter_candidates(
        [far, near], _parsed("within 800m"), today=TODAY
    )
    assert [c.activity_id for c in numbered_kept] == ["near"]
    assert [(r.activity_id, r.rule) for r in numbered_removed] == [("far", "too_far")]


def test_near_me_hides_nothing_and_is_not_free_either() -> None:
    """The other half of B-F6, written from the same sentence. "Near me" must not amputate the
    catalogue -- but it was heard, so the ranker spends it: a listing past the radius it implied
    pays travel from that radius rather than from a ceiling today's request never mentioned, and
    the breakdown names the limit that bound in the person's own terms."""
    far = candidate("far", distance_m=3400)
    near = candidate("near", distance_m=650)
    asked = _parsed("near me")
    assert asked.max_distance_m == 1000 and asked.distance_is_explicit is False

    # A tolerance wide enough that, before the radius was spent, neither listing paid anything.
    wide_tolerance = preferences(_comfortable_out_to(4200))
    far_breakdown, _ = score_candidate(far, asked, wide_tolerance)
    near_breakdown, _ = score_candidate(near, asked, wide_tolerance)
    assert _factors_of(near_breakdown)["friction"].value == 0.0
    assert _factors_of(far_breakdown)["friction"].value < 0.0
    assert "past the 1 km you asked for" in _factors_of(far_breakdown)["friction"].note


def test_an_exclusion_is_the_reason_recorded_when_several_rules_would_fire() -> None:
    """First match wins, and the exclusions are checked first: "you asked not to be shown walks"
    is a better account of a missing listing than "it runs on Tuesday"."""
    walk = candidate(
        "walk",
        activity_type=ActivityType.WALKING,
        start_at=datetime(2026, 9, 12, 9, 0),
        availability=ActivityAvailability.FULL,
    )

    _, removed = filter_candidates([walk], _parsed("no walking tomorrow"), today=TODAY)

    assert [(r.activity_id, r.rule) for r in removed] == [("walk", "excluded_activity_type")]


def test_diversity_keys_on_activity_type_not_on_format() -> None:
    """A-F4/B-F8. The variety key used to be `category`, which holds a *format* label, so a walk,
    a tai chi class and a gardening session were all "Group class" and counted as the same kind of
    thing -- while a walk and a karaoke session counted as different. Variety on that key was
    variety in how a session is run, which is not what anyone means by it."""
    shared = dict(distance_m=400, start_at=_MORNING, category="Group class")
    # Ids chosen so the walks sort ahead of the tai chi on the final `activity_id` tie-break:
    # the swap, not input order, is what has to put tai chi into the top three.
    walks = [
        candidate(f"a-walk-{index}", activity_type=ActivityType.WALKING, **shared)
        for index in range(3)
    ]
    tai_chi = candidate("b-tai-chi", activity_type=ActivityType.TAI_CHI, **shared)

    ranked = rank_candidates_with_breakdown([*walks, tai_chi], intent(), preferences())
    assert ranked[2].ranked.candidate.activity_id == "b-tai-chi"
    assert ranked[2].breakdown.variety_promoted is True
    # Three sessions of the same *format* are not three of the same kind of thing, so a top three
    # that is already varied by type is left alone.
    varied = [
        candidate("a", activity_type=ActivityType.WALKING, **shared),
        candidate("b", activity_type=ActivityType.TAI_CHI, **shared),
        candidate("c", activity_type=ActivityType.GARDENING, **shared),
        candidate("d", activity_type=ActivityType.KARAOKE, **shared),
    ]
    assert all(
        not item.breakdown.variety_promoted
        for item in rank_candidates_with_breakdown(varied, intent(), preferences())
    )


def test_an_axis_the_request_constrains_is_not_rescored_from_history() -> None:
    """B-F10, the double count. An axis the person spoke about *today* belongs to the hard filter
    or to `intent`; scoring it again from what was learned last month counts the same fact twice
    and lets history argue with what was asked for this morning."""
    indoors = candidate("indoors", indoor_outdoor=IndoorOutdoor.INDOOR, distance_m=400)
    likes_indoors = DimensionPreference(
        dimension=PreferenceDimension.ENVIRONMENT,
        value="indoor",
        strength=1.0,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
    )
    unconstrained, _ = score_candidate(indoors, intent(), preferences([likes_indoors]))
    constrained, _ = score_candidate(
        indoors,
        intent(environment=ActivityEnvironment.INDOOR),
        preferences([likes_indoors]),
    )
    assert _factors_of(unconstrained)["preference"].value > 0
    assert _factors_of(constrained)["preference"].value == 0.0
    # The ask itself is still honoured, on the factor that owns it.
    assert _factors_of(constrained)["intent"].value == 1.0


def test_rain_never_lifts_an_indoor_listing_above_a_better_fit_on_a_dry_day() -> None:
    """B-F11. The rain nudge is a better-fit nudge, not a standing thumb on the scale for being
    indoors: with no rain around it contributes nothing at all, in either direction."""
    indoors = candidate("indoors", indoor_outdoor=IndoorOutdoor.INDOOR, distance_m=2000)
    outdoors = candidate("outdoors", indoor_outdoor=IndoorOutdoor.OUTDOOR, distance_m=400)

    dry = rank_candidates_with_breakdown(
        [indoors, outdoors], intent(), preferences(), rain_forecast=False
    )
    assert [item.ranked.candidate.activity_id for item in dry] == ["outdoors", "indoors"]
    assert all(_factors(item)["context"].value == 0.0 for item in dry)

    wet = rank_candidates_with_breakdown(
        [indoors, outdoors], intent(), preferences(), rain_forecast=True
    )
    assert (
        _factors(next(i for i in wet if i.ranked.candidate.activity_id == "indoors"))[
            "context"
        ].value
        == 1.0
    )


# ── A preference line names where the winning belief came from ────────────────────────────────


def _preference_lines(
    listing: ActivityCandidate,
    rows: list[DimensionPreference],
    *,
    goals: list[object] | None = None,
    today: date = TODAY,
) -> list[str]:
    resolved = resolve(rows, today, goals=goals or [])  # type: ignore[arg-type]
    prefs = ActivityPreferences(person_id="p1", dimensions=rows, resolved=resolved)
    from silverloop.activity_search import score_candidate_detail

    # Face and the lines behind it: five stated likes do not fit on a three-line face.
    detail = score_candidate_detail(listing, intent(), prefs)
    return [
        reason.text
        for reason in [*detail.reasons, *detail.more_reasons]
        if reason.basis is ReasonBasis.PREFERENCE
    ]


def _statement(
    dimension: PreferenceDimension,
    value: str,
    *,
    origin_id: str | None = None,
    expires_at: datetime | None = None,
) -> DimensionPreference:
    return DimensionPreference(
        dimension=dimension,
        value=value,
        strength=1.0,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
        positive_evidence=1.0,
        origin_id=origin_id,
        expires_at=expires_at,
    )


def test_a_stated_or_ratified_like_says_so_and_never_before() -> None:
    listing = candidate(
        social_shape=SocialPreference.SOCIAL,
        activity_type=ActivityType.TAI_CHI,
        start_at=at_local(TODAY, 9, 0),
    )
    stated = [
        _statement(PreferenceDimension.ENVIRONMENT, "indoor"),
        _statement(PreferenceDimension.SOCIAL, "social"),
        _statement(PreferenceDimension.ACTIVITY_TYPE, "tai_chi"),
        _statement(PreferenceDimension.INTENSITY, "light"),
        _statement(PreferenceDimension.TIMING, "morning"),
    ]
    lines = _preference_lines(listing, stated)
    assert sorted(lines) == sorted(
        [
            "Indoors, which you said you like.",
            "With other people, which you said you like.",
            "Tai chi, which you said you like.",
            "Gentle, which you said you like.",
            "Runs in the morning, which you said you like.",
        ]
    )
    ratified = _preference_lines(
        listing, [_statement(PreferenceDimension.ENVIRONMENT, "indoor", origin_id="row-1")]
    )
    assert ratified == ["Indoors, which you said you like."]
    assert not any("before" in line for line in [*lines, *ratified])


def test_a_temporary_statement_and_a_goal_say_what_they_are() -> None:
    listing = candidate(social_shape=SocialPreference.SOCIAL)
    temporary = _preference_lines(
        listing,
        [
            _statement(
                PreferenceDimension.ENVIRONMENT, "indoor", expires_at=datetime(2026, 9, 12, 23, 0)
            )
        ],
    )
    assert temporary == ["Indoors, as you asked for the time being."]

    from silverloop.models import ActivityGoal, GoalKind

    goal = ActivityGoal(goal_id="g1", kind=GoalKind.MEET_PEOPLE, text="Meet people", created_at=NOW)
    goal_lines = _preference_lines(listing, [], goals=[goal])
    assert goal_lines == ["With other people, which is one of your goals."]
    assert not any("before" in line for line in [*temporary, *goal_lines])


def test_learned_lines_say_before_and_the_intensity_ceiling_says_what_it_is() -> None:
    listing = candidate(
        social_shape=SocialPreference.SOCIAL,
        activity_type=ActivityType.TAI_CHI,
        start_at=at_local(TODAY, 9, 0),
    )
    learned = [
        DimensionPreference(
            dimension=dimension,
            value=value,
            strength=0.5,
            source="inferred",
            observations=2,
            updated_at=NOW,
            positive_evidence=2.0,
        )
        for dimension, value in (
            (PreferenceDimension.ENVIRONMENT, "indoor"),
            (PreferenceDimension.SOCIAL, "social"),
            (PreferenceDimension.ACTIVITY_TYPE, "tai_chi"),
            (PreferenceDimension.TIMING, "morning"),
        )
    ]
    lines = _preference_lines(listing, learned)
    assert sorted(lines) == sorted(
        [
            "Indoors, which you've liked before.",
            "With other people, which you've enjoyed before.",
            "Tai chi, which you've enjoyed before.",
            "Runs in the morning, a time that's worked for you before.",
        ]
    )
    solo = _preference_lines(
        candidate(social_shape=SocialPreference.SOLO),
        [learned[1].model_copy(update={"value": "solo"})],
    )
    assert solo == ["Something to do on your own, which has suited you before."]

    # A "too tiring" on something harder is a ceiling, not a liking for gentle things.
    too_tiring = apply_decline(
        [],
        DeclineReason.TOO_TIRING,
        candidate(intensity=ActivityIntensity.MODERATE),
        NOW,
    )
    assert _preference_lines(candidate(intensity=ActivityIntensity.LIGHT), too_tiring) == [
        "Gentle, easier than an activity you found too tiring."
    ]
    # A learned intensity that is not a ceiling (a legacy nominal row) says it has suited them.
    gentle = learned[0].model_copy(
        update={"dimension": PreferenceDimension.INTENSITY, "value": "light"}
    )
    assert _preference_lines(candidate(intensity=ActivityIntensity.LIGHT), [gentle]) == [
        "Gentle, which has suited you before."
    ]


def test_no_reason_line_a_senior_reads_carries_a_double_dash() -> None:
    """Design review: a senior-facing sentence is written with commas, never " -- "."""
    from silverloop.activity_search import ActivityEngagement, rank_candidates_with_breakdown

    listing = candidate(
        social_shape=SocialPreference.SOCIAL,
        activity_type=ActivityType.TAI_CHI,
        start_at=at_local(TODAY, 9, 0),
        indoor_outdoor=IndoorOutdoor.SHELTERED,
    )
    unlabelled = candidate("no-env", indoor_outdoor=IndoorOutdoor.UNKNOWN, category=None)
    rows = [
        _statement(PreferenceDimension.SOCIAL, "social"),
        _statement(PreferenceDimension.ENVIRONMENT, "sheltered", expires_at=datetime(2026, 9, 12)),
        _statement(PreferenceDimension.ACTIVITY_TYPE, "tai_chi", origin_id="ratified"),
    ]
    prefs = ActivityPreferences(person_id="p1", dimensions=rows, resolved=resolve(rows, TODAY))
    ranked = rank_candidates_with_breakdown(
        [listing, unlabelled],
        intent(),
        prefs,
        rain_forecast=True,
        engagement={"act-1": ActivityEngagement(went=1, enjoyed=1)},
        today=TODAY,
    )
    lines = [r.text for e in ranked for r in [*e.ranked.reasons, *e.ranked.more_reasons]]
    assert "Sheltered, a better fit with rain around today." in lines
    assert all("--" not in line for line in lines), lines
