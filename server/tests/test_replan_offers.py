"""The replanning loop, once it is a recorded offer rather than a recomputed read view.

Audit F finding 8 (reproduced as R7) and audit J finding F-J-A, pinned at the repository level:

  * `advance()` writes a `ReplanOfferRow` in the same transaction as the change that invalidated
    the plan, and audits `replan_offered` there;
  * the plan it looks at belongs to the *active run*, so a dead run's outing -- which a reset
    leaves inside the live week again -- cannot steer which listing the live story marks full;
  * `weather_turns` never touches `availability`: the senior is told the forecast turned, never
    that their outing is "fully booked", because it is not.

`tests/test_replanning.py` covers the pure module. This one is about what is persisted. The
plans themselves are stored as rows (`tests/row_fixtures.py`): the week routes that wrote them, and
the notice read view over the offers, went in step 7. What `advance` writes is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from silverloop.context import ContextEvidence, ExternalContext
from silverloop.db_models import ActivityCandidateRow, ReplanOfferRow, WeekPlanEntryRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.local_time import local_date
from silverloop.models import (
    ActivityAvailability,
    ContextSignal,
    ReplanReason,
    ReplanResolution,
)
from silverloop.sql_repository import SqlAlchemyRepository
from tests.row_fixtures import active_run_id, audit_events, plan_activity

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


def _availability_of(repository: SqlAlchemyRepository, activity_id: str) -> ActivityAvailability:
    return ActivityAvailability(_availability(repository)[activity_id])


def _open_offers(repository: SqlAlchemyRepository) -> list[ReplanOfferRow]:
    """The live run's offers still awaiting an answer, for a plan whose day has not passed --
    the offers the removed notice read view (`replan_notices`) turned into notices."""
    run_id = active_run_id(repository, DEMO_PERSON_ID)
    today = repository.person_state().current_day
    with repository.sessions() as session:
        offers = session.scalars(
            select(ReplanOfferRow)
            .where(ReplanOfferRow.run_id == run_id, ReplanOfferRow.resolution.is_(None))
            .order_by(ReplanOfferRow.offered_at, ReplanOfferRow.offer_id)
        ).all()
        return [
            offer
            for offer in offers
            if (plan := session.get(WeekPlanEntryRow, offer.plan_id)) is not None
            and plan.replaced_reason is None
            and plan.day >= today
        ]


def _start_day(repository: SqlAlchemyRepository, activity_id: str) -> date:
    with repository.sessions() as session:
        listing = session.get(ActivityCandidateRow, activity_id)
        assert listing is not None and listing.start_at is not None
        return local_date(listing.start_at)


def _plan(repository: SqlAlchemyRepository, activity_id: str, day: date) -> None:
    plan_activity(repository, activity_id, day, person_id=DEMO_PERSON_ID)


def _plan_ids(repository: SqlAlchemyRepository) -> dict[str, str]:
    """`activity_id -> plan_id` across every run, so a test can name the dead run's own plan."""
    with repository.sessions() as session:
        return {
            row.activity_id: row.plan_id
            for row in session.scalars(select(WeekPlanEntryRow).order_by(WeekPlanEntryRow.day))
        }


# ── The offer is written where the change is ──────────────────────────────────────────────────


def test_a_full_programme_writes_one_offer_and_audits_it(repo: SqlAlchemyRepository) -> None:
    _plan(repo, "activity-gardening-1", GARDENING_DAY)

    repo.advance("programme_becomes_full", event_id="full-1")

    offers = _offers(repo)
    assert len(offers) == 1
    offer = offers[0]
    assert offer.reason == ReplanReason.FULL.value
    assert offer.resolution is None
    assert offer.alternative_activity_id is not None

    offered = [
        event
        for event in audit_events(repo, person_id=DEMO_PERSON_ID)
        if event.event_type == "replan_offered"
    ]
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
    _plan(repo, "activity-gardening-1", GARDENING_DAY)
    _plan(repo, "activity-chair-mobility-2", CHAIR_DAY)

    repo.advance("programme_becomes_full", event_id="full-1")

    assert _availability_of(repo, "activity-gardening-1") == ActivityAvailability.FULL
    assert _availability_of(repo, "activity-chair-mobility-2") == (ActivityAvailability.AVAILABLE)
    offers = _open_offers(repo)
    assert len(offers) == 1
    alternative_id = offers[0].alternative_activity_id
    assert alternative_id is not None
    assert _start_day(repo, alternative_id) == GARDENING_DAY


