"""The dimensional preference learner (F29/F30).

These tests pin the product claim the module exists to satisfy: "too far" must teach something
different from "just not today". They never touch `learning.py`'s per-candidate posterior --
that is a deliberately separate axis of evidence, exercised in `test_learning_weights.py`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from silverloop.local_time import at_local
from silverloop.models import (
    ActivityCandidate,
    ActivityIntensity,
    ActivityLocation,
    ActivityPreferences,
    ActivitySource,
    ClarificationScope,
    DeclineReason,
    DimensionPreference,
    Enjoyment,
    IndoorOutdoor,
    IntegrationStatus,
    LikedAspect,
    PreferenceDimension,
    SocialPreference,
)
from silverloop.ontology import ActivityType
from silverloop.preferences import (
    DECLINE_REASON_DIMENSIONS,
    DEFAULT_TRAVEL_TOLERANCE_M,
    LIKED_ASPECT_DIMENSIONS,
    SourceTier,
    apply_decline,
    apply_enjoyment,
    describe_preference,
    dimension_score,
    preference_utility,
    resolve,
    social_shape_score,
    travel_tolerance_m,
)

NOW = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)


def _candidate(**overrides: object) -> ActivityCandidate:
    defaults: dict[str, object] = dict(
        activity_id="act-1",
        source=ActivitySource.AAC_FIXTURE,
        integration_status=IntegrationStatus.FIXTURE,
        title="Morning tai chi",
        provider="Community Centre",
        location=ActivityLocation(name="Community Centre"),
        category="Group class",
        activity_type=ActivityType.TAI_CHI,
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        intensity=ActivityIntensity.MODERATE,
        retrieved_at=NOW,
        distance_m=500,
        start_at=datetime(2026, 9, 7, 9, 0, tzinfo=UTC),
    )
    defaults.update(overrides)
    return ActivityCandidate(**defaults)


# ── "Just not today" moves nothing ────────────────────────────────────────────────────────────


def test_bad_day_maps_to_no_dimension_and_moves_nothing() -> None:
    assert DECLINE_REASON_DIMENSIONS[DeclineReason.BAD_DAY] is None
    result = apply_decline([], DeclineReason.BAD_DAY, _candidate(), NOW)
    assert result == []


def test_already_active_moves_nothing() -> None:
    assert DECLINE_REASON_DIMENSIONS[DeclineReason.ALREADY_ACTIVE] is None
    result = apply_decline([], DeclineReason.ALREADY_ACTIVE, _candidate(), NOW)
    assert result == []


def test_no_reason_given_moves_nothing() -> None:
    assert apply_decline([], None, _candidate(), NOW) == []


def test_no_candidate_moves_nothing_even_with_a_dimensional_reason() -> None:
    assert apply_decline([], DeclineReason.TOO_FAR, None, NOW) == []


# ── "Too far" teaches something a per-candidate posterior cannot ─────────────────────────────


def test_too_far_records_a_ceiling_in_metres_rather_than_a_bucket() -> None:
    """A-F2/B-F2/D-§3. "Too far" at 5 km used to be stored as the bucket the listing fell in, and
    at 1.2 km that bucket was `near` -- so the system learned to avoid activities *near home* from
    someone who had simply named a distance. The number the person's own answer put a line at is
    the fact; the bucket was an artefact of where an arbitrary 2 km threshold happened to fall."""
    far_candidate = _candidate(activity_id="act-far", distance_m=5_000)
    updated = apply_decline([], DeclineReason.TOO_FAR, far_candidate, NOW)

    assert len(updated) == 1
    preference = updated[0]
    assert preference.dimension is PreferenceDimension.DISTANCE
    assert preference.pivot == 5_000
    assert preference.direction == "lower"
    assert preference.source == "decline_reason"
    assert preference.observations == 1

    # The whole point: it transfers to a *different*, never-before-offered listing, as a ceiling --
    # and a ceiling above the default narrows nothing. "5 km was too far" is not permission to
    # charge nothing for 4 km; only a floor the person's own enjoyment put there can raise this.
    assert travel_tolerance_m(resolve(updated)) == DEFAULT_TRAVEL_TOLERANCE_M
    far_floor = apply_enjoyment(
        [], Enjoyment.ENJOYED, [LikedAspect.LOCATION], _candidate(distance_m=8_000), NOW
    )
    assert travel_tolerance_m(resolve(far_floor)) == 8_000
    assert travel_tolerance_m(resolve(far_floor + updated)) == 5_000


def test_too_far_on_a_listing_with_no_distance_records_nothing() -> None:
    """The write-side fallback is gone. It used to record `far` regardless, which is a number
    nobody said about a listing that does not carry one."""
    assert apply_decline([], DeclineReason.TOO_FAR, _candidate(distance_m=None), NOW) == []


def test_one_decline_is_weak_evidence() -> None:
    """A single decline must not read as a confident, near-certain preference -- and its tier
    must say so too, whatever the magnitude works out at."""
    updated = apply_decline([], DeclineReason.TOO_FAR, _candidate(distance_m=5_000), NOW)
    assert 0 < abs(updated[0].strength) < 0.5
    assert resolve(updated)[0].tier is SourceTier.WEAK_LEARNED


def test_repeated_declines_strengthen_but_never_reach_certainty() -> None:
    preferences: list[DimensionPreference] = []
    for _ in range(20):
        preferences = apply_decline(
            preferences, DeclineReason.TOO_FAR, _candidate(distance_m=5_000), NOW
        )
    assert len(preferences) == 1
    assert preferences[0].observations == 20
    assert 0.5 < abs(preferences[0].strength) < 1.0
    assert resolve(preferences)[0].tier is SourceTier.STRONG_LEARNED


def test_too_tiring_records_a_rung_on_the_intensity_ladder() -> None:
    tiring = _candidate(intensity=ActivityIntensity.MODERATE)
    updated = apply_decline([], DeclineReason.TOO_TIRING, tiring, NOW)
    assert len(updated) == 1
    assert updated[0].dimension is PreferenceDimension.INTENSITY
    assert updated[0].pivot == 1  # the rung MODERATE sits on
    assert updated[0].direction == "lower"


def test_too_tiring_on_a_listing_with_no_intensity_records_nothing() -> None:
    """A-F3/§6.N3. `_declined_value` used to return `ActivityIntensity.MODERATE` for a listing
    that carries no intensity -- the only place the write side invented a catalogue fact. Every
    outreach "too tiring" therefore wrote a belief the candidate resolver's own contract promised
    it could not write, and one that contradicted the listing it was derived from."""
    assert apply_decline([], DeclineReason.TOO_TIRING, _candidate(intensity=None), NOW) == []


def test_too_tiring_on_a_light_listing_never_promotes_a_moderate_one() -> None:
    """A-F3/B-F1. The ordinal reading: "that was too tiring" is a statement about where the line
    is, so nothing at or above the line can come out ahead of something below it."""
    updated = apply_decline(
        [], DeclineReason.TOO_TIRING, _candidate(intensity=ActivityIntensity.LIGHT), NOW
    )
    resolved = resolve(updated)
    light, _, _ = preference_utility(_candidate(intensity=ActivityIntensity.LIGHT), resolved)
    moderate, _, _ = preference_utility(_candidate(intensity=ActivityIntensity.MODERATE), resolved)
    assert moderate <= light


def test_one_bad_timing_teaches_no_dimension_and_two_on_the_same_slot_do() -> None:
    """A-F5/D-§6. One "bad timing" is about the session in front of the person -- the 14-day
    cooldown already holds that listing back -- and reading it as a statement about mornings is
    how someone who could not make one Tuesday class stopped being shown mornings at all."""
    morning = _candidate(start_at=at_local(date(2026, 9, 7), 8, 0))
    once = apply_decline([], DeclineReason.BAD_TIMING, morning, NOW)
    assert once[0].dimension is PreferenceDimension.TIMING
    assert resolve(once) == []

    twice = apply_decline(once, DeclineReason.BAD_TIMING, morning, NOW)
    assert [p.dimension for p in resolve(twice)] == [PreferenceDimension.TIMING]


def test_a_timing_clarification_generalises_a_single_answer() -> None:
    """The chip is the person widening it themselves, and is the only thing that does so before a
    second answer agrees. Always optional, always skippable."""
    from silverloop.models import ClarificationScope

    morning = _candidate(start_at=at_local(date(2026, 9, 7), 8, 0))
    clarified = apply_decline(
        [],
        DeclineReason.BAD_TIMING,
        morning,
        NOW,
        clarification=ClarificationScope.TIME_OF_DAY,
    )
    assert [p.dimension for p in resolve(clarified)] == [PreferenceDimension.TIMING]


def test_bad_timing_moves_timing_using_the_candidates_own_slot() -> None:
    # Local wall-clock: 08:00 written as UTC is 4pm in Singapore, so this used to assert a
    # "morning" slot for an afternoon class.
    morning = _candidate(start_at=at_local(date(2026, 9, 7), 8, 0))
    updated = apply_decline([], DeclineReason.BAD_TIMING, morning, NOW)
    assert updated[0].dimension is PreferenceDimension.TIMING
    assert updated[0].value == "morning"


def test_not_for_me_uses_the_candidates_own_activity_type() -> None:
    """A-F4/B-F8/C-C3. It used to write `CATEGORY`, which holds a format label, so a "not for me"
    on a morning walk taught a dislike of every other "Group class" in the catalogue."""
    knitting = _candidate(activity_type=ActivityType.ARTS_CRAFTS, category="Group class")
    updated = apply_decline([], DeclineReason.NOT_FOR_ME, knitting, NOW)
    assert updated[0].dimension is PreferenceDimension.ACTIVITY_TYPE
    assert updated[0].value == ActivityType.ARTS_CRAFTS.value


def test_not_for_me_on_a_walk_leaves_an_unrelated_kind_untouched() -> None:
    """The consequence, stated as the behaviour a person would notice: turning down a walk says
    nothing whatever about tai chi, and must not quietly endorse it either.

    Widened with the type chip: an unclarified "not for me" is held back until a second agreeing
    answer (D7), and this is about what a *resolved* dislike of walks reaches."""
    from silverloop.models import ClarificationScope

    walk = _candidate(activity_type=ActivityType.WALKING)
    resolved = resolve(
        apply_decline(
            [],
            DeclineReason.NOT_FOR_ME,
            walk,
            NOW,
            clarification=ClarificationScope.THIS_ACTIVITY_TYPE,
        )
    )
    assert [p.value for p in resolved] == [ActivityType.WALKING.value]
    another_walk, _, _ = preference_utility(
        _candidate(activity_id="other-walk", activity_type=ActivityType.WALKING), resolved
    )
    tai_chi, coverage, matched = preference_utility(
        _candidate(activity_id="tai-chi", activity_type=ActivityType.TAI_CHI), resolved
    )
    assert another_walk < 0
    assert tai_chi == 0.0
    assert (coverage, matched) == (0.0, 0)


def test_not_for_me_records_nothing_when_the_listing_is_unlabelled() -> None:
    """No type, nothing honest to generalise from.

    A placeholder value would collide with every other unlabelled activity, so one decline of an
    unlabelled session would quietly teach a dislike of all of them.
    """
    assert apply_decline([], DeclineReason.NOT_FOR_ME, _candidate(activity_type=None), NOW) == []


def test_this_one_only_keeps_a_not_for_me_item_level() -> None:
    """The other chip. "Just this one" is a statement about the listing, and the cooldown already
    holds it back; nothing about a kind of activity was said."""
    from silverloop.models import ClarificationScope

    walk = _candidate(activity_type=ActivityType.WALKING)
    assert (
        apply_decline(
            [],
            DeclineReason.NOT_FOR_ME,
            walk,
            NOW,
            clarification=ClarificationScope.THIS_ONE,
        )
        == []
    )


def test_prefer_something_else_teaches_no_dimension_at_all() -> None:
    """Asking to see alternatives is not a statement about any axis.

    It was briefly mapped to SOCIAL, which would have meant that asking for a different option
    taught Care+ something about whether the person wants company. Fifty repetitions must
    still produce nothing.
    """
    preferences: list[DimensionPreference] = []
    for _ in range(50):
        preferences = apply_decline(
            preferences, DeclineReason.PREFER_SOMETHING_ELSE, _candidate(), NOW
        )
    assert preferences == []


def test_different_values_for_the_same_dimension_are_tracked_separately() -> None:
    preferences = apply_decline([], DeclineReason.TOO_FAR, _candidate(distance_m=5_000), NOW)
    preferences = apply_decline(
        preferences,
        DeclineReason.BAD_TIMING,
        _candidate(start_at=datetime(2026, 9, 7, 19, 0, tzinfo=UTC)),
        NOW,
    )
    assert len(preferences) == 2
    dimensions = {preference.dimension for preference in preferences}
    assert dimensions == {PreferenceDimension.DISTANCE, PreferenceDimension.TIMING}


# ── No double-counting ─────────────────────────────────────────────────────────────────────────


def test_apply_decline_never_mutates_the_input_list() -> None:
    original: list[DimensionPreference] = []
    apply_decline(original, DeclineReason.TOO_FAR, _candidate(distance_m=5_000), NOW)
    assert original == []


# ── Source ranking: a senior's own words outrank an inferred tap pattern ─────────────────────


def test_senior_statement_outweighs_decline_reason_in_scoring() -> None:
    candidate = _candidate(indoor_outdoor=IndoorOutdoor.OUTDOOR)
    contradictory = ActivityPreferences(
        person_id="p1",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.ENVIRONMENT,
                value="outdoor",
                strength=-0.9,
                source="decline_reason",
                confirmed=False,
                observations=10,
                updated_at=NOW,
            ),
            DimensionPreference(
                dimension=PreferenceDimension.ENVIRONMENT,
                value="outdoor",
                strength=0.9,
                source="senior_statement",
                confirmed=True,
                observations=1,
                updated_at=NOW,
            ),
        ],
    )
    score = dimension_score(candidate, contradictory)
    # The senior's own statement ("I like being outside") must win outright against the
    # merely-inferred decline pattern, so the net score must land positive.
    assert score > 0


def test_dimension_score_never_returns_a_decision_type() -> None:
    score = dimension_score(_candidate(), ActivityPreferences(person_id="p1", dimensions=[]))
    assert isinstance(score, float)
    assert score == 0.0


def test_dimension_score_ignores_a_dimension_the_candidate_cannot_confirm() -> None:
    """A SOCIAL preference never moves a score against a candidate whose `social_shape` is unset
    -- `_candidate()`'s default -- the same honest-ignorance rule every axis follows.
    """
    social_preference = ActivityPreferences(
        person_id="p1",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.SOCIAL,
                value="unspecified",
                strength=-0.9,
                source="decline_reason",
                confirmed=False,
                observations=5,
                updated_at=NOW,
            )
        ],
    )
    assert dimension_score(_candidate(), social_preference) == 0.0


def test_dimension_score_moves_for_a_social_preference_the_candidate_can_confirm() -> None:
    """The candidate-side half of the ranking loop: once `social_shape` is actually populated, a
    matching SOCIAL preference is no longer skipped.
    """
    social_candidate = _candidate(social_shape=SocialPreference.SOCIAL)
    social_preference = ActivityPreferences(
        person_id="p1",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.SOCIAL,
                value=SocialPreference.SOCIAL.value,
                strength=0.9,
                source="senior_statement",
                confirmed=True,
                observations=1,
                updated_at=NOW,
            )
        ],
    )
    assert dimension_score(social_candidate, social_preference) > 0.0


def test_dimension_score_matches_environment_via_indoor_outdoor_never_category() -> None:
    """Pins the reconciled ENVIRONMENT definition (`preferences._environment_value`) that
    `activity_search._preference_reason` now reads through the same helper: a candidate's
    free-text `category` must never stand in for its `indoor_outdoor` when judging this axis, even
    when the two values happen to collide.
    """
    environment_preference = ActivityPreferences(
        person_id="p1",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.ENVIRONMENT,
                value="indoor",
                strength=0.7,
                source="senior_statement",
                confirmed=True,
                observations=1,
                updated_at=NOW,
            )
        ],
    )
    category_collides = _candidate(category="indoor", indoor_outdoor=IndoorOutdoor.OUTDOOR)
    # The free-text badge colliding with the axis value must not make this a match. An outdoor
    # listing genuinely contradicts a stated preference for indoors, and says so.
    assert dimension_score(category_collides, environment_preference) < 0.0

    genuinely_indoors = _candidate(category="Group class", indoor_outdoor=IndoorOutdoor.INDOOR)
    assert dimension_score(genuinely_indoors, environment_preference) > 0.0


def test_dimension_score_skips_an_axis_the_listing_cannot_answer() -> None:
    """Honest ignorance rather than a fabricated match, on every axis. A listing that does not
    say what kind of thing it is cannot confirm or contradict a belief about kinds of thing."""
    unlabelled = _candidate(activity_type=None)
    preferences = ActivityPreferences(
        person_id="p1",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.ACTIVITY_TYPE,
                value=ActivityType.WALKING.value,
                strength=-0.9,
                source="senior_statement",
                confirmed=True,
                observations=5,
                updated_at=NOW,
            )
        ],
    )
    assert dimension_score(unlabelled, preferences) == 0.0


# ── social_shape_score: the same SOCIAL axis, for candidates that are not ActivityCandidates ──
#
# `sql_repository.InterventionCandidate` (a gentle nudge or a programme suggestion) is not an
# `ActivityCandidate` and never becomes one, but it does carry its own real `social_shape` -- the
# same field `guardrails.validate_proposal` checks for grounding, for a different reason (ranking
# rather than rejection). These pin that it reuses `dimension_score`'s exact weighting rather than
# a second, looser copy of it.


def test_social_shape_score_is_zero_with_no_matching_preference() -> None:
    preferences = ActivityPreferences(person_id="p1", dimensions=[])
    assert social_shape_score(SocialPreference.SOLO, preferences) == 0.0


def test_social_shape_score_is_zero_for_an_unconfirmed_social_shape() -> None:
    """`EITHER` means the listing does not say -- there is nothing here to match against, exactly
    like `dimension_score` skipping a candidate whose `social_shape` is unset.
    """
    preferences = ActivityPreferences(
        person_id="p1",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.SOCIAL,
                value=SocialPreference.SOLO.value,
                strength=0.8,
                source="senior_statement",
                confirmed=True,
                observations=3,
                updated_at=NOW,
            )
        ],
    )
    assert social_shape_score(SocialPreference.EITHER, preferences) == 0.0
    assert social_shape_score(None, preferences) == 0.0


def test_social_shape_score_moves_for_a_matching_preference() -> None:
    preferences = ActivityPreferences(
        person_id="p1",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.SOCIAL,
                value=SocialPreference.SOLO.value,
                strength=0.8,
                source="senior_statement",
                confirmed=True,
                observations=3,
                updated_at=NOW,
            )
        ],
    )
    assert social_shape_score(SocialPreference.SOLO, preferences) > 0.0
    # A group session genuinely contradicts a stated preference for doing things alone, and now
    # says so: SOCIAL and SOLO are a closed pair, so "not the one" *is* "the other".
    assert social_shape_score(SocialPreference.SOCIAL, preferences) < 0.0


def test_social_shape_score_matches_dimension_score_on_the_same_evidence() -> None:
    """Not a coincidental agreement -- both call the same private weighting helper, so a future
    change to `_SOURCE_WEIGHT` or the smoothing curve can never move one without the other.
    """
    preferences = ActivityPreferences(
        person_id="p1",
        dimensions=[
            DimensionPreference(
                dimension=PreferenceDimension.SOCIAL,
                value=SocialPreference.SOCIAL.value,
                strength=0.6,
                source="decline_reason",
                confirmed=False,
                observations=2,
                updated_at=NOW,
            )
        ],
    )
    social_candidate = _candidate(social_shape=SocialPreference.SOCIAL, activity_type=None)
    assert social_shape_score(SocialPreference.SOCIAL, preferences) == dimension_score(
        social_candidate, preferences
    )


def test_social_shape_score_stays_inside_the_bound_adr_0005_rests_on() -> None:
    """§6.N7. `sql_repository`'s argument that a social nudge cannot outvote a single real
    acceptance rests explicitly on this being in [-1, 1], and on that coming from a Pydantic
    bound rather than from arithmetic nobody re-checks. `ResolvedPreference.strength` is
    `Field(ge=-1, le=1)`, and this returns it unmodified."""
    from silverloop.models import ResolvedPreference

    assert ResolvedPreference.model_fields["strength"].metadata[0].ge == -1
    assert ResolvedPreference.model_fields["strength"].metadata[1].le == 1
    for observations in (1, 5, 50, 500):
        preferences = ActivityPreferences(
            person_id="p1",
            dimensions=[
                DimensionPreference(
                    dimension=PreferenceDimension.SOCIAL,
                    value=SocialPreference.SOCIAL.value,
                    strength=1.0,
                    source="senior_statement",
                    confirmed=True,
                    observations=observations,
                    updated_at=NOW,
                )
            ],
        )
        assert -1.0 <= social_shape_score(SocialPreference.SOCIAL, preferences) <= 1.0


# ── describe_preference ───────────────────────────────────────────────────────────────────────


def test_describe_preference_names_the_dimension_value_and_confidence() -> None:
    preference = DimensionPreference(
        dimension=PreferenceDimension.DISTANCE,
        value="far",
        strength=-0.6,
        source="decline_reason",
        confirmed=False,
        observations=3,
        updated_at=NOW,
    )
    text = describe_preference(preference)
    assert "distance" in text
    assert "far" in text
    assert "avoid" in text
    assert "3 observations" in text


def test_describe_preference_flags_a_confirmed_senior_statement() -> None:
    preference = DimensionPreference(
        dimension=PreferenceDimension.SOCIAL,
        value="group",
        strength=0.8,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
    )
    text = describe_preference(preference)
    assert "prefer" in text
    assert "confirmed" in text


def test_a_decline_never_teaches_an_axis_it_said_nothing_about() -> None:
    """The table maps a reason to a dimension only where the reason genuinely implies it.

    An earlier version filled every `PreferenceDimension` from some decline reason, which reads
    tidy and is wrong: it mapped "not for me" onto ENVIRONMENT and "prefer something else" onto
    SOCIAL, so declining a gardening session would have taught Care+ that the person dislikes
    being outdoors, and asking to see alternatives would have taught it something about whether
    they want company. Neither was said. Coverage is not a property worth having here.
    """
    assert DECLINE_REASON_DIMENSIONS[DeclineReason.NOT_FOR_ME] is PreferenceDimension.ACTIVITY_TYPE
    assert DECLINE_REASON_DIMENSIONS[DeclineReason.PREFER_SOMETHING_ELSE] is None
    # SOCIAL is reachable only from a senior's own words, never inferred from a refusal.
    assert PreferenceDimension.SOCIAL not in set(DECLINE_REASON_DIMENSIONS.values())
    # Every reason is accounted for, so a new one cannot be silently ignored.
    assert set(DECLINE_REASON_DIMENSIONS) == set(DeclineReason)


# ── Enjoyment teaches what to repeat, from the other side of the same axis ───────────────────


def test_liked_aspects_map_onto_the_documented_dimensions() -> None:
    assert LIKED_ASPECT_DIMENSIONS[LikedAspect.PEOPLE] is PreferenceDimension.SOCIAL
    assert LIKED_ASPECT_DIMENSIONS[LikedAspect.LOCATION] is PreferenceDimension.DISTANCE
    assert LIKED_ASPECT_DIMENSIONS[LikedAspect.TIMING] is PreferenceDimension.TIMING
    assert LIKED_ASPECT_DIMENSIONS[LikedAspect.ACTIVITY] is PreferenceDimension.ACTIVITY_TYPE
    assert set(LIKED_ASPECT_DIMENSIONS) == set(LikedAspect)


def test_no_liked_aspects_moves_nothing() -> None:
    assert apply_enjoyment([], Enjoyment.ENJOYED, [], _candidate(), NOW) == []


def test_no_candidate_moves_nothing_even_with_liked_aspects() -> None:
    assert apply_enjoyment([], Enjoyment.ENJOYED, [LikedAspect.PEOPLE], None, NOW) == []


def test_liked_the_people_reads_the_listings_own_company() -> None:
    social = _candidate(social_shape=SocialPreference.SOCIAL)
    updated = apply_enjoyment([], Enjoyment.ENJOYED, [LikedAspect.PEOPLE], social, NOW)
    assert len(updated) == 1
    preference = updated[0]
    assert preference.dimension is PreferenceDimension.SOCIAL
    assert preference.value == "social"
    assert preference.strength > 0
    assert preference.source == "inferred"


def test_liked_the_people_records_nothing_when_the_listing_does_not_say() -> None:
    """The last write-side fallback, and the one with the worst reading. It asserted `social`
    regardless of what the listing said, so a person was told Care+ had learned they prefer
    activities with other people from a session that never said whether it had any."""
    assert (
        apply_enjoyment(
            [], Enjoyment.ENJOYED, [LikedAspect.PEOPLE], _candidate(social_shape=None), NOW
        )
        == []
    )


def test_liked_the_location_records_the_distance_that_was_fine() -> None:
    far = _candidate(distance_m=5_000)
    updated = apply_enjoyment([], Enjoyment.ENJOYED, [LikedAspect.LOCATION], far, NOW)
    assert updated[0].dimension is PreferenceDimension.DISTANCE
    assert updated[0].pivot == 5_000
    assert updated[0].direction == "higher"
    assert updated[0].strength > 0


def test_an_enjoyed_distance_never_loosens_a_ceiling_the_person_stated() -> None:
    """Enjoying a trip this far says it was fine. It is not permission to go further still, and
    it must never raise a limit the person's own "too far" put there."""
    declined = apply_decline([], DeclineReason.TOO_FAR, _candidate(distance_m=1_200), NOW)
    both = apply_enjoyment(
        declined, Enjoyment.ENJOYED, [LikedAspect.LOCATION], _candidate(distance_m=5_000), NOW
    )
    assert travel_tolerance_m(resolve(both)) == 1_200


