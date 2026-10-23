"""The weighted preference learner, and the claim it exists to make.

`PreferenceLearner` used to count outcomes: an `accepted` was one success, exactly like a
`coordinator_resolved`. That made a tap on "Yes, tell me more" indistinguishable from a person
telling us they actually went for the walk, which is the definition of a click-through optimiser.

It went on to fold enjoyment into that same posterior, with `enjoyment` superseding
`follow_through` -- which fixed "attended and hated it scores like attended and loved it" but broke
something else: a candidate attended every time it was offered and rated a lukewarm "okay" every
time lost its entire attendance history to `okay`'s (0.5, 0.5), reading exactly like a candidate
nobody had ever tried. `PreferenceLearner` now keeps two posteriors -- ENGAGEMENT (would they
attend again) and EXPERIENCE (was it any good, once attended) -- and `expected_value` is their
product. See `docs/adr/0005-engagement-and-experience-as-two-learned-signals.md`.

These tests pin the replacement. They are deliberately written as *comparisons* rather than as
assertions on magic numbers wherever the comparison is the actual product claim -- if someone
retunes `_OUTCOME_WEIGHTS`, the relationships below must survive the retune or the change is
wrong regardless of the numbers chosen.

Nothing here touches the safety policy. The learner only ever reorders candidates the
deterministic ladder already permitted; that invariant is exercised in `test_api.py` and
`test_policy.py`, not here.
"""

from __future__ import annotations

import pytest

from silverloop.learning import (
    _DECLINE_REASON_WEIGHTS,
    _FOLLOW_THROUGH_WEIGHTS,
    _OUTCOME_WEIGHTS,
    _OUTCOMES_NEVER_REACHED_BY_THE_LEARNER,
    MIN_SINGLE_OBSERVATION_DELTA,
    PreferenceLearner,
    _single_observation_deltas,
)
from silverloop.models import DeclineReason, FollowThrough, OutcomeKind

PRIOR = 0.5  # Beta(1, 1) -- one posterior's own prior mean.
# `expected_value`'s prior, now that it is a product of two independent Beta(1, 1) posteriors
# (ENGAGEMENT x EXPERIENCE). Every test below that reasons about `expected_value` movement
# relative to "no evidence at all" must anchor to this, not to `PRIOR`.
COMBINED_PRIOR = PRIOR * PRIOR


# ── Acceptance is not success ─────────────────────────────────────────────────────────────────


def test_a_tap_moves_the_posterior_far_less_than_a_completed_follow_through() -> None:
    """The central claim of the whole change.

    Both people said yes. Only one of them did the thing. If those two observations move the
    ranking by anything close to the same amount, the learner is back to optimising taps.
    """
    learner = PreferenceLearner()
    learner.record("tapped_only", OutcomeKind.ACCEPTED.value)
    learner.record(
        "actually_did_it",
        OutcomeKind.ACCEPTED.value,
        follow_through=FollowThrough.COMPLETED.value,
    )

    tap_movement = learner.expected_value("tapped_only") - COMBINED_PRIOR
    completed_movement = learner.expected_value("actually_did_it") - COMBINED_PRIOR

    assert tap_movement > 0, "a tap is still weak evidence, not zero evidence"
    assert completed_movement > tap_movement
    # "Far less", stated as a number so the test fails if the gap is ever quietly narrowed to a
    # rounding difference. At the shipped weights the real ratio is ~3x.
    assert completed_movement > tap_movement * 2


def test_acceptance_alone_never_reaches_the_confidence_of_a_reported_completion() -> None:
    """Even a long run of bare taps must not overtake a single reported completion.

    This is the version of the property that matters operationally: a candidate can be tapped
    every single time it is offered and still not be ranked as highly as one that was actually
    carried out, because taps are not what the product is trying to cause.
    """
    tapped = PreferenceLearner()
    for _ in range(3):
        tapped.record("tapped", OutcomeKind.ACCEPTED.value)

    completed = PreferenceLearner()
    completed.record(
        "completed",
        OutcomeKind.ACCEPTED.value,
        follow_through=FollowThrough.COMPLETED.value,
    )

    assert tapped.expected_value("tapped") < completed.expected_value("completed")


# ── "Maybe later" is not a refusal, and is not a yes ──────────────────────────────────────────


