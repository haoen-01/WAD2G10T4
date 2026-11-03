"""Replanning: the world changed since something was planned, and the person is told plainly.

The sequence this exists for, spelled out in `ReplanNotice`'s own docstring: goal -> plan -> the
world changes -> replan -> ASK -> the person decides. `notices_for` is only the third and fourth
steps. It never touches a plan, never books anything and never removes an entry -- the caller owns
`WeekPlan` and `PlannedActivity` storage, and this module is not given a way to mutate either.

Two things make a planned activity worth a notice, and both are genuinely observable rather than
guessed at:

  * the listing itself has gone -- it no longer appears in the current catalogue at all, which
    covers a provider pulling it, cancelling it outright, or a scenario event ("programme_becomes_
    full") that removed rather than merely filled it;
  * the listing is still there but is now `FULL`.

A third case -- an outdoor plan the weather has turned against -- is included as an optional,
defaulted keyword (`rainy`), the same shape `activity_search.rank_candidates` uses for its own
weather nudge (`rain_forecast`) and for the same reason: the fact belongs to `ContextSignal`, which
this module is not otherwise given, and a bare boolean keeps the one live-context input explicit
and easy to trace at the call site rather than folding a hidden dependency into `catalogue`.

Every alternative offered is found, never invented: `activity_search.filter_candidates` and
`rank_candidates` do the same filtering and ordering they do everywhere else in the product, run
against an `ActivityIntent` built only from the plan's own recorded facts (its day, time of day,
company and pace) -- never from a fresh guess at what the person might want instead. `alternative`
is `None` whenever nothing survives that filter; "this is no longer available and nothing similar
was found" is an honest, complete answer on its own, not a failure to paper over.

HARD INVARIANT, same as `activity_search.py` and `preferences.py`: this module ranks and describes.
It never swaps, books or removes anything, and it has no import from `policy.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from silverloop.activity_search import ActivityEngagement, filter_candidates, rank_candidates
from silverloop.local_time import local_hour
from silverloop.models import (
    ActivityAvailability,
    ActivityCandidate,
    ActivityEnvironment,
    ActivityIntensity,
    ActivityIntent,
    ActivityPreferences,
    IndoorOutdoor,
    PlannedActivity,
    RankedActivity,
    ReplanNotice,
    ReplanOffer,
    ReplanReason,
    SocialPreference,
    TimeWindow,
)

_ENVIRONMENT_FROM_INDOOR_OUTDOOR: dict[IndoorOutdoor, ActivityEnvironment] = {
    IndoorOutdoor.INDOOR: ActivityEnvironment.INDOOR,
    IndoorOutdoor.OUTDOOR: ActivityEnvironment.OUTDOOR,
    IndoorOutdoor.SHELTERED: ActivityEnvironment.SHELTERED,
    IndoorOutdoor.UNKNOWN: ActivityEnvironment.EITHER,
}

_SOCIAL_FROM_SHAPE: dict[SocialPreference, SocialPreference] = {
    SocialPreference.SOCIAL: SocialPreference.SOCIAL,
    SocialPreference.SOLO: SocialPreference.SOLO,
}


def _time_window_for_hour(hour: int) -> TimeWindow:
    """Same bucket boundaries as `activity_search._time_window_for_hour`. Not imported, because
    that helper is private to a module whose only public surface is `filter_candidates`,
    `reasons_for` and `rank_candidates`; the boundaries are what this module shares with it, not
    the function.
    """
    if hour < 12:
        return TimeWindow.MORNING
    if hour < 17:
        return TimeWindow.AFTERNOON
    return TimeWindow.EVENING


def _intent_like(original: ActivityCandidate, *, day: date, prefer_indoors: bool) -> ActivityIntent:
    """An `ActivityIntent` grounded only in what the original plan actually was.

    Nothing here is a new preference the person expressed -- it is a restatement of the plan's own
    day, time of day, company and pace, so the alternative this produces is a genuine like-for-like
    replacement rather than a fresh guess. `prefer_indoors` is the one deliberate exception: it is
    set only when the reason for replanning is itself the weather, in which case asking for
    something indoors or sheltered is not inventing a preference but responding to the very fact
    that triggered this notice.
    """
    environment = (
        ActivityEnvironment.INDOOR
        if prefer_indoors
        else _ENVIRONMENT_FROM_INDOOR_OUTDOOR.get(
            original.indoor_outdoor, ActivityEnvironment.EITHER
        )
    )
    time_window = (
        _time_window_for_hour(local_hour(original.start_at))
        if original.start_at is not None
        else TimeWindow.ANY
    )
    social_preference = (
        _SOCIAL_FROM_SHAPE.get(original.social_shape, SocialPreference.EITHER)
        if original.social_shape is not None
        else SocialPreference.EITHER
    )
    intensity = original.intensity if original.intensity is not None else ActivityIntensity.EITHER
    return ActivityIntent(
        on_date=day,
        time_window=time_window,
        social_preference=social_preference,
        environment=environment,
        intensity=intensity,
    )


def _find(catalogue: list[ActivityCandidate], activity_id: str) -> ActivityCandidate | None:
    return next(
        (candidate for candidate in catalogue if candidate.activity_id == activity_id), None
    )


def _reason(*, fresh: ActivityCandidate | None, weather_turned: bool) -> ReplanReason | None:
    """The one thing that actually changed, or `None` when nothing did.

    Checked in a fixed order and stops at the first true condition, mirroring `activity_search.
    filter_candidates`'s own single-reason-per-removal discipline: a notice should say the one
    thing that made replanning necessary, not everything that happens to be true today.

    Returns the *code*, never the sentence. The two were the same string until the simulator was
    caught flipping a listing to `FULL` to represent bad weather (audit J finding F-J-A): with one
    string doing both jobs, the precedence below silently turned "the forecast turned" into "fully
    booked" on the senior's own screen. `sentence_for` owns the wording now, and only the wording.
    """
    if fresh is None:
        return ReplanReason.CANCELLED
    if fresh.availability == ActivityAvailability.FULL:
        return ReplanReason.FULL
    if weather_turned:
        return ReplanReason.WEATHER
    return None


def sentence_for(reason: ReplanReason, title: str) -> str:
    """The one plain sentence a person reads for a reason code. Never a status word, never a
    number, and never "fully booked" unless the listing genuinely is."""
    if reason == ReplanReason.CANCELLED:
        return f'"{title}" is no longer being offered.'
    if reason == ReplanReason.FULL:
        return f'"{title}" is now fully booked.'
    return f'"{title}" is outdoors, and today\'s forecast has turned against it.'


def alternative_for(
    entry: PlannedActivity,
    catalogue: list[ActivityCandidate],
    preferences: ActivityPreferences,
    *,
    today: date,
    prefer_indoors: bool,
    rainy: bool = False,
    engagement: Mapping[str, ActivityEngagement] | None = None,
) -> RankedActivity | None:
    """The best replacement for one planned activity, or `None` when nothing survives the filter.

    Found, never invented: the same `filter_candidates`/`rank_candidates` pair the search uses,
    over an `ActivityIntent` restated from the plan's own recorded facts. Public because the
    write path (`advance()`, recording the offer) and the read path (the notice the person sees)
    must answer this question the same way, and a second implementation of it would drift.
    """
    pool = [
        candidate for candidate in catalogue if candidate.activity_id != entry.activity.activity_id
    ]
    intent = _intent_like(entry.activity, day=entry.day, prefer_indoors=prefer_indoors)
    filtered, _ = filter_candidates(pool, intent, today=today)
    # The same engagement and calendar the search uses, so a listing the person has just
    # said "not for me" to is held back here too rather than offered as the replacement.
    ranked = rank_candidates(
        filtered,
        intent,
        preferences,
        rain_forecast=rainy,
        engagement=engagement,
        today=today,
    )
    return ranked[0] if ranked else None


def _message(reason_sentence: str, alternative: RankedActivity | None) -> str:
    return f"{reason_sentence} " + (
        f'"{alternative.candidate.title}" looks like a similar option, if you would '
        "like it instead."
        if alternative is not None
        else "I could not find anything similar for that day. Nothing has been "
        "changed, and this is just to let you know."
    )


def notices_for(
    planned: list[PlannedActivity],
    catalogue: list[ActivityCandidate],
    preferences: ActivityPreferences,
    *,
    today: date,
    rainy: bool = False,
    engagement: Mapping[str, ActivityEngagement] | None = None,
) -> list[ReplanNotice]:
    """A notice for every planned activity that can no longer happen as planned.

    `planned` is not required to have been pre-filtered: a plan whose listing is still available
    and not full, on a dry day or already indoors, produces no notice at all -- an unremarkable
    plan is not something the person needs to be told about again. Only entries for today or later
    are considered; a plan for a day already past is history, not something to replan.
    """
    notices: list[ReplanNotice] = []
    for entry in planned:
        if entry.day < today:
            continue

        fresh = _find(catalogue, entry.activity.activity_id)
        weather_turned = (
            rainy and entry.day == today and entry.activity.indoor_outdoor == IndoorOutdoor.OUTDOOR
        )
        reason = _reason(fresh=fresh, weather_turned=weather_turned)
        if reason is None:
            continue

        alternative = alternative_for(
            entry,
            catalogue,
            preferences,
            today=today,
            prefer_indoors=weather_turned,
            rainy=rainy,
            engagement=engagement,
        )
        sentence = sentence_for(reason, entry.activity.title)
        notices.append(
            ReplanNotice(
                plan_id=entry.plan_id,
                original_title=entry.activity.title,
                reason=sentence,
                reason_code=reason,
                alternative=alternative,
                message=_message(sentence, alternative),
            )
        )
    return notices


def notice_for_offer(
    offer: ReplanOffer,
    entry: PlannedActivity,
    catalogue: list[ActivityCandidate],
    preferences: ActivityPreferences,
    *,
    today: date,
    rainy: bool = False,
    engagement: Mapping[str, ActivityEngagement] | None = None,
) -> ReplanNotice:
    """The notice for an offer the server already recorded.

    The reason is not re-derived here: it is the one the world change itself wrote down, so a
    notice cannot quietly change its story between two reads, and an offer made because the
    forecast turned can never come back as "fully booked". Only the alternative is recomputed --
    a listing that filled up since the offer was made must not still be handed to someone -- and
    the one the offer named is preferred while it is still genuinely available.
    """
    alternative = alternative_for(
        entry,
        catalogue
        if offer.alternative_activity_id is None
        else _prefer(catalogue, offer.alternative_activity_id),
        preferences,
        today=today,
        prefer_indoors=offer.reason == ReplanReason.WEATHER,
        rainy=rainy,
        engagement=engagement,
    )
    sentence = sentence_for(offer.reason, entry.activity.title)
    return ReplanNotice(
        plan_id=entry.plan_id,
        original_title=entry.activity.title,
        reason=sentence,
        reason_code=offer.reason,
        alternative=alternative,
        message=_message(sentence, alternative),
        offer_id=offer.offer_id,
    )


def _prefer(catalogue: list[ActivityCandidate], activity_id: str) -> list[ActivityCandidate]:
    """The catalogue narrowed to the listing an offer named, when it is still in it.

    Narrowing rather than reordering is what keeps `alternative_for` the only judge of whether a
    listing may be offered at all: if the named one no longer survives that filter (it has since
    filled up, the person has since said "not for me"), the caller falls back to ranking the whole
    catalogue rather than pushing a listing past a gate it would now fail.
    """
    named = [candidate for candidate in catalogue if candidate.activity_id == activity_id]
    return named or catalogue
