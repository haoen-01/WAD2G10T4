"""One open review case per person per run, not one per day a concern persists.

`_create_case` used to insert a new `ReviewCaseRow` every single time a decision reached
`coordinator_review`, and a sustained decline re-reaches that rung every day it continues. An
eighteen-day drift produced sixteen near-identical cards for one person and made
`metrics.open_cases` count days rather than people. `_create_case` now refreshes the person's
existing open case in place and returns `None` from a refresh because nothing was created. These
tests pin that behaviour so it cannot regress back to one-case-per-day.

"Open" here means *unresolved*, the same predicate the automatic closers use: an acknowledged case
is a concern a human has already picked up, not a closed one, and treating it as closed produced a
second card for the same concern the moment the decline continued.
"""

from __future__ import annotations

from silverloop.models import CaseStatus, Decision, ReviewCase
from silverloop.sql_repository import SqlAlchemyRepository
from tests.row_fixtures import record_case_review

PERSON_B = "person-b"


def _case(repository: SqlAlchemyRepository, case_id: str) -> ReviewCase:
    return next(case for case in repository.list_cases() if case.case_id == case_id)


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def test_eighteen_consecutive_declines_produce_one_case_reflecting_the_latest_day() -> None:
    repository = _repo()
    try:
        responses = [
            repository.advance("activity_declines", event_id=f"drift-{index}")
            for index in range(18)
        ]

        cases = repository.list_cases()
        assert len(cases) == 1, "eighteen declining days must open exactly one review case"

        opening_state = next(
            response.state for response in responses if response.created_case is not None
        )
        latest_state = responses[-1].state

        # The two states must actually differ, or this test would not be exercising a refresh.
        assert (opening_state.signal.sustained_low_days, opening_state.signal.delta_percent) != (
            latest_state.signal.sustained_low_days,
            latest_state.signal.delta_percent,
        )

        expected_summary = (
            f"Activity is {abs(latest_state.signal.delta_percent):.0f}% below "
            f"{latest_state.display_name}'s personal baseline across "
            # "valid-wear days", not bare "days": `_sustained_low_days` skips a day with too little
            # wear-time, so the count is of days Care+ could read, and the sentence that
            # carries the percentage carries the caveat with it -- exactly as the web twin
            # (`view-models.severityDetail`) has always done. Pluralised for a person reading it.
            f"{latest_state.signal.sustained_low_days} valid-wear days."
        )
        assert latest_state.signal.sustained_low_days > 1
        assert cases[0].summary == expected_summary
    finally:
        repository.close()


def test_created_case_is_populated_only_on_the_advance_that_opens_it() -> None:
    repository = _repo()
    try:
        responses = [
            repository.advance("activity_declines", event_id=f"pop-{index}") for index in range(18)
        ]

        review_days = [
            index
            for index, response in enumerate(responses)
            if response.state.last_decision == Decision.COORDINATOR_REVIEW
        ]
        # Otherwise this run never reaches the rung this test is meant to exercise repeatedly.
        assert len(review_days) > 1

        populated = [index for index in review_days if responses[index].created_case is not None]
        assert populated == [review_days[0]], (
            "created_case must be set on the day the case opens and None on every "
            "subsequent refresh"
        )
    finally:
        repository.close()


def test_refreshed_case_keeps_its_original_case_id_and_opened_at() -> None:
    repository = _repo()
    try:
        responses = [
            repository.advance("activity_declines", event_id=f"keep-{index}") for index in range(18)
        ]

        opened = next(
            response.created_case for response in responses if response.created_case is not None
        )
        assert opened is not None

        refreshed = repository.list_cases()[0]
        assert refreshed.case_id == opened.case_id
        assert refreshed.opened_at == opened.opened_at
        # It must actually have been refreshed, not merely untouched.
        assert refreshed.summary != opened.summary
    finally:
        repository.close()


def test_resolving_a_case_and_declining_again_opens_a_new_one() -> None:
    """A closed concern that returns is genuinely new; the dedup guard must not suppress it."""
    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"resolve-first-{index}")

        opened = repository.list_cases()
        assert len(opened) == 1
        assert opened[0].status == CaseStatus.OPEN
        first_case_id = opened[0].case_id

        record_case_review(repository, first_case_id, CaseStatus.RESOLVED, "Reviewed and closed.")
        assert _case(repository, first_case_id).status == CaseStatus.RESOLVED

        response = repository.advance("activity_declines", event_id="resolve-then-decline")
        assert response.state.last_decision == Decision.COORDINATOR_REVIEW
        assert response.created_case is not None
        assert response.created_case.case_id != first_case_id

        all_cases = {case.case_id: case.status for case in repository.list_cases()}
        assert all_cases == {
            first_case_id: CaseStatus.RESOLVED,
            response.created_case.case_id: CaseStatus.OPEN,
        }
    finally:
        repository.close()


def test_acknowledging_a_case_and_declining_again_refreshes_it() -> None:
    """An acknowledged case is still an open concern.

    Reproduced live (audit H finding 1): three declining days opened a case, a coordinator
    acknowledged it, and the next declining day opened a *second* card for the same concern about
    the same person -- the queue said "2 cases for 1 senior" while `metrics.open_cases` said 1,
    and the acknowledged one froze at the day count it had when the coordinator read it, because
    every later day refreshed the new card instead. `ACKNOWLEDGED` is non-terminal; only a
    resolved concern that returns is genuinely new.
    """
    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"ack-first-{index}")

        opened = repository.list_cases()
        assert len(opened) == 1
        case_id = opened[0].case_id
        summary_when_acknowledged = opened[0].summary

        record_case_review(
            repository, case_id, CaseStatus.ACKNOWLEDGED, "Seen; calling her tomorrow."
        )
        assert _case(repository, case_id).status == CaseStatus.ACKNOWLEDGED

        response = repository.advance("activity_declines", event_id="ack-then-decline")
        assert response.state.last_decision == Decision.COORDINATOR_REVIEW
        assert response.created_case is None, "no second card for the same concern"

        cases = repository.list_cases()
        assert [case.case_id for case in cases] == [case_id]
        # Still acknowledged: a human picked this up, and one more day does not undo that.
        assert cases[0].status == CaseStatus.ACKNOWLEDGED
        # And it is refreshed rather than frozen at the day the coordinator happened to read it.
        assert cases[0].summary != summary_when_acknowledged
        assert (
            f"across {response.state.signal.sustained_low_days} valid-wear days" in cases[0].summary
        )
    finally:
        repository.close()


def test_metrics_open_cases_counts_people_needing_review_not_decline_days() -> None:
    repository = _repo()
    try:
        for index in range(18):
            repository.advance("activity_declines", event_id=f"metrics-{index}")

        metrics = repository.metrics()
        assert metrics.decision_evidence == 18
        assert metrics.open_cases == 1
    finally:
        repository.close()


def test_metrics_open_cases_is_scoped_per_person_regardless_of_days_elapsed() -> None:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    repository.reset(person_id=PERSON_B, allow_new_person=True)
    try:
        for index in range(18):
            repository.advance("activity_declines", event_id=f"metrics-a-{index}")
        for index in range(3):
            repository.advance(
                "activity_declines", event_id=f"metrics-b-{index}", person_id=PERSON_B
            )

        # Eighteen days for A, three for B -- both still count as exactly one person in review.
        assert repository.metrics().open_cases == 1
        assert repository.metrics(person_id=PERSON_B).open_cases == 1
        assert len(repository.list_cases()) == 2
    finally:
        repository.close()