def test_deferred_moves_nothing_in_either_direction() -> None:
    learner = PreferenceLearner()
    before = learner.expected_value("chair")

    for _ in range(5):
        learner.record("chair", OutcomeKind.DEFERRED.value)

    assert learner.expected_value("chair") == before == COMBINED_PRIOR


def test_deferred_is_scored_more_kindly_than_silence_and_than_a_refusal() -> None:
    """A deferral used to be filed as `no_response` and penalised almost as hard as a decline.

    Ordering, not magnitudes: an explicit "maybe later" must sit strictly above silence, and
    silence strictly above an explicit no.
    """
    learner = PreferenceLearner()
    learner.record("deferred", OutcomeKind.DEFERRED.value)
    learner.record("silent", OutcomeKind.NO_RESPONSE.value)
    learner.record("refused", OutcomeKind.DECLINED.value)

    assert (
        learner.expected_value("deferred")
        > learner.expected_value("silent")
        > learner.expected_value("refused")
    )


# ── One intervention, at most one unit of evidence ────────────────────────────────────────────


def test_follow_through_supersedes_acceptance_rather_than_stacking_on_it() -> None:
    """The accepted weight is *released*, not kept, once the person says what happened.

    Stacking would let a single intervention contribute 1.25 units of positive evidence, and
    would mean the tap keeps credit the follow-through has already superseded.
    """
    superseded = PreferenceLearner()
    superseded.record(
        "walk", OutcomeKind.ACCEPTED.value, follow_through=FollowThrough.COMPLETED.value
    )

    # `activity_recovered` carries exactly the (1.0, 0.0) that `completed` carries, so an
    # accepted-then-completed intervention must land on precisely the same posterior.
    reference = PreferenceLearner()
    reference.record("walk", OutcomeKind.ACTIVITY_RECOVERED.value)

    assert superseded.expected_value("walk") == reference.expected_value("walk")

    # And explicitly *not* the stacked value, which is what a `+=` on both weights would give.
    stacked_alpha = 1.0 + _OUTCOME_WEIGHTS["accepted"][0] + _FOLLOW_THROUGH_WEIGHTS["completed"][0]
    stacked_beta = 1.0 + _OUTCOME_WEIGHTS["accepted"][1] + _FOLLOW_THROUGH_WEIGHTS["completed"][1]
    assert superseded.expected_value("walk") != round(
        stacked_alpha / (stacked_alpha + stacked_beta), 3
    )


def test_an_accepted_suggestion_that_was_never_acted_on_loses_the_credit_acceptance_gave_it() -> (
    None
):
    """`unable` is beta-only -- it must be able to drag a candidate *below* the prior.

    If acceptance were retained alongside it the posterior could never fall below the prior, and
    a candidate nobody can actually do would keep being offered. It is now half a unit rather
    than a full one (see `test_unable_moves_the_posterior_less_than_an_outright_decline`), which
    softens the movement without changing its direction -- the property this pins.
    """
    learner = PreferenceLearner()
    learner.record("walk", OutcomeKind.ACCEPTED.value, follow_through=FollowThrough.UNABLE.value)

    assert learner.expected_value("walk") < COMBINED_PRIOR


def test_a_follow_through_the_learner_does_not_know_falls_back_to_the_outcome_weight() -> None:
    """An unrecognised follow-through must not silently erase the outcome evidence."""
    learner = PreferenceLearner()
    learner.record("walk", OutcomeKind.ACCEPTED.value, follow_through="teleported")

    plain = PreferenceLearner()
    plain.record("walk", OutcomeKind.ACCEPTED.value)

    assert learner.expected_value("walk") == plain.expected_value("walk")


def test_an_unknown_outcome_is_left_alone_rather_than_guessed_at() -> None:
    learner = PreferenceLearner()
    learner.record("walk", "invented_outcome")
    assert learner.expected_value("walk") == COMBINED_PRIOR


# ── The differentiating property: ranking ─────────────────────────────────────────────────────


