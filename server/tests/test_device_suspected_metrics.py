"""Days the tracker did not report are counted, not silently dropped (audit-H finding 7, M43).

`quality.assess_data_quality` computes `device_suspected` and writes a careful sentence about it,
and until now the only thing that ever rendered either was one chip on a senior-facing story card.
Care Team had no tile, no roster flag and no counter: a coordinator could not tell "three of this
week's readings never arrived" from "this week was quiet".

This is the aggregate half, and it is deliberately only the aggregate half. Nothing about the
decision ladder changes -- a sparse reading is still `NO_ACTION`, still `stable`, still says
nothing about the person -- and the count is offered as a data-collection fact, never as a
wellbeing signal. The `DEVICE_SUPPORT` action class the audit sketches as layer 2 is a policy
change and is not here.
"""

from __future__ import annotations

from silverloop.sql_repository import SqlAlchemyRepository


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def test_a_run_with_every_reading_intact_reports_no_suspected_days() -> None:
    repository = _repo()
    try:
        repository.advance("activity_declines", event_id="device-clean")

        assert repository.metrics().device_suspected_days == 0
    finally:
        repository.close()


def test_a_low_wear_day_is_counted_without_changing_the_decision() -> None:
    repository = _repo()
    try:
        before = repository.metrics().device_suspected_days
        response = repository.advance("low_wear", event_id="device-low-wear")

        metrics = repository.metrics()

        assert metrics.device_suspected_days == before + 1
        # The ladder is untouched. A reading nobody can interpret supports nothing either way, and
        # counting it must not start making it mean something.
        assert response.state.last_decision == "no_action"
        assert response.state.attention_band == "stable"
        assert response.state.signal.quality.device_suspected is True
    finally:
        repository.close()


def test_two_quiet_days_are_counted_once_each() -> None:
    repository = _repo()
    try:
        repository.advance("low_wear", event_id="device-day-1")
        repository.advance("low_wear", event_id="device-day-2")

        assert repository.metrics().device_suspected_days == 2
    finally:
        repository.close()