def test_liked_the_location_records_nothing_when_distance_is_unknown() -> None:
    unknown = _candidate(distance_m=None)
    assert apply_enjoyment([], Enjoyment.ENJOYED, [LikedAspect.LOCATION], unknown, NOW) == []


def test_liked_the_timing_uses_the_candidates_own_slot() -> None:
    morning = _candidate(start_at=at_local(date(2026, 9, 7), 8, 0))
    updated = apply_enjoyment([], Enjoyment.ENJOYED, [LikedAspect.TIMING], morning, NOW)
    assert updated[0].dimension is PreferenceDimension.TIMING
    assert updated[0].value == "morning"


def test_liked_the_activity_uses_the_candidates_own_activity_type() -> None:
    knitting = _candidate(activity_type=ActivityType.ARTS_CRAFTS)
    updated = apply_enjoyment([], Enjoyment.ENJOYED, [LikedAspect.ACTIVITY], knitting, NOW)
    assert updated[0].dimension is PreferenceDimension.ACTIVITY_TYPE
    assert updated[0].value == ActivityType.ARTS_CRAFTS.value


def test_liked_the_activity_records_nothing_without_a_type() -> None:
    unlabelled = _candidate(activity_type=None)
    assert apply_enjoyment([], Enjoyment.ENJOYED, [LikedAspect.ACTIVITY], unlabelled, NOW) == []