def test_high_acceptance_low_follow_through_ranks_below_low_acceptance_high_follow_through() -> (
    None
):
    """The behaviour a reviewer should check first, because it is the one that changed.

    `popular` is the candidate everybody taps and nobody does. `effective` is offered a third as
    often and is actually carried out. The old counting learner ranked `popular` first -- which
    is asserted below, so the inversion is demonstrated rather than claimed.
    """
    learner = PreferenceLearner()

    # Tapped six times; every single time the person later reported "not this time".
    for _ in range(6):
        learner.record(
            "popular", OutcomeKind.ACCEPTED.value, follow_through=FollowThrough.NOT_THIS_TIME.value
        )

    # Tapped twice; carried out both times.
    for _ in range(2):
        learner.record(
            "effective", OutcomeKind.ACCEPTED.value, follow_through=FollowThrough.COMPLETED.value
        )

    assert learner.expected_value("effective") > learner.expected_value("popular")

    # The counterfactual: ranking on acceptance alone -- what the learner did before this change
    # -- puts them the other way round. Without this the test above could pass for the wrong
    # reason (e.g. if `popular` simply had fewer observations).
    acceptance_only = PreferenceLearner()
    for _ in range(6):
        acceptance_only.record("popular", OutcomeKind.ACCEPTED.value)
    for _ in range(2):
        acceptance_only.record("effective", OutcomeKind.ACCEPTED.value)
    assert acceptance_only.expected_value("popular") > acceptance_only.expected_value("effective")


def test_partial_follow_through_sits_between_completed_and_unable() -> None:
    """ "I did some of it" is real evidence in both directions and must not collapse to either."""
    learner = PreferenceLearner()
    learner.record("done", OutcomeKind.ACCEPTED.value, follow_through=FollowThrough.COMPLETED.value)
    learner.record("some", OutcomeKind.ACCEPTED.value, follow_through=FollowThrough.PARTIAL.value)
    learner.record("none", OutcomeKind.ACCEPTED.value, follow_through=FollowThrough.UNABLE.value)

    assert (
        learner.expected_value("done")
        > learner.expected_value("some")
        > learner.expected_value("none")
    )


def test_snapshot_reports_every_requested_key_including_unseen_ones() -> None:
    learner = PreferenceLearner()
    learner.record("seen", OutcomeKind.ACCEPTED.value)

    snapshot = learner.snapshot(["seen", "never_offered"])

    assert set(snapshot) == {"seen", "never_offered"}
    assert snapshot["never_offered"] == COMBINED_PRIOR


# ── Exhaustiveness guard ──────────────────────────────────────────────────────────────────────
#
# `record` returns silently when it has no weight for an outcome. That is the right runtime
# behaviour (guessing would be worse) and exactly the wrong failure mode to leave unguarded: a
# new `OutcomeKind` member ships, nothing raises, nothing logs, and the product simply stops
# learning from that outcome. These two tests are the only thing standing between that and a
# silent regression.


def test_every_outcome_kind_has_a_learning_weight_or_is_named_unreachable() -> None:
    """Two escape hatches, both explicit. A new `OutcomeKind` either gets a weight or is written
    down as one the learner can never be handed -- and the second claim is itself pinned by
    `test_the_outcomes_the_learner_never_sees_are_named_rather_than_given_a_zero_weight`."""
    missing = [
        member.value
        for member in OutcomeKind
        if member.value not in _OUTCOME_WEIGHTS
        and member.value not in _OUTCOMES_NEVER_REACHED_BY_THE_LEARNER
    ]
    assert not missing, (
        f"OutcomeKind members with no entry in _OUTCOME_WEIGHTS: {missing}. "
        "A new outcome without a weight is silently never learned from."
    )


def test_every_follow_through_has_a_learning_weight() -> None:
    missing = [
        member.value for member in FollowThrough if member.value not in _FOLLOW_THROUGH_WEIGHTS
    ]
    assert not missing, (
        f"FollowThrough members with no entry in _FOLLOW_THROUGH_WEIGHTS: {missing}. "
        "A new follow-through without a weight is silently never learned from."
    )


def test_no_weight_table_entry_is_orphaned_from_its_enum() -> None:
    """The other direction: a weight for a value the contract can no longer produce is dead
    code that reads like live policy."""
    assert set(_OUTCOME_WEIGHTS) <= {member.value for member in OutcomeKind}
    assert set(_FOLLOW_THROUGH_WEIGHTS) <= {member.value for member in FollowThrough}
    assert set(_OUTCOMES_NEVER_REACHED_BY_THE_LEARNER) <= {m.value for m in OutcomeKind}


