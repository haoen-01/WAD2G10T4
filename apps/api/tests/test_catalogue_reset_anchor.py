"""A `reset()` rewinds the simulated calendar, and the activity catalogue comes back with it.

The catalogue is global and outlives every run, which is right -- listings are fixture reference
data, not one person's state, and `week_plan_entries.activity_id` / `activity_offer_responses`
point at them. But two things move a listing while a story plays: `_refresh_stale_activities` rolls
a session forward in whole weeks once a simulated day passes it, and `programme_becomes_full` flips
one to FULL. `reset()` already put `availability` back (`_seed_activity_candidates` refreshes it
from the fixture), and until `_reanchor_fixture_sessions` existed it did not put `start_at` back at
all -- so a reset rewound `current_day` to the fixture's anchor day and left the whole catalogue a
week or more ahead of a calendar that had gone back to the start.

Found by running two browser specs in one Playwright process: `product-loop.spec.ts` advances
several simulated days, and the reset at the top of `replan-loop.spec.ts` then handed it a
catalogue with nothing on "tomorrow" -- "something outdoors tomorrow" matched nothing and all three
of its tests failed, while the same file passed on its own. These tests pin the repository-level
behaviour underneath that, including what the re-anchor must *not* touch.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from silverloop.db_models import (
    ActivityCandidateRow,
    ActivityDimensionPreferenceRow,
    ScenarioRunRow,
)
from silverloop.fixtures import DEMO_PERSON_ID, synthetic_activity_candidates
from silverloop.local_time import local_date
from silverloop.models import (
    ActivityAvailability,
    ActivitySource,
    IntegrationStatus,
    PreferenceDimension,
    PreferenceStance,
)
from silverloop.sql_repository import (
    _FIXTURE_METADATA_SOURCE,
    SqlAlchemyRepository,
    _as_utc,
)

_ADVANCED_DAYS = 8


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def _current_day(repository: SqlAlchemyRepository) -> date:
    with repository.sessions() as session:
        run = session.scalar(
            select(ScenarioRunRow).where(
                ScenarioRunRow.active.is_(True), ScenarioRunRow.person_id == DEMO_PERSON_ID
            )
        )
        assert run is not None
        return run.current_day


def _catalogue(repository: SqlAlchemyRepository) -> dict[str, tuple[datetime | None, str]]:
    with repository.sessions() as session:
        rows = session.scalars(
            select(ActivityCandidateRow).order_by(ActivityCandidateRow.activity_id)
        ).all()
        # SQLite hands back naive datetimes; compare on the same footing as the repository's
        # own readers, which normalise through `_as_utc`.
        return {
            row.activity_id: (
                _as_utc(row.start_at) if row.start_at is not None else None,
                row.availability,
            )
            for row in rows
        }


def _advance_days(repository: SqlAlchemyRepository, count: int, tag: str) -> None:
    for index in range(count):
        repository.advance("recovery", event_id=f"{tag}-{index}")


def test_a_reset_puts_tomorrows_listings_back_on_tomorrow() -> None:
    """The failure the browser suite hit, at the repository level.

    Fails before `_reanchor_fixture_sessions`: after eight days and a reset, nothing sits on the
    day after the anchor at all, because every listing had been rolled a whole week forward.
    """
    repository = _repo()
    try:
        anchor_day = _current_day(repository)
        before = _catalogue(repository)
        tomorrow_at_anchor = {
            activity_id
            for activity_id, (start_at, _) in before.items()
            if start_at is not None and local_date(start_at) == anchor_day + timedelta(days=1)
        }
        assert tomorrow_at_anchor, (
            "the fixture catalogue must put something on the day after the anchor"
        )

        _advance_days(repository, _ADVANCED_DAYS, "reanchor")
        assert _current_day(repository) == anchor_day + timedelta(days=_ADVANCED_DAYS)

        repository.reset()

        assert _current_day(repository) == anchor_day
        after = _catalogue(repository)
        tomorrow_after_reset = {
            activity_id
            for activity_id, (start_at, _) in after.items()
            if start_at is not None and local_date(start_at) == anchor_day + timedelta(days=1)
        }
        assert tomorrow_after_reset == tomorrow_at_anchor
        # Not merely the same day: the same session, to the minute, and the same listing rows.
        assert after == before
    finally:
        repository.close()


def test_a_reset_restores_a_listing_the_simulator_marked_full() -> None:
    """`programme_becomes_full` is a catalogue change; a story restart puts the catalogue back.

    A regression guard, not a fix: `_seed_activity_candidates` already refreshed `availability`
    from the fixture on every reset, so this passed before `_reanchor_fixture_sessions` too. It is
    pinned here because the two mutations `advance()` makes to a listing -- its session time and
    its availability -- have to come back together, and only one of them ever did.
    """
    repository = _repo()
    try:
        anchor_day = _current_day(repository)
        before = _catalogue(repository)
        planned_id = next(
            activity_id
            for activity_id, (start_at, availability) in sorted(before.items())
            if start_at is not None
            and local_date(start_at) > anchor_day
            and availability != ActivityAvailability.FULL.value
        )
        repository.plan_activity(planned_id, local_date(before[planned_id][0]), actor="senior")

        repository.advance("programme_becomes_full", event_id="full-1")
        flipped = _catalogue(repository)[planned_id][1]
        assert flipped == ActivityAvailability.FULL.value, (
            "the simulator must actually have flipped the planned listing for this to test anything"
        )

        repository.reset()

        assert _catalogue(repository)[planned_id][1] == before[planned_id][1]
    finally:
        repository.close()


def test_a_reset_never_deletes_a_listing_or_changes_an_activity_id() -> None:
    """Plans and offer responses point at these rows by id: the re-anchor moves time, not
    identity."""
    repository = _repo()
    try:
        ids_before = set(_catalogue(repository))
        _advance_days(repository, _ADVANCED_DAYS, "identity")
        repository.reset()

        assert set(_catalogue(repository)) == ids_before
        with repository.sessions() as session:
            assert session.scalar(select(func.count()).select_from(ActivityCandidateRow)) == len(
                ids_before
            )
    finally:
        repository.close()


def test_a_reset_leaves_a_listing_that_is_not_fixture_data_where_it_is() -> None:
    """A row from a real feed is a fact about the world, not about this story.

    Its session time was never anchored to the simulated calendar, so rewinding that calendar must
    not move it -- and it must not be deleted for being absent from the fixture set either.
    """
    repository = _repo()
    try:
        anchor_day = _current_day(repository)
        partner_start = datetime.combine(
            anchor_day + timedelta(days=3), datetime.min.time(), tzinfo=UTC
        ).replace(hour=2, minute=15)
        with repository.sessions.begin() as session:
            session.add(
                ActivityCandidateRow(
                    activity_id="activity-partner-feed-1",
                    source=ActivitySource.ONEPA.value,
                    integration_status=IntegrationStatus.FUTURE_AUTHORISED.value,
                    title="Listing from an authorised feed",
                    provider="Partner feed",
                    start_at=partner_start,
                    location_name="Partner hall",
                    metadata_source="partner_feed:example",
                    retrieved_at=partner_start,
                    availability=ActivityAvailability.AVAILABLE.value,
                )
            )

        _advance_days(repository, _ADVANCED_DAYS, "partner")
        moved_by_the_clock = _catalogue(repository)["activity-partner-feed-1"][0]

        repository.reset()

        # Only `_refresh_stale_activities`' forward roll ever touched it, and the reset left that
        # alone rather than pulling it back to a fixture anchor it never had.
        assert _catalogue(repository)["activity-partner-feed-1"][0] == moved_by_the_clock
    finally:
        repository.close()


def test_a_reset_that_re_anchors_the_catalogue_still_keeps_a_standing_statement() -> None:
    """ADR 0004's rule is untouched: the re-anchor writes to the catalogue, never to a person.

    A standing `senior_statement` survives a reset; no preference row is deleted by one.
    """
    repository = _repo()
    try:
        repository.state_preference(
            PreferenceDimension.ENVIRONMENT,
            "outdoor",
            PreferenceStance.AVOID,
            stated_text="I would rather stay indoors",
            actor="senior",
        )
        with repository.sessions() as session:
            rows_before = session.scalar(
                select(func.count()).select_from(ActivityDimensionPreferenceRow)
            )
        assert rows_before == 1

        _advance_days(repository, _ADVANCED_DAYS, "preference")
        repository.reset()

        with repository.sessions() as session:
            rows_after = session.scalar(
                select(func.count()).select_from(ActivityDimensionPreferenceRow)
            )
        assert rows_after == rows_before
        preferences = repository.activity_preferences(person_id=DEMO_PERSON_ID)
        assert any(
            entry.value == "outdoor" and entry.source == "senior_statement" and entry.strength < 0
            for entry in preferences.dimensions
        )
    finally:
        repository.close()


def test_a_second_personas_reset_does_not_strand_the_persona_already_playing() -> None:
    """The catalogue is global; rewinding it for one persona must not empty another's week.

    A person outside `DEMO_PERSONAS` falls back to the generic fixture history, whose anchor day
    sits roughly eleven weeks *behind* the default persona's. A naive re-anchor moved every listing
    back to it, out of the persona already mid-story's live week, and `plan_activity` then rejected
    the only activities the catalogue had as "outside the week being planned". The rewind is
    floored at the furthest-ahead active run instead, and the whole-week roll keeps each listing on
    its own weekday.
    """
    repository = _repo()
    try:
        anchor_day = _current_day(repository)
        repository.reset(person_id="second-persona", allow_new_person=True)

        with repository.sessions() as session:
            other = session.scalar(
                select(ScenarioRunRow).where(
                    ScenarioRunRow.active.is_(True), ScenarioRunRow.person_id == "second-persona"
                )
            )
        assert other is not None and other.current_day < anchor_day, (
            "this only tests anything if the second persona's anchor is behind the first's"
        )

        catalogue = _catalogue(repository)
        week_starting = anchor_day - timedelta(days=anchor_day.weekday())
        in_the_first_personas_week = [
            activity_id
            for activity_id, (start_at, _) in catalogue.items()
            if start_at is not None
            and week_starting <= local_date(start_at) <= week_starting + timedelta(days=6)
        ]
        assert in_the_first_personas_week, (
            "the persona already playing must still have listings inside its own week"
        )
        # And they are genuinely plannable, which is the failure the regression produced.
        planned = repository.plan_activity(
            in_the_first_personas_week[0],
            local_date(catalogue[in_the_first_personas_week[0]][0]),
            actor="senior",
        )
        assert planned.entries

        # Every listing is the second persona's own fixture anchoring, moved forward by a whole
        # number of weeks and nothing else -- the roll never shifts a session's time of day or its
        # position within the week the fixture gave it.
        fixture = {
            candidate.activity_id: candidate.start_at
            for candidate in synthetic_activity_candidates(other.current_day)
            if candidate.start_at is not None
        }
        for activity_id, fixture_start in fixture.items():
            start_at = catalogue[activity_id][0]
            assert start_at is not None
            offset = start_at - fixture_start
            assert offset >= timedelta(0) and offset % timedelta(days=7) == timedelta(0)
    finally:
        repository.close()


def test_the_re_anchor_matches_what_the_fixture_puts_on_the_anchor_day() -> None:
    """The source of truth is `synthetic_activity_candidates`, not a hand-copied timetable."""
    repository = _repo()
    try:
        anchor_day = _current_day(repository)
        _advance_days(repository, _ADVANCED_DAYS, "fixture-parity")
        repository.reset()

        expected = {
            candidate.activity_id: candidate.start_at
            for candidate in synthetic_activity_candidates(anchor_day)
            if candidate.start_at is not None
        }
        catalogue = _catalogue(repository)
        assert expected
        for activity_id, start_at in expected.items():
            assert catalogue[activity_id][0] == start_at

        with repository.sessions() as session:
            sources = set(
                session.scalars(
                    select(ActivityCandidateRow.metadata_source).where(
                        ActivityCandidateRow.activity_id.in_(sorted(expected))
                    )
                )
            )
        assert sources == {_FIXTURE_METADATA_SOURCE}
    finally:
        repository.close()