def test_multiple_liked_aspects_in_one_report_move_multiple_dimensions() -> None:
    updated = apply_enjoyment(
        [],
        Enjoyment.ENJOYED,
        [LikedAspect.PEOPLE, LikedAspect.LOCATION],
        _candidate(distance_m=5_000, social_shape=SocialPreference.SOCIAL),
        NOW,
    )
    dimensions = {preference.dimension for preference in updated}
    assert dimensions == {PreferenceDimension.SOCIAL, PreferenceDimension.DISTANCE}


def test_okay_moves_very_little_compared_to_enjoyed() -> None:
    social = _candidate(social_shape=SocialPreference.SOCIAL)
    okay = apply_enjoyment([], Enjoyment.OKAY, [LikedAspect.PEOPLE], social, NOW)
    enjoyed = apply_enjoyment([], Enjoyment.ENJOYED, [LikedAspect.PEOPLE], social, NOW)
    assert 0 < okay[0].strength < enjoyed[0].strength
    assert okay[0].strength <= 0.15


def test_okay_then_enjoyed_and_enjoyed_then_okay_resolve_identically() -> None:
    """D-§7. The two used to share one row whose magnitude was *overwritten* by whichever arrived
    last, so "it was fine" after "I loved it" erased the endorsement while the reverse kept it.
    Counting both sides makes the order irrelevant by construction."""
    social = _candidate(social_shape=SocialPreference.SOCIAL)
    okay_first = apply_enjoyment(
        apply_enjoyment([], Enjoyment.OKAY, [LikedAspect.PEOPLE], social, NOW),
        Enjoyment.ENJOYED,
        [LikedAspect.PEOPLE],
        social,
        NOW,
    )
    enjoyed_first = apply_enjoyment(
        apply_enjoyment([], Enjoyment.ENJOYED, [LikedAspect.PEOPLE], social, NOW),
        Enjoyment.OKAY,
        [LikedAspect.PEOPLE],
        social,
        NOW,
    )
    assert okay_first[0].strength == enjoyed_first[0].strength
    assert okay_first[0].positive_evidence == enjoyed_first[0].positive_evidence


