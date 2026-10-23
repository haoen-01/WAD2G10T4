"""Reading a catalogue row written before the enrichment columns existed.

This pins a failure that reached a running product: `a3f8c72d1e94` added ten columns to
`activity_candidates` as nullable, so every row already in the database had `NULL` in all of
them. `_to_activity_candidate` handed those straight to `list[str]` fields, and Pydantic raised

    3 validation errors for ActivityCandidate
      what_to_bring  Input should be a valid list [input_value=None]

which did not merely omit the detail -- it took the whole listing down, so "Ask Care+"
answered every request with an error.

It survived the first round of testing because the SQLite schema is built from the ORM metadata
while Postgres is built by Alembic, and the two disagreed about nullability: the model said NOT
NULL, the migration said nullable. The test could not create the state that was breaking
production. Both are now nullable, and these tests construct the `NULL` case explicitly.
"""

from __future__ import annotations

from sqlalchemy import text

from silverloop.sql_repository import SqlAlchemyRepository

_NULL_OUT_ENRICHMENT = text("""
    update activity_candidates set
      what_to_bring_json = NULL, getting_there_json = NULL, good_to_know_json = NULL,
      description = NULL, location_address = NULL, location_postal_code = NULL,
      contact_phone = NULL, contact_note = NULL, booking_note = NULL, duration_minutes = NULL
""")


def _seeded_repository() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", seed=2026)
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def test_a_row_predating_the_enrichment_columns_is_still_readable() -> None:
    repository = _seeded_repository()
    with repository.sessions.begin() as session:
        session.execute(_NULL_OUT_ENRICHMENT)

    activities = repository.list_activities()

    assert activities, "the catalogue must still be readable when the new columns are NULL"
    for activity in activities:
        # An absent list and an empty one mean the same thing: the listing does not say.
        assert activity.what_to_bring == []
        assert activity.getting_there == []
        assert activity.good_to_know == []
    repository.close()


def test_startup_backfills_listings_that_were_seeded_before_the_columns_existed() -> None:
    """The seeder used to skip any row whose id already existed, so a catalogue seeded early
    stayed detail-less forever. It now refreshes in place, which is what makes the fix reach a
    database that is already running rather than only a fresh one."""
    repository = _seeded_repository()
    with repository.sessions.begin() as session:
        session.execute(_NULL_OUT_ENRICHMENT)
    assert all(activity.description is None for activity in repository.list_activities())

    repository.ensure_active_run()

    refreshed = repository.list_activities()
    assert all(activity.description for activity in refreshed)
    chair = next(a for a in refreshed if a.title == "Chair Mobility & Balance")
    assert chair.location.address and chair.location.postal_code
    assert chair.getting_there and chair.contact_phone
    assert chair.what_to_bring
    repository.close()


def test_session_times_are_not_moved_by_a_refresh() -> None:
    """`start_at` is deliberately excluded from the refresh: a later reset for another person must
    not move a session someone has already planned around."""
    repository = _seeded_repository()
    before = {a.activity_id: a.start_at for a in repository.list_activities()}

    repository.ensure_active_run()

    after = {a.activity_id: a.start_at for a in repository.list_activities()}
    assert after == before
    repository.close()
