"""Derive what the ranker actually sees -- `ActivityPreferences` and per-listing
`ActivityEngagement` -- from a persona's `PersonaBrief.trace`.

This module never reads `PersonaBrief.stated_tastes`/`soft_avoids`/`hard_avoids`. That is the
information-asymmetry boundary the whole benchmark rests on (see `dataset.py`'s module
docstring): the ground-truth grader (`labels.py`) and the ranker's own inputs (this module) must
be built from disjoint parts of the brief, or scoring the ranker against the brief would be
partly circular.

`apply_decline` and `apply_enjoyment` are the same, unmodified, production functions
`silverloop.preferences` exports -- nothing here re-implements dimension-learning logic -- and
`build_engagement` counts through `activity_search.count_engagement` and
`engagement_by_series`, the functions the repository ranks from.

`label_engagement` is the one exception, and it is not a ranker input: it is the grader's frozen
per-listing cooldown read (see its docstring). It still reads only the trace.
"""

from __future__ import annotations

from datetime import date, datetime

from silverloop.activity_search import (
    ActivityEngagement,
    count_engagement,
    engagement_by_series,
    series_key,
    series_keys_for,
)
from silverloop.evaluation.ranking.dataset import (
    CATALOGUE,
    CATALOGUE_BY_ID,
    FROZEN_TODAY,
    DeclineEvent,
    EnjoymentEvent,
    InterestEvent,
    PersonaBrief,
    StatedPreferenceEvent,
    TraceEvent,
)
from silverloop.local_time import at_local
from silverloop.models import (
    ActivityOfferResponse,
    ActivityPreferences,
    DimensionPreference,
    PlannedFollowThrough,
)
from silverloop.preferences import apply_decline, apply_enjoyment

# `activity_id -> series_key` over the frozen catalogue, the key production rolls engagement up by.
_CATALOGUE_SERIES_KEYS = series_keys_for(CATALOGUE)


def _now(day: date) -> datetime:
    return at_local(day, 12, 0)


def trace_prefix(persona: PersonaBrief, limit: int | None) -> tuple[TraceEvent, ...]:
    """The first `limit` events of the persona's observation trace (all of it when `None`).

    The learning-curve arms are built from this and nothing else: the persona, the catalogue, the
    query and the grade table are all held fixed, so the only thing that varies is how much
    evidence the ranker has been given. `limit=0` is the day the person signs up.
    """
    return persona.trace if limit is None else persona.trace[:limit]


def build_preferences(persona: PersonaBrief, *, limit: int | None = None) -> ActivityPreferences:
    """Fold the trace's declines/enjoyments/stated preferences into an `ActivityPreferences`,
    using exactly the production folding functions -- so any change to `apply_decline`/
    `apply_enjoyment` is exercised by this benchmark rather than a private copy of it.

    `limit` truncates the trace to its first `limit` events, for the cold-start and learning-curve
    arms; it defaults to the whole trace, so every existing caller keeps its meaning.

    Each decline carries its own origin id and the programme it was about, as production's do
    (`sql_repository._apply_activity_decline`), so a second unclarified answer about the same
    programme widens nothing here either. Origin ids are the event's position in the trace:
    unique per event, and stable however `limit` truncates it.
    """
    dimensions: list[DimensionPreference] = []
    origin_series: dict[str, str] = {}
    for index, event in enumerate(trace_prefix(persona, limit)):
        if isinstance(event, DeclineEvent):
            candidate = CATALOGUE_BY_ID[event.activity_id]
            origin_id = f"trace:{persona.person_id}:{index}"
            series = series_key(candidate)
            origin_series[origin_id] = series
            dimensions = apply_decline(
                dimensions,
                event.reason,
                candidate,
                _now(event.day),
                origin_id=origin_id,
                series=series,
                origin_series=origin_series,
            )
        elif isinstance(event, EnjoymentEvent):
            candidate = CATALOGUE_BY_ID[event.activity_id]
            dimensions = apply_enjoyment(
                dimensions, event.enjoyment, list(event.liked), candidate, _now(event.day)
            )
        elif isinstance(event, StatedPreferenceEvent):
            dimensions = [
                d
                for d in dimensions
                if not (d.dimension is event.dimension and d.value == event.value)
            ]
            dimensions.append(
                DimensionPreference(
                    dimension=event.dimension,
                    value=event.value,
                    strength=event.strength,
                    source="senior_statement",
                    confirmed=True,
                    observations=1,
                    # Stated preferences carry no `day` of their own (a person can restate one at
                    # any time); anchored to the frozen "today" so every case in one run sees an
                    # identical, reproducible timestamp.
                    updated_at=_now(FROZEN_TODAY),
                    stated_text=event.stated_text,
                )
            )
        # InterestEvent teaches no dimension: a bare "I'm interested" tap is too weak, real
        # engagement evidence (folded into `ActivityEngagement` below, never into a preference).
    return ActivityPreferences(person_id=persona.person_id, dimensions=dimensions)


