"""A review case has a clock and a typed ending (audit-H finding 4).

Before this, `ReviewCaseRow` carried one timestamp -- `opened_at`, a wall clock -- and nothing
else. A coordinator could not tell whether a case had been sitting there for a day or a fortnight,
who had last touched it, or, once it closed, *why*: the reason lived only in the prose of a
`CaseReviewRow.note` written by `reviewer="system"`, so anything wanting to act on it had to
string-match an English sentence.

Two things are fixed here, and they are deliberately different in kind:

- the **clock** is counted in simulated days, the same clock the response window already uses
  (`RESPONSE_WINDOW_DAYS`). Wall time is meaningless in this product: nothing advances except
  `POST /v1/simulation/advance`, so a case opened "three days ago" by the calendar may have seen
  no new reading at all.
- the **ending** is stored as a typed `CaseResolution` on the case row, set at the one place each
  closure happens, rather than inferred afterwards from a note.
"""

from __future__ import annotations

from datetime import timedelta

from silverloop.models import CaseResolution, CaseStatus
from silverloop.sql_repository import CASE_REVIEW_WINDOW_DAYS, SqlAlchemyRepository
from tests.row_fixtures import record_case_review


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def test_the_case_clock_counts_simulated_days_not_wall_clock_ones() -> None:
    repository = _repo()
    try:
        opening_day = None
        for index in range(3):
            response = repository.advance("activity_declines", event_id=f"clock-{index}")
            if response.created_case is not None:
                opening_day = response.state.current_day
        assert opening_day is not None, "three declining days must open a case"

        opened = repository.list_cases()[0]
        assert opened.opened_day == opening_day
        # The day it opened is day one of the review, not day zero: a coordinator reading "0 days"
        # about a case that is on their screen right now would be reading a falsehood.
        assert opened.days_in_review == 1
        assert opened.review_by_day == opening_day + timedelta(days=CASE_REVIEW_WINDOW_DAYS)
        assert opened.resolution is None

        latest = repository.advance("activity_declines", event_id="clock-3")
        assert latest.created_case is None, "a fourth declining day refreshes, never re-opens"

        refreshed = repository.list_cases()[0]
        assert refreshed.opened_day == opening_day, "a refresh must not move the opening day"
        assert refreshed.days_in_review == 2
    finally:
        repository.close()


def test_a_reviewed_case_carries_who_touched_it_and_when() -> None:
    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"actor-{index}")
        case = repository.list_cases()[0]
        assert case.last_reviewed_at is None and case.reviewer is None

        record_case_review(
            repository,
            case.case_id,
            CaseStatus.ACKNOWLEDGED,
            "Picked this up; speaking to her daughter first.",
            reviewer="coordinator-amy",
        )

        reviewed = repository.list_cases()[0]
        assert reviewed.reviewer == "coordinator-amy"
        assert reviewed.last_reviewed_at is not None
        assert reviewed.last_reviewed_at == reviewed.action_history[-1].recorded_at
        # Acknowledging is not an ending. It does not resolve, snooze or stop the clock.
        assert reviewed.resolution is None
        assert reviewed.days_in_review == 1
    finally:
        repository.close()


def test_a_coordinator_resolution_is_stored_as_one_rather_than_written_in_prose() -> None:
    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"resolve-{index}")
        case = repository.list_cases()[0]

        record_case_review(
            repository,
            case.case_id,
            CaseStatus.RESOLVED,
            "Spoke to her; she is away with family.",
            "amy",
        )

        resolved = repository.list_cases()[0]
        assert resolved.status == CaseStatus.RESOLVED
        assert resolved.resolution == CaseResolution.COORDINATOR_DECISION
        # Nothing to re-surface once a human has answered the question the case asked.
        assert resolved.review_by_day is None
    finally:
        repository.close()


def test_recovery_and_consent_withdrawal_close_a_case_with_their_own_reasons() -> None:
    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"recover-{index}")
        repository.advance("recovery", event_id="recover-back")

        recovered = repository.list_cases()[0]
        assert recovered.status == CaseStatus.RESOLVED
        assert recovered.resolution == CaseResolution.RECOVERED
    finally:
        repository.close()

    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"consent-{index}")
        repository.advance("consent_revoked", event_id="consent-off")

        withdrawn = repository.list_cases()[0]
        assert withdrawn.status == CaseStatus.RESOLVED
        assert withdrawn.resolution == CaseResolution.CONSENT_WITHDRAWN
    finally:
        repository.close()
