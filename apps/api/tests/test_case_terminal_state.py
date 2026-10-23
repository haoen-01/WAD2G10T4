"""A `resolved` review case is terminal.

`review_case` applied `row.status = status.value` unconditionally, once consent passed -- so an
already-`resolved` case could be re-reviewed, appended a duplicate `CaseReviewRow` against a
`summary` that may no longer describe anything current, and could even be driven back to `open`.
These tests pin the guard.
"""

from __future__ import annotations

import pytest

from silverloop.models import CaseStatus
from silverloop.sql_repository import SqlAlchemyRepository


def _repo_with_resolved_case() -> tuple[SqlAlchemyRepository, str]:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    for index in range(3):
        repository.advance("activity_declines", event_id=f"terminal-state-{index}")
    case_id = repository.list_cases()[0].case_id
    repository.review_case(case_id, CaseStatus.RESOLVED, "Reviewed and closed.")
    return repository, case_id


def test_a_resolved_case_cannot_be_reviewed_again() -> None:
    repository, case_id = _repo_with_resolved_case()
    try:
        with pytest.raises(ValueError, match="already been resolved"):
            repository.review_case(case_id, CaseStatus.ACKNOWLEDGED, "Second look.")
    finally:
        repository.close()


def test_a_resolved_case_cannot_be_driven_back_to_open() -> None:
    """The specific, worse failure mode the guard exists to prevent."""
    repository, case_id = _repo_with_resolved_case()
    try:
        with pytest.raises(ValueError):
            repository.review_case(case_id, CaseStatus.OPEN, "Reopening by mistake.")
        assert repository.get_case(case_id).status == CaseStatus.RESOLVED
    finally:
        repository.close()


def test_the_rejected_re_review_does_not_append_a_duplicate_audit_entry() -> None:
    repository, case_id = _repo_with_resolved_case()
    try:
        before = len(repository.get_case(case_id).action_history)
        with pytest.raises(ValueError):
            repository.review_case(case_id, CaseStatus.ACKNOWLEDGED, "Second look.")
        after = len(repository.get_case(case_id).action_history)
        assert after == before
    finally:
        repository.close()


def test_a_case_not_yet_resolved_can_still_be_reviewed() -> None:
    """The guard must be narrow: it blocks re-reviewing a *resolved* case, not an ordinary
    coordinator action on one still open.
    """
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"open-review-{index}")
        case_id = repository.list_cases()[0].case_id

        response = repository.review_case(case_id, CaseStatus.ACKNOWLEDGED, "Looking into it.")
        assert response.case.status == CaseStatus.ACKNOWLEDGED
    finally:
        repository.close()