def test_with_nothing_planned_the_event_changes_no_listing_at_all(
    repo: SqlAlchemyRepository,
) -> None:
    """No plan, no news: the event never reaches for a listing of its own to fill, because a
    listing the person had nothing to do with filling up is not something to tell them about."""
    before = _availability(repo)

    repo.advance("programme_becomes_full", event_id="full-1")

    assert _availability(repo) == before
    assert _offers(repo) == []
    assert _open_offers(repo) == []


def test_the_same_change_on_a_later_day_does_not_offer_the_same_thing_twice(
    repo: SqlAlchemyRepository,
) -> None:
    """The reappearing-notice half of audit F finding 8: the notice was recomputed on every read
    and every advance, so it came back however often it was answered."""
    _plan(repo, "activity-chair-mobility-2", CHAIR_DAY)
    repo.advance("programme_becomes_full", event_id="full-1")
    repo.advance("recovery", event_id="recovery-1")

    assert len(_offers(repo)) == 1
    assert len(_open_offers(repo)) == 1


def test_an_offer_whose_day_has_passed_is_closed_rather_than_left_open(
    repo: SqlAlchemyRepository,
) -> None:
    _plan(repo, "activity-gardening-1", GARDENING_DAY)
    repo.advance("programme_becomes_full", event_id="full-1")
    assert _open_offers(repo)

    repo.advance("recovery", event_id="recovery-1")
    repo.advance("recovery", event_id="recovery-2")

    offer = _offers(repo)[0]
    assert offer.resolution == ReplanResolution.EXPIRED.value
    assert offer.resolved_at is not None
    assert _open_offers(repo) == []


# ── Weather is weather, not a fabricated catalogue fact ───────────────────────────────────────


def test_weather_never_marks_a_listing_full(repo: SqlAlchemyRepository) -> None:
    """Audit J finding F-J-A: `weather_turns` used to flip the listing's `availability` to FULL,
    which is a catalogue fact standing in for a context one -- and the senior read it as "fully
    booked"."""
    _plan(repo, "activity-gardening-1", GARDENING_DAY)

    repo.advance("weather_turns", event_id="weather-1")

    assert _availability_of(repo, "activity-gardening-1") == ActivityAvailability.AVAILABLE


def test_weather_offers_a_weather_reason(
    repo: SqlAlchemyRepository,
) -> None:
    _plan(repo, "activity-gardening-1", GARDENING_DAY)

    repo.advance("weather_turns", event_id="weather-1")

    offers = _offers(repo)
    assert [offer.reason for offer in offers] == [ReplanReason.WEATHER.value]
    assert [offer.reason for offer in _open_offers(repo)] == [ReplanReason.WEATHER.value]


def test_weather_leaves_an_indoor_plan_alone(repo: SqlAlchemyRepository) -> None:
    _plan(repo, "activity-chair-mobility-1", GARDENING_DAY)

    repo.advance("weather_turns", event_id="weather-1")

    assert _offers(repo) == []
    assert _open_offers(repo) == []


# ── Live rain only moves the sessions its reading or forecast covers ───────────────────────────

# activity-gardening-1 starts 2026-08-19 01:00 UTC (9 am in Singapore).
GARDENING_STARTS = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)
# The real clock: 8:30 am in Singapore on that same day, so live weather speaks for it.
LIVE_MORNING = datetime(2026, 8, 19, 0, 30, tzinfo=UTC)