def test_no_single_observation_contributes_more_than_one_unit_of_evidence() -> None:
    """The rule the weight tables are built to: one intervention, at most one unit.

    Pairs summing to less than one are intentional (the remainder is honest ignorance); a pair
    summing to more than one would let one reply outweigh a completed routine.
    """
    for table_name, table in (
        ("_OUTCOME_WEIGHTS", _OUTCOME_WEIGHTS),
        ("_FOLLOW_THROUGH_WEIGHTS", _FOLLOW_THROUGH_WEIGHTS),
    ):
        for key, (alpha, beta) in table.items():
            assert alpha >= 0 and beta >= 0, f"{table_name}[{key}] has a negative weight"
            assert alpha + beta <= 1.0, f"{table_name}[{key}] contributes more than one unit"


# ── Engagement and experience: two posteriors, not one (ADR 0005) ────────────────────────────


def test_attended_but_disliked_ranks_below_attended_and_enjoyed() -> None:
    """Before `_ENJOYMENT_WEIGHTS` existed these two were identical: the learner could only ever
    learn that a person turns up."""
    learner = PreferenceLearner()
    learner.record("loved", "accepted", "completed", "enjoyed")
    learner.record("hated", "accepted", "completed", "not_for_me")
    learner.record("okay", "accepted", "completed", "okay")
    assert learner.expected_value("loved") > learner.expected_value("okay")
    assert learner.expected_value("okay") > learner.expected_value("hated")
    # ENGAGEMENT is identical for all three (all "completed"): exactly one unit each, on top of
    # the (1, 1) prior. It is EXPERIENCE alone that separates them.
    assert learner.engagement_value("loved") == learner.engagement_value("hated")
    assert learner.engagement_value("hated") == learner.engagement_value("okay")
    engagement_alpha, engagement_beta = learner._engagement["hated"]
    assert engagement_alpha + engagement_beta == 3.0  # prior (1, 1) plus exactly one unit
    experience_alpha, experience_beta = learner._experience["hated"]
    assert experience_alpha + experience_beta == 3.0  # prior (1, 1) plus exactly one unit


def test_engagement_does_not_reset_when_an_enjoyment_report_arrives() -> None:
    """The defect ADR 0005 exists to fix: `okay`'s (0.5, 0.5) used to *replace* `completed`'s
    (1.0, 0.0) in the one posterior both fed, so ten reliable completions rated `okay` read
    exactly like a candidate nobody had ever tried. ENGAGEMENT must keep every completion's
    weight regardless of what the enjoyment report says.
    """
    learner = PreferenceLearner()
    for _ in range(10):
        learner.record("chair_exercise", "accepted", "completed", "okay")

    # Ten reliable completions: ENGAGEMENT should read as strong attendance, not the neutral
    # prior an "okay"-only posterior collapsed it to.
    assert learner.engagement_value("chair_exercise") > 0.8
    # EXPERIENCE is exactly the "okay" prior -- neutral, not eroded and not boosted.
    assert learner.experience_value("chair_exercise") == 0.5


def test_reliable_but_lukewarm_attendance_can_outrank_rare_but_loved_attendance() -> None:
    """The concrete ranking inversion ADR 0005 is written around: chair exercise, offered and
    completed every time and rated a shrug each time, against gardening, mostly turned down but
    glowing on the few occasions it was tried.

    Under the single collapsed posterior this used to be the other way round -- gardening's three
    `enjoyed` reports outweighed chair exercise's ten-for-ten record, because `okay` erased that
    record on contact. See the ADR for the exact numbers this test pins.
    """
    learner = PreferenceLearner()
    for _ in range(10):
        learner.record("chair_exercise", "accepted", "completed", "okay")
    for _ in range(3):
        learner.record("gardening", "accepted", "completed", "enjoyed")
    learner.record("gardening", "declined")
    learner.record("gardening", "declined")
    learner.record("gardening", "no_response")

    assert learner.expected_value("chair_exercise") == 0.458
    assert learner.expected_value("gardening") == 0.427
    assert learner.expected_value("chair_exercise") > learner.expected_value("gardening")


def test_enjoyment_attached_to_a_non_attendance_follow_through_is_not_experience_evidence() -> None:
    """An enjoyment verdict is only evidence about the experience when the person actually
    attended. `not_this_time` and `unable` are both "did not do it" facts; a report attached to
    either (a client-side edge case the API does not currently forbid) must not move EXPERIENCE.
    """
    learner = PreferenceLearner()
    learner.record("walk", "accepted", "not_this_time", "enjoyed")

    assert learner.experience_value("walk") == 0.5
    # ENGAGEMENT still reads the `not_this_time` follow-through normally.
    assert learner.engagement_value("walk") < 0.5