def test_okay_is_always_a_fraction_of_an_enjoyed_report_however_often_it_repeats() -> None:
    """ "It was fine" is not an endorsement and must never read as one.

    It used to be enforced by a *cap* on the magnitude, which had a worse bug inside it: the cap
    was applied by overwriting, so "okay" arriving after "enjoyed" erased the endorsement while
    the same two reports in the other order kept it. What is enforced now is the thing actually
    worth enforcing -- an "okay" is worth a fraction of an "enjoyed", report for report, at every
    count -- and it survives being reported in either order.
    """
    social = _candidate(social_shape=SocialPreference.SOCIAL)
    okay: list[DimensionPreference] = []
    enjoyed: list[DimensionPreference] = []
    for _ in range(50):
        okay = apply_enjoyment(okay, Enjoyment.OKAY, [LikedAspect.PEOPLE], social, NOW)
        enjoyed = apply_enjoyment(enjoyed, Enjoyment.ENJOYED, [LikedAspect.PEOPLE], social, NOW)
        assert len(okay) == 1
        assert okay[0].strength < enjoyed[0].strength
        assert okay[0].positive_evidence <= 0.15 * enjoyed[0].positive_evidence + 1e-9


def test_not_for_me_can_still_teach_a_real_liked_aspect() -> None:
    """A person can dislike the activity as a whole and still name one thing that worked."""
    updated = apply_enjoyment([], Enjoyment.NOT_FOR_ME, [LikedAspect.LOCATION], _candidate(), NOW)
    assert updated[0].strength > 0.15


def test_repeated_enjoyment_strengthens_but_never_reaches_certainty() -> None:
    social = _candidate(social_shape=SocialPreference.SOCIAL)
    preferences: list[DimensionPreference] = []
    for _ in range(20):
        preferences = apply_enjoyment(
            preferences, Enjoyment.ENJOYED, [LikedAspect.PEOPLE], social, NOW
        )
    assert len(preferences) == 1
    assert preferences[0].observations == 20
    assert 0.5 < preferences[0].strength < 1.0


def test_apply_enjoyment_never_mutates_the_input_list() -> None:
    original: list[DimensionPreference] = []
    apply_enjoyment(
        original,
        Enjoyment.ENJOYED,
        [LikedAspect.PEOPLE],
        _candidate(social_shape=SocialPreference.SOCIAL),
        NOW,
    )
    assert original == []


def test_enjoyment_evidence_never_overwrites_a_declines_accumulated_history() -> None:
    """A decline and an enjoyment can name the same (dimension, value) from opposite directions;
    neither may reset the other's accumulated evidence -- see the module comment on why enjoyment
    uses its own source tier.
    """
    far = _candidate(distance_m=5_000)
    declined = apply_decline([], DeclineReason.TOO_FAR, far, NOW)
    both = apply_enjoyment(declined, Enjoyment.ENJOYED, [LikedAspect.LOCATION], far, NOW)

    assert len(both) == 2
    decline_entry = next(p for p in both if p.source == "decline_reason")
    enjoyment_entry = next(p for p in both if p.source == "inferred")
    assert decline_entry.direction == "lower"
    assert decline_entry.observations == 1
    assert enjoyment_entry.direction == "higher"
    assert enjoyment_entry.observations == 1


# ── Precedence: the person's own statement supersedes what was inferred ───────────────────────


def _pref(source: str, strength: float, **overrides: object) -> DimensionPreference:
    base: dict[str, object] = dict(
        dimension=PreferenceDimension.ENVIRONMENT,
        value="outdoor",
        strength=strength,
        source=source,
        confirmed=source == "senior_statement",
        observations=3,
        updated_at=NOW,
    )
    base.update(overrides)
    return DimensionPreference(**base)  # type: ignore[arg-type]


def test_a_stated_preference_supersedes_inferred_rows_on_the_same_dimension() -> None:
    """Averaging used to halve a person's own words with what the system had guessed: stated
    +1.0 beside a learned -0.67 came out at +0.43. Now the statement is the whole answer."""
    outdoors = _candidate(indoor_outdoor=IndoorOutdoor.OUTDOOR, activity_type=None)
    stated_only = ActivityPreferences(person_id="p1", dimensions=[_pref("senior_statement", 1.0)])
    contradicted = ActivityPreferences(
        person_id="p1",
        dimensions=[_pref("senior_statement", 1.0), _pref("decline_reason", -0.67)],
    )
    assert dimension_score(outdoors, contradicted) == dimension_score(outdoors, stated_only) == 1.0


def test_a_higher_tier_supersedes_rather_than_averages_on_the_same_axis() -> None:
    """Generalised from "stated beats inferred" to "the highest active tier wins the axis".

    Three agreeing declines are `STRONG_LEARNED`; one enjoyment is `WEAK_LEARNED`. They used to be
    blended by a per-source weight -- a table built to rank evidence *classes within* one axis,
    used as a mixer -- so what the person had said most often was diluted by what they had said
    once. The stronger tier is now the whole contribution, and the weaker one is shown as a
    contradiction instead of scored.
    """
    outdoors = _candidate(indoor_outdoor=IndoorOutdoor.OUTDOOR, activity_type=None)
    strong = _pref("decline_reason", -0.5, observations=3)
    weak = _pref("inferred", 0.5, observations=1)
    mixed = ActivityPreferences(person_id="p1", dimensions=[strong, weak])
    resolved = resolve(mixed.dimensions)
    winner = next(p for p in resolved if p.tier == p.winning_tier)
    assert winner.tier is SourceTier.STRONG_LEARNED
    assert winner.source == "decline_reason"
    assert dimension_score(outdoors, mixed) < 0.0
    # The losing belief is shown, never scored.
    loser = next(p for p in resolved if p.tier != p.winning_tier)
    assert loser.contradicted_by


def test_a_statement_on_one_dimension_never_silences_inferences_on_another() -> None:
    outdoor_social = _candidate(
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        social_shape=SocialPreference.SOCIAL,
        activity_type=None,
    )
    prefs = ActivityPreferences(
        person_id="p1",
        dimensions=[
            _pref("senior_statement", 1.0),
            _pref("decline_reason", -1.0, dimension=PreferenceDimension.SOCIAL, value="social"),
        ],
    )
    assert 0.0 < dimension_score(outdoor_social, prefs) < 1.0


# ── The denominator: match-any must stop looking like match-all ───────────────────────────────


def _stated(dimension: PreferenceDimension, value: str) -> DimensionPreference:
    return DimensionPreference(
        dimension=dimension,
        value=value,
        strength=1.0,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
    )


