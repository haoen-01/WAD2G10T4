"""The replanning loop, once it is a recorded offer rather than a recomputed read view.

Audit F finding 8 (reproduced as R7) and audit J finding F-J-A, pinned at the repository level:

  * `advance()` writes a `ReplanOfferRow` in the same transaction as the change that invalidated
    the plan, and audits `replan_offered` there;
  * the plan it looks at belongs to the *active run*, so a dead run's outing -- which a reset
    leaves inside the live week again -- cannot steer which listing the live story marks full;
  * `weather_turns` never touches `availability`: the senior is told the forecast turned, never
    that their outing is "fully booked", because it is not.

`tests/test_replanning.py` covers the pure module. This one is about what is persisted.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from silverloop.db_models import ActivityCandidateRow, ReplanOfferRow, WeekPlanEntryRow
from silverloop.local_time import local_date
from silverloop.models import ActivityAvailability, ReplanReason, ReplanResolution
from silverloop.sql_repository import SqlAlchemyRepository

# The seeded fixture catalogue, anchored to the reset day (2026-08-18). Named rather than
# discovered so each test says plainly which listing it is about.
GARDENING_DAY = date(2026, 8, 19)  # activity-gardening-1, outdoor
CHAIR_DAY = date(2026, 8, 21)  # activity-chair-mobility-2, indoor, later in the week


@pytest.fixture
def repo() -> SqlAlchemyRepository:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()
    instance.reset()
    return instance


def _offers(repository: SqlAlchemyRepository) -> list[ReplanOfferRow]:
    with repository.sessions() as session:
        return list(session.scalars(select(ReplanOfferRow).order_by(ReplanOfferRow.offer_id)).all())


def _availability(repository: SqlAlchemyRepository) -> dict[str, str]:
    """Every listing's availability, so a test can say that nothing at all changed."""
    with repository.sessions() as session:
        return {
            row.activity_id: row.availability
            for row in session.scalars(select(ActivityCandidateRow))
        }


def _plan_ids(repository: SqlAlchemyRepository) -> dict[str, str]:
    """`activity_id -> plan_id` across every run, so a test can name the dead run's own plan."""
    with repository.sessions() as session:
        return {
            row.activity_id: row.plan_id
            for row in session.scalars(select(WeekPlanEntryRow).order_by(WeekPlanEntryRow.day))
        }


# ── The offer is written where the change is ──────────────────────────────────────────────────


def test_a_full_programme_writes_one_offer_and_audits_it(repo: SqlAlchemyRepository) -> None:
    repo.plan_activity("activity-gardening-1", GARDENING_DAY, "senior")

    repo.advance("programme_becomes_full", event_id="full-1")

    offers = _offers(repo)
    assert len(offers) == 1
    offer = offers[0]
    assert offer.reason == ReplanReason.FULL.value
    assert offer.resolution is None
    assert offer.alternative_activity_id is not None

    offered = [event for event in repo.list_events() if event.event_type == "replan_offered"]
    assert len(offered) == 1
    assert offered[0].detail["offer_id"] == offer.offer_id
    assert offered[0].detail["reason_code"] == ReplanReason.FULL.value
    assert offered[0].detail["activity_id"] == "activity-gardening-1"
    assert offered[0].detail["alternative_rank_basis"] == "deterministic"


def test_the_event_fills_the_plan_for_the_next_simulated_day_and_offers_that_days_alternative(
    repo: SqlAlchemyRepository,
) -> None:
    """The story the event exists to tell: the outing the person is about to go to has filled up.

    It is their own plan that changes, on the day it is about -- a later plan in the same week is
    not the news -- and the replacement offered is for that same day, because `alternative_for`
    restates the plan's own date and time of day. When the day has one, the person is told about
    it; "I could not find anything similar" is the honest answer only when the day genuinely has
    nothing, which is what makes this branch worth pinning.
    """
    repo.plan_activity("activity-gardening-1", GARDENING_DAY, "senior")
    repo.plan_activity("activity-chair-mobility-2", CHAIR_DAY, "senior")

    repo.advance("programme_becomes_full", event_id="full-1")

    assert repo.get_activity("activity-gardening-1").availability == ActivityAvailability.FULL
    assert repo.get_activity("activity-chair-mobility-2").availability == (
        ActivityAvailability.AVAILABLE
    )
    notices = repo.replan_notices()
    assert len(notices) == 1
    alternative = notices[0].alternative
    assert alternative is not None
    assert alternative.candidate.start_at is not None
    assert local_date(alternative.candidate.start_at) == GARDENING_DAY
    assert "looks like a similar option" in notices[0].message


def test_with_nothing_planned_the_event_changes_no_listing_at_all(
    repo: SqlAlchemyRepository,
) -> None:
    """No plan, no news: the event never reaches for a listing of its own to fill, because a
    listing the person had nothing to do with filling up is not something to tell them about."""
    before = _availability(repo)

    repo.advance("programme_becomes_full", event_id="full-1")

    assert _availability(repo) == before
    assert _offers(repo) == []
    assert repo.replan_notices() == []


