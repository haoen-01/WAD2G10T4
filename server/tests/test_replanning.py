"""Replanning: the world changed, and the person is told plainly with a genuine alternative.

Mirrors `test_activity_search.py`'s discipline: an alternative is only ever something that
survived the same `filter_candidates`/`rank_candidates` path everything else in the product uses,
never a value this module invented.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from silverloop.models import (
    ActivityAvailability,
    ActivityCandidate,
    ActivityLocation,
    ActivityPreferences,
    ActivitySource,
    IndoorOutdoor,
    IntegrationStatus,
    PlannedActivity,
)
from silverloop.replanning import notices_for

NOW = datetime(2026, 9, 6, 9, 0, tzinfo=UTC)
TODAY = date(2026, 9, 6)
NO_PREFERENCES = ActivityPreferences(person_id="p1", dimensions=[])


def _candidate(**overrides: object) -> ActivityCandidate:
    defaults: dict[str, object] = dict(
        activity_id="act-1",
        source=ActivitySource.AAC_FIXTURE,
        integration_status=IntegrationStatus.FIXTURE,
        title="Morning tai chi",
        provider="Community Centre",
        location=ActivityLocation(name="Community Centre"),
        category="tai chi",
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        availability=ActivityAvailability.AVAILABLE,
        retrieved_at=NOW,
        distance_m=500,
        start_at=datetime(2026, 9, 6, 9, 0, tzinfo=UTC),
    )
    defaults.update(overrides)
    return ActivityCandidate(**defaults)


def _plan(
    activity: ActivityCandidate, *, day: date = TODAY, plan_id: str = "plan-1"
) -> PlannedActivity:
    return PlannedActivity(plan_id=plan_id, day=day, activity=activity)


# ── No notice when nothing changed ────────────────────────────────────────────────────────────


def test_still_available_and_dry_produces_no_notice() -> None:
    original = _candidate()
    planned = [_plan(original)]
    catalogue = [original]
    assert notices_for(planned, catalogue, NO_PREFERENCES, today=TODAY) == []


def test_a_past_dated_plan_is_never_replanned() -> None:
    original = _candidate()
    planned = [_plan(original, day=date(2026, 9, 1))]
    # Not even in the catalogue any more -- still no notice, because the day has passed.
    assert notices_for(planned, [], NO_PREFERENCES, today=TODAY) == []


# ── Became full ────────────────────────────────────────────────────────────────────────────────


def test_a_full_listing_produces_a_notice_naming_it() -> None:
    original = _candidate()
    planned = [_plan(original)]
    now_full = _candidate(availability=ActivityAvailability.FULL)
    notices = notices_for(planned, [now_full], NO_PREFERENCES, today=TODAY)

    assert len(notices) == 1
    notice = notices[0]
    assert notice.plan_id == "plan-1"
    assert notice.original_title == "Morning tai chi"
    assert "fully booked" in notice.reason


def test_a_full_listing_with_a_real_alternative_offers_it() -> None:
    original = _candidate()
    now_full = _candidate(availability=ActivityAvailability.FULL)
    alternative = _candidate(
        activity_id="act-2",
        title="Chair yoga",
        start_at=datetime(2026, 9, 6, 9, 30, tzinfo=UTC),
    )
    notices = notices_for([_plan(original)], [now_full, alternative], NO_PREFERENCES, today=TODAY)

    assert len(notices) == 1
    assert notices[0].alternative is not None
    assert notices[0].alternative.candidate.activity_id == "act-2"
    assert "Chair yoga" in notices[0].message


def test_no_survivable_alternative_is_an_honest_none_not_an_error() -> None:
    original = _candidate()
    now_full = _candidate(availability=ActivityAvailability.FULL)
    notices = notices_for([_plan(original)], [now_full], NO_PREFERENCES, today=TODAY)

    assert notices[0].alternative is None
    assert "could not find anything similar" in notices[0].message


def test_a_delisted_activity_is_distinguished_from_a_full_one() -> None:
    original = _candidate()
    notices = notices_for([_plan(original)], [], NO_PREFERENCES, today=TODAY)

    assert len(notices) == 1
    assert "no longer being offered" in notices[0].reason


# ── Weather ────────────────────────────────────────────────────────────────────────────────────


def test_rain_against_an_outdoor_plan_today_produces_a_notice() -> None:
    outdoor = _candidate(indoor_outdoor=IndoorOutdoor.OUTDOOR)
    notices = notices_for([_plan(outdoor)], [outdoor], NO_PREFERENCES, today=TODAY, rainy=True)

    assert len(notices) == 1
    assert "forecast" in notices[0].reason


def test_live_rain_only_replans_an_outdoor_session_the_forecast_covers() -> None:
    # The session starts at 09:00 UTC (5 pm in Singapore).
    outdoor = _candidate(indoor_outdoor=IndoorOutdoor.OUTDOOR)
    ends_before = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
    ends_after = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)

    def notices(rain_until: datetime | None) -> int:
        return len(
            notices_for(
                [_plan(outdoor)],
                [outdoor],
                NO_PREFERENCES,
                today=TODAY,
                rainy=True,
                rain_until=rain_until,
            )
        )

    assert notices(ends_before) == 0  # the rain the forecast speaks of is over by then
    assert notices(ends_after) == 1
    assert notices(None) == 1  # simulated rain covers the whole day


def test_rain_never_flags_an_indoor_plan() -> None:
    indoor = _candidate(indoor_outdoor=IndoorOutdoor.INDOOR)
    notices = notices_for([_plan(indoor)], [indoor], NO_PREFERENCES, today=TODAY, rainy=True)
    assert notices == []


def test_rain_only_matters_for_todays_plan_not_a_future_one() -> None:
    outdoor = _candidate(start_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC))
    planned = [_plan(outdoor, day=date(2026, 9, 8))]
    notices = notices_for(planned, [outdoor], NO_PREFERENCES, today=TODAY, rainy=True)
    assert notices == []


def test_a_full_reason_takes_precedence_over_a_weather_reason() -> None:
    """A single reason per notice, mirroring `activity_search.filter_candidates`'s own rule."""
    now_full_outdoor = _candidate(availability=ActivityAvailability.FULL)
    notices = notices_for(
        [_plan(_candidate())], [now_full_outdoor], NO_PREFERENCES, today=TODAY, rainy=True
    )
    assert len(notices) == 1
    assert "fully booked" in notices[0].reason
    assert "forecast" not in notices[0].reason