@dataclass
class _LiveRain:
    """A stand-in context provider reporting current live rain until `until`."""

    until: datetime

    def fetch(self, as_of: datetime) -> ExternalContext:
        return ExternalContext(
            signal=ContextSignal(
                rainy=True,
                note="Live rain (test).",
                weather_source="live",
                weather_valid_until=self.until,
            ),
            evidence=[
                ContextEvidence(
                    source="nea_weather_live",
                    observed_at=LIVE_MORNING,
                    expires_at=self.until,
                    confidence=0.95,
                    evidence_id="E-TEST-LIVE-RAIN",
                    payload={"available": True},
                )
            ],
        )


def _live_repo(monkeypatch: pytest.MonkeyPatch, until: datetime) -> SqlAlchemyRepository:
    monkeypatch.setattr("silverloop.sql_repository._utcnow", lambda: LIVE_MORNING)
    instance = SqlAlchemyRepository(
        "sqlite+pysqlite:///:memory:", context_provider=_LiveRain(until)
    )
    instance.create_schema_for_tests()
    instance.reset()
    _plan(instance, "activity-gardening-1", GARDENING_DAY)
    return instance


@pytest.mark.parametrize(
    ("until", "offered"),
    [
        (datetime(2026, 8, 19, 0, 45, tzinfo=UTC), False),  # the rain is over before it starts
        (GARDENING_STARTS, True),  # it starts the very moment the reading stops speaking
        (datetime(2026, 8, 19, 2, 0, tzinfo=UTC), True),  # the rain runs into it
    ],
)
def test_live_rain_offers_a_replan_only_for_an_outdoor_session_it_covers(
    monkeypatch: pytest.MonkeyPatch, until: datetime, offered: bool
) -> None:
    repository = _live_repo(monkeypatch, until)

    response = repository.advance("activity_declines", event_id="live-rain-replan")

    context = response.state.signal.context
    assert (context.rainy, context.weather_source, context.weather_valid_until) == (
        True,
        "live",
        until,
    )
    expected = [ReplanReason.WEATHER.value] if offered else []
    assert [offer.reason for offer in _offers(repository)] == expected


def test_simulated_rain_still_covers_the_whole_day_whatever_live_weather_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Live rain that ended before the session would not move it; the scripted rain does.
    repository = _live_repo(monkeypatch, datetime(2026, 8, 19, 0, 45, tzinfo=UTC))

    response = repository.advance("weather_turns", event_id="simulated-rain-replan")

    context = response.state.signal.context
    assert (context.rainy, context.weather_source, context.weather_valid_until) == (
        True,
        "simulated",
        None,
    )
    assert [offer.reason for offer in _offers(repository)] == [ReplanReason.WEATHER.value]


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
    _plan(repo, "activity-gardening-1", GARDENING_DAY)
    dead_plan_id = _plan_ids(repo)["activity-gardening-1"]

    repo.reset()
    _plan(repo, "activity-chair-mobility-2", CHAIR_DAY)

    repo.advance("programme_becomes_full", event_id="full-1")

    assert _availability_of(repo, "activity-chair-mobility-2") == ActivityAvailability.FULL
    assert _availability_of(repo, "activity-gardening-1") == ActivityAvailability.AVAILABLE
    offers = _offers(repo)
    assert [offer.plan_id for offer in offers] != [dead_plan_id]
    assert len(offers) == 1
    assert offers[0].plan_id != dead_plan_id


def test_a_dead_runs_plan_is_never_offered_a_replacement(repo: SqlAlchemyRepository) -> None:
    _plan(repo, "activity-gardening-1", GARDENING_DAY)
    repo.reset()

    repo.advance("programme_becomes_full", event_id="full-1")

    assert _offers(repo) == []
    assert _open_offers(repo) == []