def test_three_confirmed_likes_outscore_one_confirmed_like() -> None:
    """A-F1/B-F7, the averaging defect. The old score summed *matched rows only* and divided by
    their own weights, so the denominator grew with the numerator: a listing matching one of three
    stated likes scored exactly what a listing matching all three scored, and three of a person's
    own confirmed statements were a constant offset that changed no order at all."""
    likes = [
        _stated(PreferenceDimension.SOCIAL, SocialPreference.SOCIAL.value),
        _stated(PreferenceDimension.ENVIRONMENT, "indoor"),
        _stated(PreferenceDimension.ACTIVITY_TYPE, ActivityType.TAI_CHI.value),
    ]
    resolved = resolve(likes)
    all_three, _, matched_all = preference_utility(
        _candidate(
            social_shape=SocialPreference.SOCIAL,
            indoor_outdoor=IndoorOutdoor.INDOOR,
            activity_type=ActivityType.TAI_CHI,
        ),
        resolved,
    )
    one_only, _, matched_one = preference_utility(
        _candidate(
            social_shape=SocialPreference.SOLO,
            indoor_outdoor=IndoorOutdoor.OUTDOOR,
            activity_type=ActivityType.TAI_CHI,
        ),
        resolved,
    )
    assert all_three > one_only
    assert (matched_all, matched_one) == (3, 1)


def test_an_avoid_on_one_axis_is_not_cancelled_by_a_like_on_another() -> None:
    """The other half of the same defect. A like and an avoid used to sum to exactly 0.0, which
    the breakdown then reported as "Nothing learned applies to this listing." -- the one number
    that cannot tell "nothing known" from "two things that disagree"."""
    resolved = resolve(
        [
            _stated(PreferenceDimension.SOCIAL, SocialPreference.SOCIAL.value),
            DimensionPreference(
                dimension=PreferenceDimension.ACTIVITY_TYPE,
                value=ActivityType.WALKING.value,
                strength=-1.0,
                source="senior_statement",
                confirmed=True,
                observations=1,
                updated_at=NOW,
            ),
        ]
    )
    like_only, like_coverage, _ = preference_utility(
        _candidate(social_shape=SocialPreference.SOCIAL, activity_type=None), resolved
    )
    both, both_coverage, both_matched = preference_utility(
        _candidate(social_shape=SocialPreference.SOCIAL, activity_type=ActivityType.WALKING),
        resolved,
    )
    assert like_only > both
    # And the disagreement is visible rather than reading as "nothing known".
    assert both_coverage > like_coverage
    assert both_matched == 2


def test_stating_the_same_preference_twice_is_one_piece_of_evidence() -> None:
    """A-F1. A person saying one thing three times is one person saying it. The world model
    reports `evidence_count` from this, so counting repeats overstated what is actually known."""
    resolved = resolve([_stated(PreferenceDimension.ENVIRONMENT, "indoor")])
    assert resolved[0].evidence_count == 1


def test_coverage_is_reported_and_an_unjudgeable_axis_is_excluded_from_both_sides() -> None:
    """§3.11. An axis a listing cannot answer is out of the numerator and out of the denominator,
    and how much of what is known could be judged at all travels separately -- so a sparsely
    described listing cannot out-score a fully described identical one by being unanswerable."""
    resolved = resolve(
        [
            _stated(PreferenceDimension.SOCIAL, SocialPreference.SOCIAL.value),
            _stated(PreferenceDimension.ENVIRONMENT, "indoor"),
        ]
    )
    full, full_coverage, full_matched = preference_utility(
        _candidate(social_shape=SocialPreference.SOCIAL, indoor_outdoor=IndoorOutdoor.INDOOR),
        resolved,
    )
    sparse, sparse_coverage, sparse_matched = preference_utility(
        _candidate(social_shape=SocialPreference.SOCIAL, indoor_outdoor=IndoorOutdoor.UNKNOWN),
        resolved,
    )
    assert full == sparse == 1.0
    assert full_coverage == 1.0 and sparse_coverage == 0.5
    assert full_matched > sparse_matched


def test_no_preference_dimension_is_ever_derived_from_accessibility_tags() -> None:
    """D-§E, safety. Accessibility is never inferred from behaviour: a person turning something
    down is not a statement about what they can do, and a system that read it as one would be
    making a capability judgement nobody asked it to make."""
    tagged = _candidate(accessibility_tags=["wheelchair_accessible", "hearing_loop"])
    for reason in DeclineReason:
        for preference in apply_decline([], reason, tagged, NOW):
            assert preference.value not in tagged.accessibility_tags
            assert preference.dimension is not PreferenceDimension.CATEGORY
    for aspect in LikedAspect:
        for preference in apply_enjoyment([], Enjoyment.ENJOYED, [aspect], tagged, NOW):
            assert preference.value not in tagged.accessibility_tags


# ── D7: an unclarified "not for me" is about the listing until a second answer agrees ────────


def test_one_unclarified_not_for_me_is_recorded_but_held_back() -> None:
    """D7. One "not for me" on a walk is about that walk -- the cooldown already holds it back.
    It used to resolve at once, so a single tap became a standing dislike of every walk, which is
    exactly the reading one "bad timing" is refused. The row is still written (it is the evidence a
    second answer builds on); it just does not rank anything yet."""
    from silverloop.models import ClarificationScope

    walk = _candidate(activity_type=ActivityType.WALKING)
    once = apply_decline([], DeclineReason.NOT_FOR_ME, walk, NOW, origin_id="r1")
    assert len(once) == 1
    assert once[0].dimension is PreferenceDimension.ACTIVITY_TYPE
    assert once[0].value == ActivityType.WALKING.value
    assert once[0].scope is ClarificationScope.THIS_ONE
    assert resolve(once) == []
    another_walk, coverage, matched = preference_utility(
        _candidate(activity_id="other-walk", activity_type=ActivityType.WALKING), resolve(once)
    )
    assert (another_walk, coverage, matched) == (0.0, 0.0, 0)


def test_a_second_agreeing_not_for_me_resolves_the_dislike() -> None:
    walk = _candidate(activity_type=ActivityType.WALKING)
    once = apply_decline([], DeclineReason.NOT_FOR_ME, walk, NOW, origin_id="r1")
    twice = apply_decline(
        once,
        DeclineReason.NOT_FOR_ME,
        _candidate(activity_id="act-2", activity_type=ActivityType.WALKING),
        NOW,
        origin_id="r2",
    )
    resolved = resolve(twice)
    assert [(p.dimension, p.value, p.sentiment) for p in resolved] == [
        (PreferenceDimension.ACTIVITY_TYPE, ActivityType.WALKING.value, "avoid")
    ]
    assert resolved[0].evidence_count == 2
    # A retry of the same tap is one origin, not a second agreeing answer.
    retried = apply_decline(once, DeclineReason.NOT_FOR_ME, walk, NOW, origin_id="r1")
    assert resolve(retried) == []


def test_the_activity_type_chip_widens_a_single_not_for_me_immediately() -> None:
    from silverloop.models import ClarificationScope

    walk = _candidate(activity_type=ActivityType.WALKING)
    clarified = apply_decline(
        [],
        DeclineReason.NOT_FOR_ME,
        walk,
        NOW,
        clarification=ClarificationScope.THIS_ACTIVITY_TYPE,
    )
    assert [p.value for p in resolve(clarified)] == [ActivityType.WALKING.value]
    assert resolve(clarified)[0].evidence_count == 1

    # The scope alone decides it: the same single observation, held back as `this_one` and
    # released as `this_activity_type`, with no second origin anywhere.
    held = apply_decline([], DeclineReason.NOT_FOR_ME, walk, NOW, origin_id="r1")
    assert held[0].negative_evidence == 1.0 and resolve(held) == []
    widened_in_place = [held[0].model_copy(update={"scope": ClarificationScope.THIS_ACTIVITY_TYPE})]
    assert held[0].model_dump(exclude={"scope"}) == widened_in_place[0].model_dump(
        exclude={"scope"}
    )
    released = resolve(widened_in_place)
    assert [(p.value, p.evidence_count) for p in released] == [(ActivityType.WALKING.value, 1)]

    # A retry of the tap that was held back, now with the chip, is still one origin: nothing is
    # folded and nothing widens -- only a new answer can carry the chip.
    retried = apply_decline(
        held,
        DeclineReason.NOT_FOR_ME,
        walk,
        NOW,
        clarification=ClarificationScope.THIS_ACTIVITY_TYPE,
        origin_id="r1",
    )
    assert retried == held and resolve(retried) == []


def test_with_no_programme_given_a_second_origin_on_the_same_listing_still_agrees() -> None:
    """The fallback, documented: a caller that passes no `series` (or cannot trace the row's
    origin to a programme) gets agreement counted by distinct origin alone, as before. Two "not
    for me"s on the very same walk on two days are then two origins and widen the dislike. Every
    production caller passes the programme; see the tests below for the rule that then applies."""
    walk = _candidate(activity_type=ActivityType.WALKING)
    monday = apply_decline([], DeclineReason.NOT_FOR_ME, walk, NOW, origin_id="response-monday")
    assert resolve(monday) == []
    tuesday = apply_decline(
        monday,
        DeclineReason.NOT_FOR_ME,
        walk,
        NOW + timedelta(days=1),
        origin_id="response-tuesday",
    )
    resolved = resolve(tuesday)
    assert [(p.value, p.sentiment, p.evidence_count) for p in resolved] == [
        (ActivityType.WALKING.value, "avoid", 2)
    ]
    assert resolved[0].scope is ClarificationScope.THIS_ONE