def test_the_notice_carries_the_offer_it_belongs_to(repo: SqlAlchemyRepository) -> None:
    """Before the offer store, a notice had no id at all -- which is why "no thanks" could only
    ever be browser state."""
    repo.plan_activity("activity-gardening-1", GARDENING_DAY, "senior")
    repo.advance("programme_becomes_full", event_id="full-1")

    notices = repo.replan_notices()

    assert len(notices) == 1
    assert notices[0].offer_id == _offers(repo)[0].offer_id
    assert notices[0].reason_code == ReplanReason.FULL


def test_the_same_change_on_a_later_day_does_not_offer_the_same_thing_twice(
    repo: SqlAlchemyRepository,
) -> None:
    """The reappearing-notice half of audit F finding 8: the notice was recomputed on every read
    and every advance, so it came back however often it was answered."""
    repo.plan_activity("activity-chair-mobility-2", CHAIR_DAY, "senior")
    repo.advance("programme_becomes_full", event_id="full-1")
    repo.advance("recovery", event_id="recovery-1")

    assert len(_offers(repo)) == 1
    assert len(repo.replan_notices()) == 1


def test_an_offer_whose_day_has_passed_is_closed_rather_than_left_open(
    repo: SqlAlchemyRepository,
) -> None:
    repo.plan_activity("activity-gardening-1", GARDENING_DAY, "senior")
    repo.advance("programme_becomes_full", event_id="full-1")
    assert repo.replan_notices()

    repo.advance("recovery", event_id="recovery-1")
    repo.advance("recovery", event_id="recovery-2")

    offer = _offers(repo)[0]
    assert offer.resolution == ReplanResolution.EXPIRED.value
    assert offer.resolved_at is not None
    assert repo.replan_notices() == []


# ── Weather is weather, not a fabricated catalogue fact ───────────────────────────────────────


def test_weather_never_marks_a_listing_full(repo: SqlAlchemyRepository) -> None:
    """Audit J finding F-J-A: `weather_turns` used to flip the listing's `availability` to FULL,
    which is a catalogue fact standing in for a context one -- and the senior read it as "fully
    booked"."""
    repo.plan_activity("activity-gardening-1", GARDENING_DAY, "senior")

    repo.advance("weather_turns", event_id="weather-1")

    assert repo.get_activity("activity-gardening-1").availability == ActivityAvailability.AVAILABLE


def test_weather_offers_a_weather_reason_and_says_the_forecast_turned(
    repo: SqlAlchemyRepository,
) -> None:
    repo.plan_activity("activity-gardening-1", GARDENING_DAY, "senior")

    repo.advance("weather_turns", event_id="weather-1")

    offers = _offers(repo)
    assert [offer.reason for offer in offers] == [ReplanReason.WEATHER.value]
    notices = repo.replan_notices()
    assert len(notices) == 1
    assert notices[0].reason_code == ReplanReason.WEATHER
    assert "forecast" in notices[0].reason
    assert "booked" not in notices[0].message


def test_weather_leaves_an_indoor_plan_alone(repo: SqlAlchemyRepository) -> None:
    repo.plan_activity("activity-chair-mobility-1", GARDENING_DAY, "senior")

    repo.advance("weather_turns", event_id="weather-1")

    assert _offers(repo) == []
    assert repo.replan_notices() == []


# ── A dead run's plan is not the live run's business ──────────────────────────────────────────


def test_a_dead_runs_plan_cannot_steer_which_listing_is_marked_full(
    repo: SqlAlchemyRepository,
) -> None:
    """The run-scoping defect the week-plan work found next door, in `advance()` itself.

    A reset rewinds the simulated calendar to the fixture's anchor day, so a dead run's plan falls
    inside the live week again. Selected person-scoped and ordered by day, the dead run's earlier
    outing won -- so the event the senior triggered filled up a listing they had nothing planned
    for and left the plan they *did* have untouched, with no notice at all.
    """
    repo.plan_activity("activity-gardening-1", GARDENING_DAY, "senior")
    dead_plan_id = _plan_ids(repo)["activity-gardening-1"]

    repo.reset()
    repo.plan_activity("activity-chair-mobility-2", CHAIR_DAY, "senior")

    repo.advance("programme_becomes_full", event_id="full-1")

    assert repo.get_activity("activity-chair-mobility-2").availability == ActivityAvailability.FULL
    assert repo.get_activity("activity-gardening-1").availability == ActivityAvailability.AVAILABLE
    offers = _offers(repo)
    assert [offer.plan_id for offer in offers] != [dead_plan_id]
    assert len(offers) == 1
    assert offers[0].plan_id != dead_plan_id


def test_a_dead_runs_plan_is_never_offered_a_replacement(repo: SqlAlchemyRepository) -> None:
    repo.plan_activity("activity-gardening-1", GARDENING_DAY, "senior")
    repo.reset()

    repo.advance("programme_becomes_full", event_id="full-1")

    assert _offers(repo) == []
    assert repo.replan_notices() == []