def build_engagement(
    persona: PersonaBrief, *, limit: int | None = None
) -> dict[str, ActivityEngagement]:
    """What the ranker sees about the person's own responses, through the production pipeline.

    Each trace event becomes the row production would have recorded -- an `InterestEvent` an
    "interested" search-card answer, a `DeclineEvent` a "not for me" one, an `EnjoymentEvent` a
    `went` follow-through plus its enjoyment verdict -- and those rows are counted by
    `activity_search.count_engagement` and rolled up to the programme by
    `activity_search.engagement_by_series`, keyed by `series_keys_for` over the frozen catalogue:
    the same two functions and the same key `sql_repository._activity_engagement` uses. A private
    copy of that counting used to live here, keyed per session with no programme roll-up, so the
    benchmark scored a ranker that saw a decline on Monday's class as touching Monday only.

    `limit` truncates the trace, as in `build_preferences`. The grader does not read this; see
    `label_engagement`.
    """
    offers: list[tuple[str, str, date]] = []
    follow_through: list[tuple[str, str]] = []
    verdicts: list[tuple[str, str]] = []
    for event in trace_prefix(persona, limit):
        if isinstance(event, InterestEvent):
            offers.append((event.activity_id, ActivityOfferResponse.INTERESTED.value, event.day))
        elif isinstance(event, DeclineEvent):
            offers.append((event.activity_id, ActivityOfferResponse.NOT_FOR_ME.value, event.day))
        elif isinstance(event, EnjoymentEvent):
            follow_through.append((event.activity_id, PlannedFollowThrough.WENT.value))
            verdicts.append((event.activity_id, event.enjoyment.value))
    counted = count_engagement(offers, follow_through, verdicts)
    return engagement_by_series(
        counted.counts, counted.last_declined, counted.answered, _CATALOGUE_SERIES_KEYS
    )


def label_engagement(
    persona: PersonaBrief, *, limit: int | None = None
) -> dict[str, ActivityEngagement]:
    """The GRADER's input, frozen: each listing's own responses, per session, with the day of the
    most recent "not for me" -- a search-card decline or an "I went, and it was not for me".

    Not what the ranker sees (that is `build_engagement`), and deliberately not kept in step with
    it. `labels.grade_candidate` reads only `last_not_for_me` from this, as a plain historical
    fact about the listing; the relevance grades are hand-authored ground truth, and moving them
    whenever production's engagement counting changes would turn the benchmark into a second
    opinion on the ranker. This is the counting the grades were authored against, kept verbatim.
    Where the two disagree -- a sibling session of a declined programme is held back for the
    ranker but not graded as inside a cooldown -- that is measured, not hidden
    (`test_ranking_evaluation.py`).
    """
    interested: dict[str, int] = {}
    not_for_me: dict[str, int] = {}
    went: dict[str, int] = {}
    enjoyed: dict[str, int] = {}
    last_not_for_me: dict[str, object] = {}

    for event in trace_prefix(persona, limit):
        if isinstance(event, InterestEvent):
            interested[event.activity_id] = interested.get(event.activity_id, 0) + 1
        elif isinstance(event, DeclineEvent):
            not_for_me[event.activity_id] = not_for_me.get(event.activity_id, 0) + 1
            current = last_not_for_me.get(event.activity_id)
            if current is None or event.day > current:
                last_not_for_me[event.activity_id] = event.day
        elif isinstance(event, EnjoymentEvent):
            went[event.activity_id] = went.get(event.activity_id, 0) + 1
            if event.enjoyment.value == "enjoyed":
                enjoyed[event.activity_id] = enjoyed.get(event.activity_id, 0) + 1
            elif event.enjoyment.value == "not_for_me":
                not_for_me[event.activity_id] = not_for_me.get(event.activity_id, 0) + 1
                current = last_not_for_me.get(event.activity_id)
                if current is None or event.day > current:
                    last_not_for_me[event.activity_id] = event.day

    ids = set(interested) | set(not_for_me) | set(went) | set(enjoyed)
    return {
        activity_id: ActivityEngagement(
            interested=interested.get(activity_id, 0),
            not_for_me=not_for_me.get(activity_id, 0),
            went=went.get(activity_id, 0),
            enjoyed=enjoyed.get(activity_id, 0),
            last_not_for_me=last_not_for_me.get(activity_id),
        )
        for activity_id in ids
    }