# ── A second item-level answer must be about a different programme ──────────────────────────


def _series_of(candidate: ActivityCandidate) -> str:
    from silverloop.activity_search import series_key

    return series_key(candidate)


def _decline(
    rows: list[DimensionPreference],
    reason: DeclineReason,
    candidate: ActivityCandidate,
    origin_id: str,
    origins: dict[str, str],
    *,
    now: datetime = NOW,
    clarification: ClarificationScope | None = None,
) -> list[DimensionPreference]:
    """Fold a decline the way production does: the new origin's programme is known, and so is
    every stored origin's."""
    series = _series_of(candidate)
    result = apply_decline(
        rows,
        reason,
        candidate,
        now,
        clarification=clarification,
        origin_id=origin_id,
        series=series,
        origin_series=origins,
    )
    origins[origin_id] = series
    return result


def _walk_session(activity_id: str, day: int, **overrides: object) -> ActivityCandidate:
    fields: dict[str, object] = {
        "activity_id": activity_id,
        "title": "Park walk",
        "activity_type": ActivityType.WALKING,
        "start_at": at_local(date(2026, 9, day), 8, 0),
    }
    return _candidate(**{**fields, **overrides})


def test_the_same_listing_declined_again_on_another_day_stays_held_back() -> None:
    walk = _walk_session("walk-1", 7)
    origins: dict[str, str] = {}
    monday = _decline([], DeclineReason.NOT_FOR_ME, walk, "response-monday", origins)
    tuesday = _decline(
        monday,
        DeclineReason.NOT_FOR_ME,
        walk,
        "response-tuesday",
        origins,
        now=NOW + timedelta(days=1),
    )
    assert tuesday == monday
    assert resolve(tuesday) == []
    assert tuesday[0].negative_evidence == 1.0 and tuesday[0].origin_id == "response-monday"


def test_a_sibling_session_of_the_same_programme_stays_held_back() -> None:
    origins: dict[str, str] = {}
    monday = _walk_session("walk-mon", 7)
    wednesday = _walk_session("walk-wed", 9)
    assert _series_of(monday) == _series_of(wednesday)
    once = _decline([], DeclineReason.NOT_FOR_ME, monday, "r-mon", origins)
    twice = _decline(once, DeclineReason.NOT_FOR_ME, wednesday, "r-wed", origins)
    assert twice == once and resolve(twice) == []

    # The same rule on TIMING: two sessions of one programme in the same slot are one opinion
    # about that programme's timing, not about mornings.
    timing_once = _decline([], DeclineReason.BAD_TIMING, monday, "t-mon", origins)
    timing_twice = _decline(timing_once, DeclineReason.BAD_TIMING, wednesday, "t-wed", origins)
    assert timing_twice == timing_once and resolve(timing_twice) == []


def test_a_different_programme_of_the_same_kind_or_slot_widens() -> None:
    origins: dict[str, str] = {}
    park = _walk_session("park-walk", 7)
    river = _walk_session("river-walk", 8, title="River walk", provider="Another Centre")
    assert _series_of(park) != _series_of(river)
    once = _decline([], DeclineReason.NOT_FOR_ME, park, "r-park", origins)
    twice = _decline(once, DeclineReason.NOT_FOR_ME, river, "r-river", origins)
    resolved = resolve(twice)
    assert [(p.value, p.sentiment, p.evidence_count) for p in resolved] == [
        (ActivityType.WALKING.value, "avoid", 2)
    ]

    timing_once = _decline([], DeclineReason.BAD_TIMING, park, "t-park", origins)
    timing_twice = _decline(timing_once, DeclineReason.BAD_TIMING, river, "t-river", origins)
    assert [p.dimension for p in resolve(timing_twice)] == [PreferenceDimension.TIMING]


def test_a_widening_chip_on_the_same_programme_still_widens_and_adds_evidence() -> None:
    origins: dict[str, str] = {}
    walk = _walk_session("walk-1", 7)
    held = _decline([], DeclineReason.NOT_FOR_ME, walk, "r1", origins)
    widened = _decline(
        held,
        DeclineReason.NOT_FOR_ME,
        walk,
        "r2",
        origins,
        clarification=ClarificationScope.THIS_ACTIVITY_TYPE,
    )
    assert widened[0].scope is ClarificationScope.THIS_ACTIVITY_TYPE
    assert widened[0].negative_evidence == 2.0
    assert [(p.value, p.evidence_count) for p in resolve(widened)] == [
        (ActivityType.WALKING.value, 2)
    ]

    timing_held = _decline([], DeclineReason.BAD_TIMING, walk, "t1", origins)
    timing_widened = _decline(
        timing_held,
        DeclineReason.BAD_TIMING,
        walk,
        "t2",
        origins,
        clarification=ClarificationScope.TIME_OF_DAY,
    )
    assert timing_widened[0].scope is ClarificationScope.TIME_OF_DAY
    assert timing_widened[0].negative_evidence == 2.0
    assert [p.dimension for p in resolve(timing_widened)] == [PreferenceDimension.TIMING]


def test_an_untraceable_origin_folds_as_before() -> None:
    """No `origin_id` on the stored row (a legacy row), or an origin the caller could not map to
    a programme: the guard cannot tell the two answers apart, so it does not guess they match."""
    walk = _walk_session("walk-1", 7)
    series = _series_of(walk)
    legacy = _type_row(
        ActivityType.WALKING, "decline_reason", -0.333, negative_evidence=1.0, scope=None
    )
    assert legacy.origin_id is None
    folded = apply_decline(
        [legacy],
        DeclineReason.NOT_FOR_ME,
        walk,
        NOW,
        origin_id="r-new",
        series=series,
        origin_series={"r-new": series},
    )
    assert [p.evidence_count for p in resolve(folded)] == [2]

    once = apply_decline([], DeclineReason.NOT_FOR_ME, walk, NOW, origin_id="r-unknown")
    unmapped = apply_decline(
        once,
        DeclineReason.NOT_FOR_ME,
        walk,
        NOW,
        origin_id="r-2",
        series=series,
        origin_series={},
    )
    assert [p.evidence_count for p in resolve(unmapped)] == [2]


def test_a_generalised_belief_gains_nothing_from_repeats_about_its_latest_programme() -> None:
    """Once a belief has generalised, a repeat item-level answer about the programme its latest
    origin names is still one opinion about that programme, so it never counts toward
    `STRONG_LEARNED`. Only the latest origin is stored, so alternating programmes (river, park,
    river) do count -- a documented, bounded approximation."""
    origins: dict[str, str] = {}
    park = _walk_session("park-walk", 7)
    river = _walk_session("river-walk", 8, title="River walk", provider="Another Centre")
    rows = _decline([], DeclineReason.NOT_FOR_ME, park, "r1", origins)
    rows = _decline(rows, DeclineReason.NOT_FOR_ME, river, "r2", origins)
    assert rows[0].negative_evidence == 2.0
    for n, session in enumerate(
        (
            river,
            _walk_session("river-walk-2", 9, title="River walk", provider="Another Centre"),
            river,
        )
    ):
        repeated = _decline(rows, DeclineReason.NOT_FOR_ME, session, f"repeat-{n}", origins)
        assert repeated == rows
    [tier] = {p.tier for p in resolve(rows)}
    assert tier is SourceTier.WEAK_LEARNED

    # The approximation: park after river is a different programme, and river after park is too.
    rows = _decline(rows, DeclineReason.NOT_FOR_ME, park, "r3", origins)
    rows = _decline(rows, DeclineReason.NOT_FOR_ME, river, "r4", origins)
    assert rows[0].negative_evidence == 4.0


def test_the_same_programme_rule_applies_to_a_chip_widened_belief_too() -> None:
    """The rule reads the new answer's scope, not the row's: an unclarified repeat about the
    programme a chip was given on adds nothing to the belief the chip widened."""
    origins: dict[str, str] = {}
    walk = _walk_session("walk-1", 7)
    widened = _decline(
        [],
        DeclineReason.NOT_FOR_ME,
        walk,
        "r1",
        origins,
        clarification=ClarificationScope.THIS_ACTIVITY_TYPE,
    )
    sibling = _walk_session("walk-2", 9)
    assert _decline(widened, DeclineReason.NOT_FOR_ME, sibling, "r2", origins) == widened