def test_every_enjoyment_has_a_learning_weight_of_at_most_one_unit() -> None:
    from silverloop.learning import _ENJOYMENT_WEIGHTS
    from silverloop.models import Enjoyment

    assert set(_ENJOYMENT_WEIGHTS) == {member.value for member in Enjoyment}
    for key, (alpha, beta) in _ENJOYMENT_WEIGHTS.items():
        assert alpha >= 0 and beta >= 0 and alpha + beta <= 1.0, key


# ── A decline is not one answer: reason-keyed weights ────────────────────────────────────────
#
# `record_outcome` has always stored the one-tap `DeclineReason` on the outcome row, and
# suppression has always read it (a `bad_day` decline never counts toward muting a candidate).
# The posterior that actually orders outreach did not: "just a bad day", "I am already getting
# about" (a correction to the *sensor*, not a verdict on the option) and "it is not for me" all
# arrived at `record` as a bare `declined` and each taught a full unit against the candidate.


def test_a_bad_day_decline_leaves_the_posterior_exactly_where_it_was() -> None:
    """ "Not today" is a fact about the day. Three quiet-week declines used to drag a perfectly
    good option to a fraction of its starting value."""
    learner = PreferenceLearner()
    for _ in range(3):
        learner.record("chair", OutcomeKind.DECLINED.value, reason=DeclineReason.BAD_DAY.value)

    assert learner.expected_value("chair") == COMBINED_PRIOR


def test_already_active_is_a_sensor_correction_and_never_ranks_the_option_down() -> None:
    """`ALREADY_ACTIVE` is the person telling us the wearable is wrong. `policy.py` reads it as
    data quality; ranking the suggestion down for it would punish the option for the tracker's
    mistake."""
    learner = PreferenceLearner()
    learner.record("chair", OutcomeKind.DECLINED.value, reason=DeclineReason.ALREADY_ACTIVE.value)

    assert learner.expected_value("chair") == COMBINED_PRIOR


def test_not_for_me_still_carries_the_full_weight_of_a_bare_decline() -> None:
    """The carve-out above must not have softened the decline that really is about the option."""
    reasoned = PreferenceLearner()
    reasoned.record("chair", OutcomeKind.DECLINED.value, reason=DeclineReason.NOT_FOR_ME.value)

    bare = PreferenceLearner()
    bare.record("chair", OutcomeKind.DECLINED.value)

    assert reasoned.expected_value("chair") == bare.expected_value("chair") < COMBINED_PRIOR


def test_a_bad_day_decline_outranks_a_not_for_me_decline() -> None:
    """The ordering the whole change exists for, stated without magic numbers."""
    learner = PreferenceLearner()
    learner.record("bad_day", OutcomeKind.DECLINED.value, reason=DeclineReason.BAD_DAY.value)
    learner.record("refused", OutcomeKind.DECLINED.value, reason=DeclineReason.NOT_FOR_ME.value)

    assert learner.expected_value("bad_day") > learner.expected_value("refused")


def test_an_unrecognised_decline_reason_falls_back_to_the_bare_decline_weight() -> None:
    """A reason this learner has no entry for is still a decline -- it must never be read as the
    zero-weight carve-out by accident."""
    learner = PreferenceLearner()
    learner.record("chair", OutcomeKind.DECLINED.value, reason="invented_reason")

    bare = PreferenceLearner()
    bare.record("chair", OutcomeKind.DECLINED.value)

    assert learner.expected_value("chair") == bare.expected_value("chair")


def test_a_reason_attached_to_an_outcome_that_is_not_a_decline_changes_nothing() -> None:
    """`OutcomeRequest.reason` is "only meaningful alongside `declined`". A client that sends one
    anyway must not be able to zero out an acceptance with `bad_day`."""
    learner = PreferenceLearner()
    learner.record("chair", OutcomeKind.ACCEPTED.value, reason=DeclineReason.BAD_DAY.value)

    plain = PreferenceLearner()
    plain.record("chair", OutcomeKind.ACCEPTED.value)

    assert learner.expected_value("chair") == plain.expected_value("chair")


def test_unable_moves_the_posterior_less_than_an_outright_decline() -> None:
    """ "I couldn't today" is not "I won't". `unable` used to carry the same full unit against the
    candidate that a flat refusal does, and it is the one follow-through the product promises is
    never read as a statement about the person."""
    learner = PreferenceLearner()
    learner.record(
        "could_not", OutcomeKind.ACCEPTED.value, follow_through=FollowThrough.UNABLE.value
    )
    learner.record("refused", OutcomeKind.DECLINED.value)

    assert learner.expected_value("could_not") > learner.expected_value("refused")
    # Still negative evidence, though: an option nobody can actually do must be rankable down.
    assert learner.expected_value("could_not") < COMBINED_PRIOR


