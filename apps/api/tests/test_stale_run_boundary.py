"""A `reset()` deactivates the previous run but leaves its rows on record.

`ScenarioRunRow.active` flips, but nothing about `reset()` may rewrite the append-only history a
prior run left behind -- its interventions, its consent evidence, its proposed memories all stay
exactly as they were. That is correct for the audit trail and wrong for what a *stale browser tab*
can still do with an old id: `record_outcome`, `record_follow_through` and `record_enjoyment` used
to check consent against the intervention's own (possibly long-dead) `run_id` rather than the
person's current active run, so a tab still holding an `intervention_id` from before a reset could
keep answering it -- successfully, and folding a ghost answer into `person_id`-scoped preference
state that lives across runs. `ProposedMemoryRow` has the identical problem: its own docstring
promises it is "scoped to the run it was raised in ... so a demo reset starts with a clean slate",
but nothing enforced that read filter or that write guard. `week_plan_entries` was the third and
worst case (audit I finding 1): a reset rewinds the simulated calendar to the fixture's anchor
day, so a dead run's plans fell inside the live week again, showed on the senior's week, accepted
"went" and "enjoyed", and wrote inferred `social`/`timing` preferences into the run that never
made them. These tests pin all three boundaries.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from silverloop.db_models import InterventionOutcomeRow, ProposedMemoryRow, ScenarioRunRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.local_time import local_date
from silverloop.models import PlannedFollowThrough, PreferenceDimension
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


def test_follow_through_cannot_be_recorded_against_a_dead_run() -> None:
    repository = _repo()
    try:
        first = repository.advance("activity_declines", event_id="stale-follow-1")
        intervention_id = first.created_intervention.intervention_id
        repository.record_outcome(intervention_id, "accepted")

        repository.reset()

        with pytest.raises(ValueError, match="previous run"):
            repository.record_follow_through(intervention_id, "completed")
    finally:
        repository.close()


def test_enjoyment_cannot_be_recorded_against_a_dead_run() -> None:
    repository = _repo()
    try:
        first = repository.advance("activity_declines", event_id="stale-enjoy-1")
        intervention_id = first.created_intervention.intervention_id
        repository.record_outcome(intervention_id, "accepted")
        repository.record_follow_through(intervention_id, "completed")

        repository.reset()

        with pytest.raises(ValueError, match="previous run"):
            repository.record_enjoyment(intervention_id, "enjoyed", [], "senior")
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


# ── Proposed memories are scoped to the run they were raised in ──────────────────────────────


def _insert_stale_proposal(repository: SqlAlchemyRepository, run_id: str) -> str:
    proposal_id = "prop_stale_test_0001"
    now = datetime.now(UTC)
    with repository.sessions.begin() as session:
        session.add(
            ProposedMemoryRow(
                proposal_id=proposal_id,
                run_id=run_id,
                person_id=DEMO_PERSON_ID,
                dimension=PreferenceDimension.ENVIRONMENT.value,
                value="indoor",
                statement="You mentioned preferring indoor activities.",
                question="Should Care+ remember that you prefer indoor activities?",
                source_text=None,
                status="pending",
                created_at=now,
            )
        )
    return proposal_id


def test_a_proposal_from_a_dead_run_is_not_listed_after_reset() -> None:
    repository = _repo()
    try:
        with repository.sessions() as session:
            dead_run_id = repository._active_run(session, DEMO_PERSON_ID).run_id
        _insert_stale_proposal(repository, dead_run_id)
        assert [p.proposal_id for p in repository.list_proposed_memories()]

        repository.reset()

        assert repository.list_proposed_memories() == [], (
            "a demo reset must start with a clean slate, per ProposedMemoryRow's own docstring"
        )
    finally:
        repository.close()


def test_a_proposal_from_a_dead_run_cannot_be_confirmed_into_a_durable_preference() -> None:
    """The concrete harm BUG 4 describes: a stale proposal confirmed into `senior_statement`
    evidence -- the strongest evidence class the ranker recognises -- from a conversation the
    current run never had.
    """
    repository = _repo()
    try:
        with repository.sessions() as session:
            dead_run_id = repository._active_run(session, DEMO_PERSON_ID).run_id
        proposal_id = _insert_stale_proposal(repository, dead_run_id)

        repository.reset()

        with pytest.raises(KeyError):
            repository.decide_proposed_memory(proposal_id, "remember", "senior")
    finally:
        repository.close()


def test_a_proposal_from_the_current_run_is_unaffected_by_the_guard() -> None:
    repository = _repo()
    try:
        with repository.sessions() as session:
            run_id = repository._active_run(session, DEMO_PERSON_ID).run_id
        proposal_id = _insert_stale_proposal(repository, run_id)

        assert [p.proposal_id for p in repository.list_proposed_memories()] == [proposal_id]
        response = repository.decide_proposed_memory(proposal_id, "remember", "senior")
        assert response.decision == "remember"
        assert response.preference is not None
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


# ── Week plans belong to the run that made them ──────────────────────────────────────────────


def _plan_one_activity(repository: SqlAlchemyRepository) -> tuple[str, str, date]:
    """Put the first fixed-time listing on the person's week; return `(plan_id, activity_id,
    day)`. The catalogue is seeded once and later resets leave its session times where they are
    (`_seed_activity_candidates`), so the same day is still inside the week after a reset."""
    activity = next(a for a in repository.list_activities() if a.start_at is not None)
    day = local_date(activity.start_at)
    week = repository.plan_activity(activity.activity_id, day, "senior")
    entry = next(e for e in week.entries if e.activity.activity_id == activity.activity_id)
    return entry.plan_id, activity.activity_id, day


def test_a_week_plan_from_a_dead_run_is_not_on_the_new_runs_week() -> None:
    """A reset rewinds the simulated calendar to the fixture's anchor day, so a dead run's plan
    days are inside the live week again. Read person-scoped, the senior saw outings this run
    never made -- and `metrics.activities_planned`, already run-scoped, disagreed with them."""
    repository = _repo()
    try:
        _plan_one_activity(repository)
        assert repository.week_plan().entries, "the plan must be visible before the reset"

        repository.reset()

        assert repository.week_plan().entries == []
        assert repository.replan_notices() == []
    finally:
        repository.close()


def test_a_week_plan_from_a_dead_run_cannot_be_reported_on() -> None:
    """The route answers 404 (`KeyError`), not "that belongs to an old run": a stale browser tab
    holding the id must not have it confirmed. Same answer `decide_proposed_memory` gives."""
    repository = _repo()
    try:
        plan_id, _, _ = _plan_one_activity(repository)

        repository.reset()
        # Past the planned day, so the "that activity has not happened yet" guard is not what
        # rejects this -- the run boundary has to be.
        for index in range(5):
            repository.advance("recovery", event_id=f"dead-plan-{index}")

        with pytest.raises(KeyError):
            repository.record_planned_follow_through(plan_id, "went", None, "senior")
        with pytest.raises(KeyError):
            repository.record_planned_enjoyment(plan_id, "enjoyed", ["people", "timing"], "senior")
    finally:
        repository.close()


def test_a_dead_runs_plan_report_does_not_move_person_scoped_preference_state() -> None:
    """The concrete harm audit I finding 1 reproduced: `social/social 0.5` and `timing/morning
    0.5` inferred into the *live* run from a plan it never made. Mirrors
    `test_a_ghost_answer_does_not_move_person_scoped_preference_state` for the plan path."""
    repository = _repo()
    try:
        plan_id, _, _ = _plan_one_activity(repository)

        repository.reset()
        for index in range(5):
            repository.advance("recovery", event_id=f"dead-plan-learn-{index}")

        before = repository.activity_preferences(person_id=DEMO_PERSON_ID).dimensions

        with pytest.raises(KeyError):
            repository.record_planned_follow_through(plan_id, "went", None, "senior")
        with pytest.raises(KeyError):
            repository.record_planned_enjoyment(plan_id, "enjoyed", ["people", "timing"], "senior")

        after = repository.activity_preferences(person_id=DEMO_PERSON_ID).dimensions
        assert after == before
        assert not [
            preference
            for preference in after
            if preference.dimension in (PreferenceDimension.SOCIAL, PreferenceDimension.TIMING)
        ]
    finally:
        repository.close()


def test_the_same_choice_can_be_planned_again_in_the_new_run() -> None:
    """The other half of run-scoping, and the reason the unique key had to move with the readers:
    person-scoped uniqueness made a live re-plan impossible once a dead run held the same
    `(person, day, activity)` -- "add to my week" failed for a week showing nothing."""
    repository = _repo()
    try:
        dead_plan_id, activity_id, day = _plan_one_activity(repository)

        repository.reset()

        week = repository.plan_activity(activity_id, day, "senior")
        assert [entry.activity.activity_id for entry in week.entries] == [activity_id]
        assert week.entries[0].plan_id != dead_plan_id, "the live run must get its own plan row"
    finally:
        repository.close()


def test_a_plan_made_in_the_current_run_is_unaffected_by_the_guard() -> None:
    """The guard must not reject an ordinary, same-run report -- only a stale one."""
    repository = _repo()
    try:
        plan_id, _, _ = _plan_one_activity(repository)
        for index in range(5):
            repository.advance("recovery", event_id=f"live-plan-{index}")

        report = repository.record_planned_follow_through(plan_id, "went", None, "senior")
        assert report.follow_through == PlannedFollowThrough.WENT
        verdict = repository.record_planned_enjoyment(
            plan_id, "enjoyed", ["people", "timing"], "senior"
        )
        assert verdict.preferences_updated
    finally:
        repository.close()