def test_a_restarted_row_is_held_back_again_against_its_new_origin() -> None:
    """A retracted row restarts from the next answer, even one about the programme it was last
    about; a further answer about that same programme then leaves it held back."""
    origins: dict[str, str] = {}
    walk = _walk_session("walk-1", 7)
    park = _walk_session("park-walk", 8, title="Park walk two", provider="Another Centre")
    rows = _decline([], DeclineReason.NOT_FOR_ME, walk, "r1", origins)
    rows = _decline(rows, DeclineReason.NOT_FOR_ME, park, "r2", origins)
    assert [p.evidence_count for p in resolve(rows)] == [2]
    retracted = [rows[0].model_copy(update={"superseded_by": "retracted"})]
    assert resolve(retracted) == []

    restarted = _decline(retracted, DeclineReason.NOT_FOR_ME, park, "r3", origins)
    assert restarted[0].superseded_by is None
    assert (restarted[0].negative_evidence, restarted[0].origin_id) == (1.0, "r3")
    assert resolve(restarted) == []

    again = _decline(restarted, DeclineReason.NOT_FOR_ME, park, "r4", origins)
    assert again == restarted and resolve(again) == []


def test_a_legacy_unclarified_activity_type_decline_is_held_back_like_a_new_one() -> None:
    """Rows written before D7 carry `scope=None` for an unclarified "not for me". Read as
    `this_one`, one such tap is held back exactly like a new one; two agreeing observations still
    resolve, and the other sources and axes are untouched."""
    legacy_once = _type_row(
        ActivityType.WALKING, "decline_reason", -0.333, negative_evidence=1.0, scope=None
    )
    assert resolve([legacy_once]) == []
    legacy_twice = _type_row(
        ActivityType.WALKING,
        "decline_reason",
        -0.5,
        negative_evidence=2.0,
        observations=2,
        scope=None,
    )
    assert [p.value for p in resolve([legacy_twice])] == [ActivityType.WALKING.value]
    # A new unclarified tap folded onto a legacy row is the second agreeing answer.
    folded = apply_decline(
        [legacy_once],
        DeclineReason.NOT_FOR_ME,
        _candidate(activity_type=ActivityType.WALKING),
        NOW,
        origin_id="r-new",
    )
    assert [p.evidence_count for p in resolve(folded)] == [2]
    # Not an ACTIVITY_TYPE decline: a one-observation learned like and a ceiling are not held back.
    like = _type_row(ActivityType.WALKING, "inferred", 0.333, positive_evidence=1.0, scope=None)
    assert [p.value for p in resolve([like])] == [ActivityType.WALKING.value]
    too_far = apply_decline([], DeclineReason.TOO_FAR, _candidate(distance_m=300), NOW)
    assert too_far[0].scope is None and len(resolve(too_far)) == 1


def test_item_level_not_for_me_chips_still_teach_nothing() -> None:
    from silverloop.models import ClarificationScope

    walk = _candidate(activity_type=ActivityType.WALKING)
    for chip in (
        ClarificationScope.THIS_ONE,
        ClarificationScope.THIS_VENUE,
        ClarificationScope.THIS_FORMAT,
    ):
        assert apply_decline([], DeclineReason.NOT_FOR_ME, walk, NOW, clarification=chip) == []


def test_a_timing_chip_on_a_not_for_me_does_not_widen_it() -> None:
    """A chip from the other question says nothing about kinds of activity."""
    from silverloop.models import ClarificationScope

    walk = _candidate(activity_type=ActivityType.WALKING)
    for chip in (ClarificationScope.TIME_OF_DAY, ClarificationScope.WEEKDAY):
        recorded = apply_decline([], DeclineReason.NOT_FOR_ME, walk, NOW, clarification=chip)
        assert recorded[0].scope is ClarificationScope.THIS_ONE
        assert resolve(recorded) == []


def test_too_far_and_too_tiring_still_write_a_ceiling_at_once() -> None:
    """The ordinal exception to D7: a line at a number the listing carries, not a guess about a
    kind of activity, so one answer is enough -- and a ceiling only ever narrows."""
    too_far = apply_decline([], DeclineReason.TOO_FAR, _candidate(distance_m=300), NOW)
    assert too_far[0].scope is None
    assert travel_tolerance_m(resolve(too_far)) == 300
    too_tiring = apply_decline(
        [], DeclineReason.TOO_TIRING, _candidate(intensity=ActivityIntensity.MODERATE), NOW
    )
    assert [p.dimension for p in resolve(too_tiring)] == [PreferenceDimension.INTENSITY]


# ── D17: what a tier wins is an axis, or one value on ACTIVITY_TYPE ──────────────────────────


def _type_row(
    value: ActivityType, source: str, strength: float, **overrides: object
) -> DimensionPreference:
    base: dict[str, object] = dict(
        dimension=PreferenceDimension.ACTIVITY_TYPE,
        value=value.value,
        strength=strength,
        source=source,
        confirmed=source == "senior_statement",
        observations=1,
        updated_at=NOW,
    )
    base.update(overrides)
    return DimensionPreference(**base)  # type: ignore[arg-type]


def test_a_temporary_avoid_on_one_kind_never_silences_beliefs_about_other_kinds() -> None:
    """D17. Resolved per axis, "no walks this week" (TEMPORARY_STATED) out-tiered a standing "I
    like arts and crafts" and a learned "not for me" on stretch, so both stopped counting for as
    long as the walk statement lasted -- though neither says anything about walking."""
    today = date(2026, 9, 6)
    temporary = _type_row(
        ActivityType.WALKING,
        "senior_statement",
        -1.0,
        expires_at=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
    )
    stated_like = _type_row(ActivityType.ARTS_CRAFTS, "senior_statement", 1.0)
    # Widened with the type chip: one unclarified "not for me" would be held back (D7).
    learned_avoid = _type_row(
        ActivityType.STRETCH,
        "decline_reason",
        -0.333,
        negative_evidence=1.0,
        scope=ClarificationScope.THIS_ACTIVITY_TYPE,
    )
    resolved = {p.value: p for p in resolve([temporary, stated_like, learned_avoid], today)}
    assert resolved["walking"].tier is SourceTier.TEMPORARY_STATED
    assert resolved["arts_crafts"].tier is SourceTier.STATED
    assert resolved["stretch"].tier is SourceTier.WEAK_LEARNED
    assert all(p.tier == p.winning_tier for p in resolved.values())
    assert all(not p.contradicted_by for p in resolved.values())

    everything = list(resolved.values())
    crafts, _, crafts_matched = preference_utility(
        _candidate(activity_type=ActivityType.ARTS_CRAFTS), everything
    )
    stretch, _, _ = preference_utility(_candidate(activity_type=ActivityType.STRETCH), everything)
    walk, _, _ = preference_utility(_candidate(activity_type=ActivityType.WALKING), everything)
    assert crafts > 0 and crafts_matched == 1
    assert stretch < 0
    assert walk < 0


def test_same_value_beliefs_still_settle_by_tier_and_link_the_loser() -> None:
    """D17. A stated like and a temporary avoid on the *same* kind: only the temporary avoid
    scores, and the two are linked so the person can see and settle the disagreement."""
    today = date(2026, 9, 6)
    stated_like = _type_row(ActivityType.WALKING, "senior_statement", 1.0)
    temporary = _type_row(
        ActivityType.WALKING,
        "senior_statement",
        -1.0,
        expires_at=datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        origin_id=None,
    )
    # The table holds one row per `(dimension, value, source)`, so these two statements never
    # coexist in storage; the resolver is still total over them, and the tier rule is the same.
    resolved = resolve([stated_like, temporary], today)
    winners = [p for p in resolved if p.tier == p.winning_tier]
    losers = [p for p in resolved if p.tier != p.winning_tier]
    assert [(p.tier, p.sentiment) for p in winners] == [(SourceTier.TEMPORARY_STATED, "avoid")]
    assert [(p.tier, p.sentiment) for p in losers] == [(SourceTier.STATED, "like")]
    assert winners[0].contradicted_by and losers[0].contradicted_by
    walk, _, _ = preference_utility(_candidate(activity_type=ActivityType.WALKING), resolved)
    assert walk == -1.0

    # The shape storage can actually hold: a temporary statement over a learned like of the same
    # kind. The loser is named by its own key, so the link is unambiguous.
    learned_like = _type_row(ActivityType.WALKING, "inferred", 0.6, positive_evidence=3.0)
    mixed = {p.source: p for p in resolve([temporary, learned_like], today)}
    assert mixed["senior_statement"].tier == mixed["senior_statement"].winning_tier
    assert mixed["inferred"].tier != mixed["inferred"].winning_tier
    assert mixed["senior_statement"].contradicted_by == ["activity_type:walking:inferred"]
    assert mixed["inferred"].contradicted_by == ["activity_type:walking:senior_statement"]
    walk, _, _ = preference_utility(
        _candidate(activity_type=ActivityType.WALKING), list(mixed.values())
    )
    assert walk == -1.0


def test_equal_tiers_on_the_same_value_both_win_and_cancel() -> None:
    learned_avoid = _type_row(
        ActivityType.WALKING,
        "decline_reason",
        -0.333,
        negative_evidence=1.0,
        scope=ClarificationScope.THIS_ACTIVITY_TYPE,
    )
    learned_like = _type_row(ActivityType.WALKING, "inferred", 0.333, positive_evidence=1.0)
    resolved = resolve([learned_avoid, learned_like])
    assert all(p.tier == p.winning_tier == SourceTier.WEAK_LEARNED for p in resolved)
    assert all(p.contradicted_by for p in resolved)
    walk, _, _ = preference_utility(_candidate(activity_type=ActivityType.WALKING), resolved)
    assert walk == 0.0


