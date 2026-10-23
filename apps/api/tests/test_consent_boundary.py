"""Consent gates the coordinator surface, not only outreach.

Adversarial probing on 2026-09-05 found that withdrawing consent withdrew the pending
intervention and nothing else: the review case stayed open on the coordinator's queue carrying
its derived summary ("activity is 56% below her personal baseline"), and `review_case` had no
consent check at all, so a coordinator could act on it and be permanently recorded as having
done so. These tests pin the boundary.
"""

from __future__ import annotations

import pytest

from silverloop.models import CaseStatus
from silverloop.sql_repository import SqlAlchemyRepository


def _repo_with_open_case() -> SqlAlchemyRepository:
    """Three sustained declines is the shortest path to a `coordinator_review` case."""
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    for index in range(3):
        repository.advance("activity_declines", event_id=f"consent-boundary-{index}")
    return repository


def test_revoking_consent_closes_open_review_cases() -> None:
    repository = _repo_with_open_case()
    try:
        assert [case for case in repository.list_cases() if case.status != CaseStatus.RESOLVED]

        repository.set_consent(False, "Senior withdrew consent.", "senior")

        unresolved = [
            case for case in repository.list_cases() if case.status != CaseStatus.RESOLVED
        ]
        assert unresolved == [], "a withdrawn senior must not stay on the review queue"
    finally:
        repository.close()


def test_case_closure_is_recorded_rather_than_silent() -> None:
    """The case must not simply vanish -- the append-only trail says why it closed."""
    repository = _repo_with_open_case()
    try:
        repository.set_consent(False, "Senior withdrew consent.", "senior")

        case = repository.list_cases()[0]
        assert case.action_history, "closure must append a review action"
        closure = case.action_history[-1]
        assert closure.reviewer == "system"
        assert "consent" in closure.note.lower()
    finally:
        repository.close()


def test_review_case_is_refused_once_consent_is_inactive() -> None:
    repository = _repo_with_open_case()
    try:
        case_id = repository.list_cases()[0].case_id
        repository.set_consent(False, "Senior withdrew consent.", "senior")

        with pytest.raises(ValueError, match="[Cc]onsent is inactive"):
            repository.review_case(case_id, CaseStatus.ACKNOWLEDGED, "coordinator note")
    finally:
        repository.close()


def test_consent_revocation_reports_the_cases_it_closed() -> None:
    """The audit detail names them, so the closure is traceable from the consent event."""
    repository = _repo_with_open_case()
    try:
        response = repository.set_consent(False, "Senior withdrew consent.", "senior")
        closed = response.audit_event.detail.get("closed_case_ids")
        assert closed, "the consent audit event must record which cases it closed"
    finally:
        repository.close()


def test_withdrawn_outreach_does_not_spend_the_weekly_contact_budget() -> None:
    """An offer withdrawn on revocation was never received, so it must not count against the cap.

    Without this, a senior who withdrew consent and turned suggestions back on started capped
    having been sent nothing.
    """
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    try:
        for index in range(2):
            repository.advance("activity_declines", event_id=f"cap-{index}")

        with repository.sessions.begin() as session:
            run = repository._active_run(session, "mdm-lim")
            assert repository._weekly_contact_count(session, run.run_id, run.current_day) == 2

        repository.set_consent(False, "Senior withdrew consent.", "senior")

        with repository.sessions.begin() as session:
            run = repository._active_run(session, "mdm-lim")
            assert repository._weekly_contact_count(session, run.run_id, run.current_day) == 0
    finally:
        repository.close()


def test_attention_band_reports_the_signal_not_the_action_urgency() -> None:
    """A suppressed person must not read as `stable`.

    The band used to be derived from `support_priority`, which `suppress` deliberately scores
    low (15 for the contact cap, 0 for revoked consent). That made "we have contacted them
    enough this week" render identically to "they are fine" on the queue a coordinator triages.
    """
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    try:
        assert repository.person_state().attention_band == "stable"

        bands = []
        for index in range(3):
            state = repository.advance("activity_declines", event_id=f"band-{index}").state
            bands.append(state.attention_band)

        # A single substantial decline is already worth watching, and a sustained severe one
        # reaches review -- neither may report as stable.
        assert bands[0] == "watch"
        assert bands[-1] == "review"
        assert "stable" not in bands
    finally:
        repository.close()


def test_a_demo_reset_reactivates_consent_after_a_prior_withdrawal() -> None:
    """Pins current behaviour; this is not a statement that it is correct.

    `ConsentEvidenceRow` is scoped by `run_id`, and `_consent_active` reads only the latest row
    for the *active* run. `reset()` ends the old run and starts a new one with its own fresh
    `active=True` "Synthetic demo consent fixture activated on reset" row -- so a withdrawal
    recorded in one run has no row at all in the next run's history, and a reset silently
    re-enables consent regardless of what the person decided before it.

    See `docs/adr/0001-consent-scope-model.md`, "Needs human decision" -- whether a withdrawal
    should survive a reset the way a standing `senior_statement` preference does (ADR 0004) is
    undecided. This test only fixes what happens today, so a future decision has something
    concrete to flip.
    """
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    try:
        repository.set_consent(False, "Senior withdrew consent.", "senior")
        assert repository.person_state().consent_active is False

        repository.reset()

        assert repository.person_state().consent_active is True
    finally:
        repository.close()