def test_every_decline_reason_has_a_learning_weight() -> None:
    missing = [
        member.value for member in DeclineReason if member.value not in _DECLINE_REASON_WEIGHTS
    ]
    assert not missing, (
        f"DeclineReason members with no entry in _DECLINE_REASON_WEIGHTS: {missing}. "
        "A new reason without a weight silently falls back to a full-unit decline."
    )


def test_no_decline_reason_weight_is_orphaned_from_its_enum() -> None:
    assert set(_DECLINE_REASON_WEIGHTS) <= {member.value for member in DeclineReason}


def test_no_decline_reason_contributes_more_than_one_unit_of_evidence() -> None:
    for reason, (alpha, beta) in _DECLINE_REASON_WEIGHTS.items():
        assert alpha >= 0 and beta >= 0, f"_DECLINE_REASON_WEIGHTS[{reason}] has a negative weight"
        assert alpha + beta <= 1.0, f"_DECLINE_REASON_WEIGHTS[{reason}] is more than one unit"


# ── The reason table is inside the bound it perturbs (ADR 0005) ──────────────────────────────


def test_every_decline_reason_weight_is_enumerated_by_the_single_observation_probe() -> None:
    """`SOCIAL_DIMENSION_RANKING_WEIGHT` is `MIN_SINGLE_OBSERVATION_DELTA / 4`, and that minimum
    is recomputed at import from the weight tables so a retune cannot silently invalidate it.
    A reason-keyed table the enumeration cannot see would make that claim false in the *unsafe*
    direction while every existing test kept passing.
    """
    baseline = PreferenceLearner().expected_value("_probe")
    enumerated = _single_observation_deltas()

    for reason, weights in _DECLINE_REASON_WEIGHTS.items():
        learner = PreferenceLearner()
        learner.record("_probe", OutcomeKind.DECLINED.value, reason=reason)
        delta = learner.expected_value("_probe") - baseline
        if weights == (0.0, 0.0):
            assert delta == 0, reason
            continue
        assert any(abs(candidate - delta) < 1e-12 for candidate in enumerated), (
            f"the delta a single `declined` + {reason!r} produces ({delta}) is not enumerated by "
            "_single_observation_deltas()"
        )


def test_a_retuned_reason_weight_smaller_than_todays_minimum_shrinks_the_enumerated_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property that matters is not "today's numbers are safe" -- they are -- but that a
    *future* reason weight below the current minimum is seen. Enumerating the outcome table
    alone returns the same minimum as before and leaves the social nudge able to override the
    observation this hypothetical reason records.
    """
    monkeypatch.setitem(_DECLINE_REASON_WEIGHTS, DeclineReason.BAD_TIMING.value, (0.0, 0.02))

    smallest = min(abs(delta) for delta in _single_observation_deltas())

    assert smallest < MIN_SINGLE_OBSERVATION_DELTA


# ── Outcomes that never reach the learner at all ─────────────────────────────────────────────


def test_the_outcomes_the_learner_never_sees_are_named_rather_than_given_a_zero_weight() -> None:
    """`coordinator_resolved` cannot reach `record`: `record_outcome` rejects it outright (see
    `test_follow_through_api.py`'s coordinator-route test) and case review writes a
    `CaseReviewRow`, never an `InterventionOutcomeRow`. It used to sit in `_OUTCOME_WEIGHTS` as a
    considered `(0.0, 0.0)`, which reads as live policy for a path no data takes. It is named as
    unreachable instead, and the exhaustiveness guard still covers it.
    """
    assert set(_OUTCOMES_NEVER_REACHED_BY_THE_LEARNER) == {OutcomeKind.COORDINATOR_RESOLVED.value}
    assert not _OUTCOMES_NEVER_REACHED_BY_THE_LEARNER & set(_OUTCOME_WEIGHTS)

    # And if one ever did arrive, the fail-safe is `record`'s silent no-op, not a chosen weight.
    learner = PreferenceLearner()
    learner.record("k", OutcomeKind.COORDINATOR_RESOLVED.value)
    assert learner.expected_value("k") == COMBINED_PRIOR