def test_the_exclusive_and_ordinal_axes_still_resolve_as_a_whole() -> None:
    """D17's other half, unchanged: on TIMING, ENVIRONMENT, SOCIAL, DISTANCE and INTENSITY one
    value really is an answer about the others, so a stated belief still out-tiers a learned one
    on a *different* value of the same axis."""
    stated_morning = _stated(PreferenceDimension.TIMING, "morning")
    learned_afternoon = DimensionPreference(
        dimension=PreferenceDimension.TIMING,
        value="afternoon",
        strength=-0.5,
        source="decline_reason",
        observations=2,
        negative_evidence=2.0,
        updated_at=NOW,
    )
    resolved = {p.value: p for p in resolve([stated_morning, learned_afternoon])}
    assert resolved["afternoon"].winning_tier is SourceTier.STATED
    assert resolved["afternoon"].tier != resolved["afternoon"].winning_tier

    stated_ceiling = DimensionPreference(
        dimension=PreferenceDimension.DISTANCE,
        value="lower",
        strength=1.0,
        source="senior_statement",
        observations=1,
        pivot=800,
        direction="lower",
        updated_at=NOW,
    )
    learned_floor = DimensionPreference(
        dimension=PreferenceDimension.DISTANCE,
        value="higher",
        strength=0.333,
        source="inferred",
        observations=1,
        positive_evidence=1.0,
        pivot=3_000,
        direction="higher",
        updated_at=NOW,
    )
    distance = {p.value: p for p in resolve([stated_ceiling, learned_floor])}
    assert distance["higher"].winning_tier is SourceTier.STATED
    assert travel_tolerance_m(list(distance.values())) == 500


# ── D20: a goal is keyed apart from a statement on the same value ────────────────────────────


def test_a_goal_and_a_statement_on_the_same_value_have_distinct_keys() -> None:
    from silverloop.models import ActivityGoal, GoalKind

    stated_avoid = DimensionPreference(
        dimension=PreferenceDimension.SOCIAL,
        value=SocialPreference.SOCIAL.value,
        strength=-1.0,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
    )
    goal = ActivityGoal(
        goal_id="goal_1", kind=GoalKind.MEET_PEOPLE, text="Meet people", created_at=NOW
    )
    resolved = resolve([stated_avoid], goals=[goal])
    by_key = {p.supporting[0]: p for p in resolved}
    assert set(by_key) == {"social:social:senior_statement", "goal:social:social"}
    assert by_key["social:social:senior_statement"].contradicted_by == ["goal:social:social"]
    assert by_key["goal:social:social"].contradicted_by == ["social:social:senior_statement"]


# ── A DISTANCE statement with no number caps the comfortable distance, and only narrows ──────


def _distance_statement(value: str, strength: float = 1.0) -> DimensionPreference:
    return DimensionPreference(
        dimension=PreferenceDimension.DISTANCE,
        value=value,
        strength=strength,
        source="senior_statement",
        confirmed=True,
        observations=1,
        updated_at=NOW,
        positive_evidence=1.0 if strength > 0 else 0.0,
        negative_evidence=1.0 if strength < 0 else 0.0,
    )


def _too_far_at(metres: int, origin_id: str = "r1") -> list[DimensionPreference]:
    return apply_decline(
        [], DeclineReason.TOO_FAR, _candidate(distance_m=metres), NOW, origin_id=origin_id
    )


def _floor_at(metres: int) -> list[DimensionPreference]:
    return apply_enjoyment(
        [], Enjoyment.ENJOYED, [LikedAspect.LOCATION], _candidate(distance_m=metres), NOW
    )


def _travel(rows: list[DimensionPreference], goals: list[object] | None = None) -> tuple[int, str]:
    from silverloop.preferences import travel_tolerance_basis

    resolved = resolve(rows, goals=goals or [])  # type: ignore[arg-type]
    return travel_tolerance_m(resolved), travel_tolerance_basis(resolved)


def test_the_nearby_radius_is_the_one_a_near_me_request_asks_for() -> None:
    from silverloop.intent import parse_intent
    from silverloop.preferences import NEARBY_RADIUS_M

    assert NEARBY_RADIUS_M == 1000
    assert parse_intent("something near me", today=NOW.date()).max_distance_m == NEARBY_RADIUS_M


def test_a_stated_near_under_a_learned_ceiling_changes_nothing() -> None:
    # A 2 km floor lifts the default, so the 650 m ceiling is what binds before the statement.
    learned = [*_floor_at(2000), *_too_far_at(650)]
    assert _travel(learned) == (650, "learned_ceiling")
    rows = [_distance_statement("near"), *learned]
    assert _travel(rows) == (650, "learned_ceiling")
    # Separate resolution groups: the statement does not outrank the learned line away.
    resolved = resolve(rows)
    assert all(p.tier == p.winning_tier for p in resolved)


def test_a_stated_near_over_a_learned_floor_brings_the_line_back_to_a_kilometre() -> None:
    rows = [_distance_statement("near"), *_floor_at(2000)]
    assert _travel(_floor_at(2000)) == (2000, "learned_floor")
    assert _travel(rows) == (1000, "stated_near")
    # "Avoid far" is the same request for less travel.
    assert _travel([_distance_statement("far", -1.0), *_floor_at(2000)]) == (1000, "stated_near")


def test_a_stated_near_alone_never_widens_the_default() -> None:
    assert _travel([_distance_statement("near")]) == (DEFAULT_TRAVEL_TOLERANCE_M, "default")


def test_a_stated_far_or_an_avoided_near_never_raises_anything() -> None:
    assert _travel([_distance_statement("far")]) == (DEFAULT_TRAVEL_TOLERANCE_M, "default")
    assert _travel([_distance_statement("near", -1.0)]) == (DEFAULT_TRAVEL_TOLERANCE_M, "default")
    assert _travel([_distance_statement("far"), *_floor_at(2000), *_too_far_at(650)]) == (
        650,
        "learned_ceiling",
    )
    assert _travel([_distance_statement("far"), *_floor_at(2000)]) == (2000, "learned_floor")


def test_a_learned_distance_row_with_no_pivot_is_read_as_nothing() -> None:
    from silverloop.preferences import travel_beliefs

    legacy = DimensionPreference(
        dimension=PreferenceDimension.DISTANCE,
        value="near",
        strength=0.5,
        source="inferred",
        observations=2,
        updated_at=NOW,
        positive_evidence=2.0,
    )
    assert travel_beliefs(resolve([legacy])) == []
    assert _travel([legacy, *_floor_at(2000)]) == (2000, "learned_floor")


def test_a_higher_tier_far_neither_widens_nor_silences_a_stated_near() -> None:
    """A temporary "I don't mind going further" outranks a standing "somewhere near" by tier, but
    a far-leaning belief is never read, so it resolves apart and cannot lift the cap."""
    from silverloop.preferences import belief_in_effect

    temporary_far = _distance_statement("far").model_copy(
        update={"expires_at": NOW + timedelta(days=3)}
    )
    temporary_avoid_near = _distance_statement("near", -1.0).model_copy(
        update={"expires_at": NOW + timedelta(days=3)}
    )
    for widening in (temporary_far, temporary_avoid_near):
        rows = [_distance_statement("near"), widening, *_floor_at(2000)]
        assert _travel(rows) == (1000, "stated_near")
        by_lean = {(p.value, p.sentiment): p for p in resolve(rows) if p.pivot is None}
        assert belief_in_effect(by_lean[("near", "like")]) is True
        far = next(p for key, p in by_lean.items() if key != ("near", "like"))
        assert far.tier == far.winning_tier and belief_in_effect(far) is False


def test_a_learned_ceiling_exactly_at_the_nearby_radius_names_the_stated_near() -> None:
    """A tie at the boundary counts as binding, as every other step does: 1 km learned "too far"
    over a 2 km floor, then a stated "near" at the same 1 km."""
    learned = [*_floor_at(2000), *_too_far_at(1000)]
    assert _travel(learned) == (1000, "learned_ceiling")
    assert _travel([_distance_statement("near"), *learned]) == (1000, "stated_near")


def test_the_less_travel_goal_behaves_like_a_stated_near() -> None:
    from silverloop.models import ActivityGoal, GoalKind
    from silverloop.preferences import GOAL_DIMENSION_VALUES

    assert GOAL_DIMENSION_VALUES[GoalKind.LESS_TRAVEL] == (PreferenceDimension.DISTANCE, "near")
    goal = ActivityGoal(goal_id="g1", kind=GoalKind.LESS_TRAVEL, text="Travel less", created_at=NOW)
    assert _travel(_floor_at(2000), goals=[goal]) == (1000, "stated_near")
    assert _travel([*_floor_at(2000), *_too_far_at(650)], goals=[goal]) == (650, "learned_ceiling")
    assert _travel([], goals=[goal]) == (DEFAULT_TRAVEL_TOLERANCE_M, "default")
    inactive = goal.model_copy(update={"active": False})
    assert _travel(_floor_at(2000), goals=[inactive]) == (2000, "learned_floor")
