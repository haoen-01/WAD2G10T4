"""Whether a shown reason line is actually grounded -- the evaluation harness's own check.

The *question* is still asked independently: a shown `INTENT` reason is verified against the
intent and the candidate directly, never merely trusted because `reasons_for` produced it.

What is no longer independent is the small vocabulary the question is asked in. This module used
to keep its own copy of the environment-compatibility table and the time-of-day boundaries, with
the drift risk documented as accepted -- and then three copies of "does sheltered count as
indoors" came to coexist and disagree, so a listing could be filtered in on one reading and
graded out on another. Both are imported now (see `_dimensions.py`); only the verification is the
harness's own.
"""

from __future__ import annotations

from silverloop.activity_search import _time_window_for_hour
from silverloop.local_time import local_hour
from silverloop.models import (
    ActivityCandidate,
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    SocialPreference,
    TimeWindow,
)
from silverloop.preferences import Tri, environment_compatibility


def intent_is_constrained(intent: ActivityIntent) -> bool:
    return (
        intent.max_distance_m is not None
        or intent.time_window != TimeWindow.ANY
        or intent.social_preference != SocialPreference.EITHER
        or intent.environment != ActivityEnvironment.EITHER
        or intent.intensity != ActivityIntensity.EITHER
        or intent.language is not None
    )


def candidate_matches_a_constrained_axis(
    candidate: ActivityCandidate, intent: ActivityIntent
) -> bool:
    """Whether `candidate` actually satisfies at least one axis `intent` constrains -- the
    evaluation-only check `INTENT`-basis reasons are verified against (E1's definition: "the
    intent axis is constrained and the candidate matches").
    """
    if (
        intent.max_distance_m is not None
        and candidate.distance_m is not None
        and candidate.distance_m <= intent.max_distance_m
    ):
        return True
    if (
        intent.time_window != TimeWindow.ANY
        and candidate.start_at is not None
        and _time_window_for_hour(local_hour(candidate.start_at)) == intent.time_window
    ):
        return True
    if (
        intent.social_preference != SocialPreference.EITHER
        and candidate.social_shape is not None
        and candidate.social_shape == intent.social_preference
    ):
        return True
    if environment_compatibility(intent.environment, candidate.indoor_outdoor) is Tri.MATCH:
        return True
    if (
        intent.intensity != ActivityIntensity.EITHER
        and candidate.intensity is not None
        and candidate.intensity == intent.intensity
    ):
        return True
    return bool(
        intent.language is not None
        and candidate.language_tags
        and intent.language in candidate.language_tags
    )
