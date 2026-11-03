"""A `reset()` deactivates the previous run but leaves its rows on record.

`ScenarioRunRow.active` flips, but nothing about `reset()` may rewrite the append-only history a
prior run left behind -- its interventions and its consent evidence stay exactly as they were.
That is correct for the audit trail and wrong for what a *stale browser tab* can still do with an
old id: `record_outcome` used to check consent against the intervention's own (possibly
long-dead) `run_id` rather than the person's current active run, so a tab still holding an
`intervention_id` from before a reset could keep answering it -- successfully, and folding a
ghost answer into `person_id`-scoped preference state that lives across runs. These tests pin that
boundary. (The same guards on follow-through, enjoyment, proposed memories and week-plan reports
went with their routes in step 7.)
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from silverloop.db_models import InterventionOutcomeRow, ScenarioRunRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


# ── Interventions must be answered against the *current* run ─────────────────────────────────


def test_a_never_answered_intervention_from_a_dead_run_cannot_be_declined() -> None:
    repository = _repo()
    try:
        first = repository.advance("activity_declines", event_id="stale-outcome-1")
        intervention_id = first.created_intervention.intervention_id

        repository.reset()  # deactivates the run the intervention belongs to

        with pytest.raises(ValueError, match="previous run"):
            repository.record_outcome(intervention_id, "declined")

        # And the ghost attempt left no trace: no outcome was actually recorded.
        with repository.sessions() as session:
            recorded = session.scalar(
                select(InterventionOutcomeRow).where(
                    InterventionOutcomeRow.intervention_id == intervention_id
                )
            )
            assert recorded is None
    finally:
        repository.close()


def test_a_ghost_answer_does_not_move_person_scoped_preference_state() -> None:
    """The concrete harm BUG 3 describes: cross-run learner/suppression state moved by a reply
    from a run that no longer exists.
    """
    repository = _repo()
    try:
        first = repository.advance("activity_declines", event_id="stale-learn-1")
        intervention_id = first.created_intervention.intervention_id
        candidate_key = first.created_intervention.candidate_key

        with repository.sessions() as session:
            _, before = repository._preference_learners(session, DEMO_PERSON_ID)
        before_score = before.expected_value(candidate_key)

        repository.reset()
        with pytest.raises(ValueError):
            repository.record_outcome(intervention_id, "declined")

        with repository.sessions() as session:
            _, after = repository._preference_learners(session, DEMO_PERSON_ID)
        assert after.expected_value(candidate_key) == before_score
    finally:
        repository.close()


def test_current_run_interventions_are_unaffected_by_the_guard() -> None:
    """The guard must not reject an ordinary, same-run reply -- only a stale one."""
    repository = _repo()
    try:
        first = repository.advance("activity_declines", event_id="live-outcome-1")
        intervention_id = first.created_intervention.intervention_id

        response = repository.record_outcome(intervention_id, "declined")
        assert response.outcome == "declined"
    finally:
        repository.close()


# ── `_active_run` selection is deterministic even with more than one active row ──────────────


def test_active_run_selection_is_deterministic_with_duplicate_active_rows() -> None:
    """No DB constraint enforces one active run per person (see BUG 6 in the incident report);
    two concurrent `reset()` calls can leave two active rows. `_active_run` must not raise
    `MultipleResultsFound` when that happens -- it must pick one, deterministically.
    """
    repository = _repo()
    try:
        with repository.sessions.begin() as session:
            current = repository._active_run(session, DEMO_PERSON_ID)
            duplicate = ScenarioRunRow(
                run_id="run_duplicate_active_0001",
                person_id=DEMO_PERSON_ID,
                seed=current.seed,
                scenario_version=current.scenario_version,
                current_day=current.current_day,
                active=True,
                # Strictly after `current.started_at`, not merely `datetime.now(UTC)` -- the two
                # inserts can otherwise land in the same microsecond and make the ordering this
                # test pins nondeterministic on a fast machine.
                started_at=current.started_at + timedelta(minutes=1),
            )
            session.add(duplicate)

        with repository.sessions() as session:
            resolved = repository._active_run(session, DEMO_PERSON_ID)
        assert resolved.run_id == "run_duplicate_active_0001", (
            "the most recently started active run must win, deterministically"
        )
    finally:
        repository.close()