# ── Never swaps anything ──────────────────────────────────────────────────────────────────────


def test_notices_for_never_mutates_the_planned_list() -> None:
    original = _candidate()
    planned = [_plan(original)]
    now_full = _candidate(availability=ActivityAvailability.FULL)
    notices_for(planned, [now_full], NO_PREFERENCES, today=TODAY)

    assert planned[0].activity.activity_id == "act-1"
    assert planned[0].origin == "chosen"


# ── The replacement honours the person's own recent "not for me" ──────────────────────────────


def test_a_recently_declined_listing_is_not_offered_as_the_replacement() -> None:
    from silverloop.activity_search import ActivityEngagement

    original = _candidate()
    now_full = _candidate(availability=ActivityAvailability.FULL)
    declined = _candidate(
        activity_id="act-2",
        title="Chair yoga",
        start_at=datetime(2026, 9, 6, 9, 30, tzinfo=UTC),
    )
    other = _candidate(
        activity_id="act-3",
        title="Line dancing",
        distance_m=900,
        start_at=datetime(2026, 9, 6, 10, 0, tzinfo=UTC),
    )
    engagement = {"act-2": ActivityEngagement(not_for_me=1, last_not_for_me=TODAY)}
    notices = notices_for(
        [_plan(original)],
        [now_full, declined, other],
        NO_PREFERENCES,
        today=TODAY,
        engagement=engagement,
    )
    assert notices[0].alternative is not None
    assert notices[0].alternative.candidate.activity_id == "act-3"
    # Without the engagement the nearer, declined listing would have been chosen.
    without = notices_for(
        [_plan(original)], [now_full, declined, other], NO_PREFERENCES, today=TODAY
    )
    assert without[0].alternative is not None
    assert without[0].alternative.candidate.activity_id == "act-2"
