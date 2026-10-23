"""Ground-truth relevance grading, read ONLY from `PersonaBrief.stated_tastes`/`soft_avoids`/
`hard_avoids` and the persona's own decline-cooldown state -- never from the trace-derived
`ActivityPreferences`/`ActivityEngagement` the ranker is scored against (see `dataset.py`'s module
docstring on information asymmetry).

Grades, assigned lexicographically (highest matching rule wins):

  3  satisfies all hard constraints, matches >=1 stated taste, hits no avoid
  2  satisfies constraints, matches no taste, hits no avoid
  1  satisfies constraints, hits a SOFT avoid
  0  hits a HARD ("stated") avoid, OR the candidate is inside the person's own decline cooldown

"Satisfies all hard constraints" is not separately re-checked here: every candidate this module
grades has already survived `activity_search.filter_candidates`, which enforces every hard
constraint before anything is graded or ranked (see `runner.py`). The artifact used to report that
as a `constraint_satisfaction@3` row reading 1.0 on every case; it is a property of
`activity_search`, not a measurement, and now lives in that module's own unit tests
(`test_every_hard_constraint_violation_is_removed_before_ranking_ever_sees_it`).
"""

from __future__ import annotations

from datetime import date, timedelta

from silverloop.activity_search import DECLINE_COOLDOWN_DAYS, ActivityEngagement
from silverloop.evaluation.ranking._dimensions import candidate_dimension_value
from silverloop.evaluation.ranking.dataset import PersonaBrief
from silverloop.models import ActivityCandidate, PreferenceDimension

GRADE_HARD_AVOID_OR_COOLDOWN = 0
GRADE_SOFT_AVOID = 1
GRADE_NEUTRAL = 2
GRADE_TASTE_MATCH = 3


def _matches_any(
    candidate: ActivityCandidate, pairs: tuple[tuple[PreferenceDimension, str], ...]
) -> bool:
    return any(
        candidate_dimension_value(dimension, candidate) == value for dimension, value in pairs
    )


def _inside_decline_cooldown(engagement: ActivityEngagement | None, today: date) -> bool:
    if engagement is None or engagement.last_not_for_me is None:
        return False
    return today - engagement.last_not_for_me < timedelta(days=DECLINE_COOLDOWN_DAYS)


def grade_candidate(
    persona: PersonaBrief,
    candidate: ActivityCandidate,
    engagement: ActivityEngagement | None,
    today: date,
) -> int:
    """One candidate's graded relevance (0-3) for one persona, per the lexicographic rule above.

    `engagement` here is a stand-in for "the persona's own recorded response to this listing" --
    grading uses only `last_not_for_me` (a plain historical fact), never anything the ranker
    inferred from it, so this stays a ground-truth judgement rather than a second opinion on the
    ranker's own preference store.
    """
    if _inside_decline_cooldown(engagement, today):
        return GRADE_HARD_AVOID_OR_COOLDOWN
    if _matches_any(candidate, persona.hard_avoids):
        return GRADE_HARD_AVOID_OR_COOLDOWN
    if _matches_any(candidate, persona.soft_avoids):
        return GRADE_SOFT_AVOID
    if _matches_any(candidate, persona.stated_tastes):
        return GRADE_TASTE_MATCH
    return GRADE_NEUTRAL
