"""Review-setting writers on PostgreSQL: the run-row lock and its ordering (ADR 0008).

Skipped unless `SILVERLOOP_POSTGRES_TEST_URL` names a dedicated test database, like the rest of the
PostgreSQL suite. SQLite has no row locks; `test_review_threshold_api.py` pins the
lock-before-insert ordering there, and these tests pin what that ordering buys on the engine the
shared runtime uses.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from silverloop.db_models import (
    AuditEventRow,
    ReviewThresholdDecisionRow,
    ReviewThresholdProposalRow,
    ScenarioRunRow,
)
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.migrations import upgrade_database
from silverloop.models import CaseStatus, HumanAction
from silverloop.review_threshold import ReviewThreshold, never_later, resolve_live_threshold
from silverloop.sql_repository import (
    ReviewThresholdConflict,
    SqlAlchemyRepository,
    _sync_database_url,
    _utcnow,
)

POSTGRES_TEST_URL = os.getenv("SILVERLOOP_POSTGRES_TEST_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not POSTGRES_TEST_URL,
        reason="SILVERLOOP_POSTGRES_TEST_URL is required for PostgreSQL integration tests",
    ),
]


def _repository() -> SqlAlchemyRepository:
    assert POSTGRES_TEST_URL is not None
    database_url = _sync_database_url(POSTGRES_TEST_URL)
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql" or "test" not in (parsed.database or "").lower():
        pytest.fail("PostgreSQL tests require a dedicated database whose name contains 'test'.")
    upgrade_database(database_url)
    repository = SqlAlchemyRepository(database_url)
    repository.reset()
    return repository


def _run_id(repository: SqlAlchemyRepository) -> str:
    with repository.sessions() as session:
        run_id = session.scalar(
            select(ScenarioRunRow.run_id).where(
                ScenarioRunRow.active.is_(True), ScenarioRunRow.person_id == DEMO_PERSON_ID
            )
        )
    assert run_id is not None
    return run_id


def test_the_run_lock_serialises_writers_but_never_blocks_a_child_insert() -> None:
    repository = _repository()
    run_id = _run_id(repository)
    holder = repository.sessions()
    try:
        holder.begin()
        repository._lock_threshold_run(holder, run_id)

        # FOR NO KEY UPDATE is compatible with the KEY SHARE lock a child insert takes.
        with repository.sessions.begin() as other:
            other.execute(text("SET LOCAL lock_timeout = '2s'"))
            other.add(
                AuditEventRow(
                    event_id=f"evt_lock_probe_{_utcnow().timestamp():.0f}",
                    run_id=run_id,
                    person_id=DEMO_PERSON_ID,
                    event_type="lock_probe",
                    actor="test",
                    decision=None,
                    detail_json={},
                    recorded_at=_utcnow(),
                )
            )

        # A second review-setting writer waits for the first.
        waiting = repository.sessions()
        try:
            waiting.begin()
            waiting.execute(text("SET LOCAL lock_timeout = '300ms'"))
            with pytest.raises(DBAPIError, match="lock"):
                repository._lock_threshold_run(waiting, run_id)
        finally:
            waiting.rollback()
            waiting.close()
    finally:
        holder.rollback()
        holder.close()
        repository.close()


def _race(
    workers: list[tuple[str, Callable[[], object]]],
    allowed: dict[str, tuple[type[BaseException], ...]],
) -> dict[str, int]:
    """Start every worker at the same instant; return successes per kind. Any exception that is
    not an enumerated, expected domain conflict for that kind fails the test."""
    barrier = threading.Barrier(len(workers))
    successes: dict[str, int] = {}
    unexpected: list[tuple[str, BaseException]] = []
    lock = threading.Lock()

    def run(kind: str, call: Callable[[], object]) -> None:
        barrier.wait(timeout=30)
        try:
            call()
        except allowed.get(kind, ()):
            return
        except BaseException as error:  # noqa: BLE001 - collected and asserted on below
            with lock:
                unexpected.append((kind, error))
            return
        with lock:
            successes[kind] = successes.get(kind, 0) + 1

    threads = [threading.Thread(target=run, args=worker) for worker in workers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive(), "a writer hung (lock wait or deadlock)"
    assert not unexpected, unexpected
    return successes


def test_concurrent_writers_on_a_loosened_setting_never_deadlock_or_fail_unexpectedly() -> None:
    """Reviews marked "should have reached me sooner", advances, an approval and consent changes,
    all released together against a person whose live setting is loosened, so the revert walk,
    supersession and pending-approval ending all run under contention."""
    repository = _repository()
    try:
        run_id = _run_id(repository)
        with repository.sessions.begin() as session:
            run = session.get(ScenarioRunRow, run_id)
            assert run is not None
            session.add(
                ReviewThresholdDecisionRow(
                    decision_id=f"pg_race_approval_{_utcnow().timestamp():.0f}",
                    run_id=run_id,
                    person_id=DEMO_PERSON_ID,
                    kind="approved",
                    previous_severity_pct=40,
                    previous_persistence_days=3,
                    severity_pct=40,
                    persistence_days=4,
                    decided_by="coordinator",
                    decided_on_day=run.current_day - timedelta(days=10),
                    effective_from_day=run.current_day - timedelta(days=9),
                    decided_at=_utcnow() - timedelta(days=10),
                )
            )
        stamp = f"{_utcnow().timestamp():.0f}"
        for index in range(4):
            repository.advance("activity_declines", f"pg-race-setup-{stamp}-{index}")
        cases = repository.list_cases()
        assert cases, "four declining days under 40%/4 days must open a case"
        case = cases[0]
        state = repository.person_state()
        with repository.sessions.begin() as session:
            proposal = ReviewThresholdProposalRow(
                proposal_id=f"pg_race_proposal_{stamp}",
                run_id=run_id,
                person_id=DEMO_PERSON_ID,
                output_kind="proposal",
                proposer="agent",
                round_id=None,
                round_index=1,
                previous_severity_pct=40,
                previous_persistence_days=4,
                proposed_severity_pct=40,
                proposed_persistence_days=5,
                cause="too_tight_for_person",
                reasoning="Race fixture.",
                cited_evidence_ids=[case.decision_evidence_id],
                trigger_case_id=None,
                trigger_review_ids=[],
                reported_by="coordinator",
                coordinator_reason="not_a_concern",
                write_up_for_decision_id=None,
                agent_run_json=None,
                proposed_on_day=state.current_day,
                proposed_at=_utcnow(),
            )
            session.add(proposal)

        def review(index: int) -> Callable[[], object]:
            return lambda: repository.review_case(
                case.case_id,
                CaseStatus.ACKNOWLEDGED,
                f"Concurrent review {index}.",
                "coordinator",
                human_action=HumanAction.AGREE,
                reached_too_late=True,
            )

        def advance(index: int, wave: int) -> Callable[[], object]:
            return lambda: repository.advance(
                "activity_declines", f"pg-race-{stamp}-{wave}-{index}"
            )

        # Expected domain outcomes, per writer, and nothing else:
        # - approve: the proposal was superseded by a revert, the day moved under it, or the
        #   setting changed since it was made (all `ReviewThresholdConflict`);
        # - a review in the second wave: consent was withdrawn first (`ValueError`);
        # - consent in the second wave / approve: none beyond the above.
        first_wave = _race(
            [
                *[("review", review(index)) for index in range(3)],
                *[("advance", advance(index, 1)) for index in range(3)],
                (
                    "approve",
                    lambda: repository.approve_threshold_proposal(
                        DEMO_PERSON_ID,
                        proposal.proposal_id,
                        cause_confirmed=True,
                        shown_on_day=state.current_day,
                        note=None,
                        actor="coordinator",
                    ),
                ),
                ("consent", lambda: repository.set_consent(True, "Still taking part.", "senior")),
            ],
            allowed={"approve": (ReviewThresholdConflict,)},
        )
        assert first_wave.get("review", 0) >= 1, first_wave
        assert first_wave.get("advance", 0) >= 1, first_wave

        second_wave = _race(
            [
                *[("review", review(index)) for index in range(3, 6)],
                *[("advance", advance(index, 2)) for index in range(2)],
                ("consent", lambda: repository.set_consent(False, "Stopping.", "senior")),
            ],
            allowed={"review": (ValueError,)},
        )
        assert second_wave.get("advance", 0) >= 1, second_wave
        assert second_wave.get("consent", 0) == 1, second_wave

        with repository.sessions() as session:
            facts = repository._threshold_facts(session, run_id)
            run = session.get(ScenarioRunRow, run_id)
            assert run is not None
            tomorrow = resolve_live_threshold(facts, run.current_day + timedelta(days=1))
        assert never_later(tomorrow.threshold, ReviewThreshold(40, 4)), tomorrow
    finally:
        repository.close()
