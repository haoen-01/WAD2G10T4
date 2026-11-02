from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DatabaseError
from sqlalchemy.schema import CreateTable

from silverloop.config import Settings
from silverloop.db_models import (
    Base,
    ConsentEvidenceRow,
    DecisionEvidenceRow,
    InterventionOutcomeRow,
    SimulationEventRow,
)
from silverloop.learning import PreferenceLearner
from silverloop.logging_config import agent_logger, request_logger
from silverloop.main import create_app
from silverloop.migrations import upgrade_database
from silverloop.sql_repository import SqlAlchemyRepository, _sync_database_url
from tests.row_fixtures import (
    activity_preferences,
    decide_baseline_confirmation,
    state_preference,
)


def file_repository(path: Path) -> SqlAlchemyRepository:
    database_url = f"sqlite+pysqlite:///{path}"
    upgrade_database(database_url)
    return SqlAlchemyRepository(database_url)


def test_migrated_sqlite_reports_offline_readiness(tmp_path: Path) -> None:
    repository = file_repository(tmp_path / "ready.db")

    readiness = repository.readiness("offline")

    assert readiness.status == "ready"
    assert readiness.database_backend == "sqlite"
    assert readiness.database_connected is True
    assert readiness.migration_revision == readiness.expected_migration_revision
    repository.close()


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("postgresql://user:pass@db.example/app", "postgresql+psycopg://user:pass@db.example/app"),
        ("postgres://user:pass@db.example/app", "postgresql+psycopg://user:pass@db.example/app"),
        (
            "postgresql+asyncpg://user:pass@db.example/app",
            "postgresql+psycopg://user:pass@db.example/app",
        ),
        (
            "postgresql+psycopg://user:pass@db.example/app",
            "postgresql+psycopg://user:pass@db.example/app",
        ),
        ("sqlite+aiosqlite:///demo.db", "sqlite+pysqlite:///demo.db"),
    ],
)
def test_sync_database_url_uses_installed_sync_drivers(database_url: str, expected: str) -> None:
    assert _sync_database_url(database_url) == expected


def test_state_and_outcomes_survive_repository_restart(tmp_path: Path) -> None:
    database = tmp_path / "persistent.db"
    first = file_repository(database)
    first.reset()
    advanced = first.advance("activity_declines")
    assert advanced.created_intervention is not None
    intervention_id = advanced.created_intervention.intervention_id
    result = first.record_outcome(intervention_id, "accepted")
    assert result.preference_after > result.preference_before
    day_before_restart = first.person_state().current_day
    first.close()

    restarted = SqlAlchemyRepository(f"sqlite+pysqlite:///{database}")
    restarted.ensure_active_run()
    assert restarted.person_state().current_day == day_before_restart
    assert restarted.list_interventions()[0].outcome == "accepted"
    scores = restarted.metrics().preference_scores
    # A bare `accepted` with no follow-through: weak positive ENGAGEMENT evidence, no EXPERIENCE
    # evidence at all. Compared against a freshly built learner fed the identical single outcome
    # (see `learning.PreferenceLearner` / ADR 0005), rather than a hardcoded 0.5 -- the product of
    # two Beta(1, 1) priors is 0.25, not 0.5, so "no evidence" is no longer the right threshold.
    expected = PreferenceLearner()
    expected.record("gentle_nudge", "accepted")
    assert scores["gentle_nudge"] == expected.expected_value("gentle_nudge")
    assert scores["gentle_nudge"] > PreferenceLearner().expected_value("gentle_nudge")
    restarted.close()


def test_confirmed_baseline_reference_survives_a_repository_restart(tmp_path: Path) -> None:
    """The candidate-baseline override (`BaselineConfirmationRow`) is read fresh from the database
    on every evaluation, never cached in memory -- so it must still apply after the process
    restarts, exactly like every other piece of durable evidence in this system. Uses real
    migrations (`file_repository`) rather than `create_all`, since the row this exercises depends
    on the migration in `b8e4f6c1a205_add_baseline_confirmations`.
    """
    from silverloop.models import BaselineConfirmationDecision

    database = tmp_path / "baseline-confirmation.db"
    first = file_repository(database)
    first.reset()
    response = None
    for index in range(60):
        response = first.advance("activity_declines", event_id=f"decline-{index}")
        if response.state.pending_baseline_confirmation is not None:
            break
    assert response is not None and response.state.pending_baseline_confirmation is not None
    person_id = response.state.person_id
    rolling_median = response.state.baseline.median_steps
    decide_baseline_confirmation(first, BaselineConfirmationDecision.CONFIRM, person_id=person_id)
    first.close()

    restarted = SqlAlchemyRepository(f"sqlite+pysqlite:///{database}")
    restarted.ensure_active_run(person_id=person_id)
    state = restarted.person_state(person_id=person_id)
    assert state.baseline.reference_steps == rolling_median
    assert state.baseline.effective_median_steps == state.baseline.median_steps
    restarted.close()


def test_reset_preserves_prior_append_only_evidence(tmp_path: Path) -> None:
    repository = file_repository(tmp_path / "reset.db")
    repository.reset()
    repository.advance("activity_declines")
    with repository.sessions() as session:
        decisions_before = session.scalar(select(func.count()).select_from(DecisionEvidenceRow))
        consents_before = session.scalar(select(func.count()).select_from(ConsentEvidenceRow))
    repository.reset()
    with repository.sessions() as session:
        assert (
            session.scalar(select(func.count()).select_from(DecisionEvidenceRow))
            == decisions_before
        )
        assert (
            session.scalar(select(func.count()).select_from(ConsentEvidenceRow)) > consents_before
        )
    repository.close()


def test_reset_no_longer_deletes_activity_dimension_preferences(tmp_path: Path) -> None:
    """ADR 0004 (`docs/adr/0004-run-scope-activity-dimension-preferences.md`): a demo reset used
    to be the only place this repository destroyed derived domain state. It no longer deletes
    `activity_dimension_preferences` rows at all.

    A *standing* stated preference (no `until`) is a standing instruction, exactly like an
    outreach mute, and is never scoped to the run it was made in -- it survives every reset. A
    *time-boxed* one (an `until` day) is a promise about a day on the calendar of the run it was
    stated in; a reset rewinds that calendar back to the fixture's anchor day, so the row is
    retired rather than let apply to a story it was never part of -- otherwise a reset could
    resurrect a promise that had already lapsed, simply because the calendar fell behind its
    `until` date again. Neither row is deleted; both are still on record."""
    from datetime import timedelta

    from silverloop.db_models import ActivityDimensionPreferenceRow
    from silverloop.fixtures import DEMO_PERSON_ID
    from silverloop.models import PreferenceDimension

    repository = file_repository(tmp_path / "reset-preferences.db")
    repository.reset()
    state_preference(
        repository,
        PreferenceDimension.ENVIRONMENT,
        "outdoor",
        prefer=False,
        person_id=DEMO_PERSON_ID,
    )
    until = repository.person_state().current_day + timedelta(days=3)
    state_preference(
        repository,
        PreferenceDimension.ACTIVITY_TYPE,
        "walking",
        prefer=False,
        person_id=DEMO_PERSON_ID,
        until=until,
    )
    with repository.sessions() as session:
        rows_before = session.scalar(
            select(func.count()).select_from(ActivityDimensionPreferenceRow)
        )
    assert rows_before == 2

    repository.reset()

    with repository.sessions() as session:
        rows_after = session.scalar(
            select(func.count()).select_from(ActivityDimensionPreferenceRow)
        )
    assert rows_after == rows_before

    # The standing preference survives; the time-boxed one does not, whether or not it had
    # already lapsed by the wall clock -- it belonged to a run that is no longer active.
    assert [
        d.value for d in activity_preferences(repository, person_id=DEMO_PERSON_ID).dimensions
    ] == ["outdoor"]
    repository.close()


def test_sqlite_migration_enforces_append_only_decisions(tmp_path: Path) -> None:
    repository = file_repository(tmp_path / "append-only.db")
    repository.reset()
    repository.advance("activity_declines")
    with (
        pytest.raises(DatabaseError, match="append-only evidence"),
        repository.engine.begin() as connection,
    ):
        connection.execute(update(DecisionEvidenceRow).values(decision="tampered"))
    repository.close()


def test_sqlite_migration_enforces_append_only_idempotency_evidence(tmp_path: Path) -> None:
    repository = file_repository(tmp_path / "append-only-events.db")
    repository.reset()
    repository.advance("activity_declines", "event-immutable-001")
    with (
        pytest.raises(DatabaseError, match="append-only evidence"),
        repository.engine.begin() as connection,
    ):
        connection.execute(update(SimulationEventRow).values(event_name="tampered"))
    repository.close()


def test_schema_compiles_for_postgresql() -> None:
    dialect = postgresql.dialect()
    compiled = [
        str(CreateTable(table).compile(dialect=dialect)) for table in Base.metadata.sorted_tables
    ]
    # 13 before the follow-through loop; +3 for `intervention_follow_through`,
    # `candidate_preferences` and `day_disputes`; +2 for the activity catalogue and the
    # dimensional preferences behind the user-initiated loop; +5 for enjoyment, proposed
    # memories, context-question answers, goals and the week plan; +1 for
    # `baseline_confirmations`; +3 for the user-initiated loop closing -- offer responses,
    # plan follow-through and plan enjoyment; +1 for `replan_offers`, the store that turns
    # replanning from a recomputed read view into a recorded, answerable loop; +2 for the
    # review-threshold calibrator's append-only `review_threshold_proposals` and
    # `review_threshold_decisions` (ADR 0008); +5 for family groups: `accounts`, `care_groups`,
    # `group_members`, `family_pins` and `pin_attempts`; +3 for the family calendar:
    # `appointments`, `availability_entries` and `helper_assignments`; +1 for `family_activity`,
    # the family feed; +1 for `appointment_notes`; +2 for `tasks` and `task_ticks`.
    assert len(compiled) == 42
    assert any("decision_evidence" in statement for statement in compiled)
    assert any("simulation_events" in statement for statement in compiled)
    for table in (
        "intervention_follow_through",
        "candidate_preferences",
        "day_disputes",
        "activity_candidates",
        "activity_dimension_preferences",
        "intervention_enjoyment",
        "proposed_memories",
        "context_question_answers",
        "activity_goals",
        "week_plan_entries",
        "baseline_confirmations",
        "activity_offer_responses",
        "plan_follow_through",
        "plan_enjoyment",
        "replan_offers",
        "review_threshold_proposals",
        "review_threshold_decisions",
        "accounts",
        "care_groups",
        "group_members",
        "family_pins",
        "pin_attempts",
        "appointments",
        "availability_entries",
        "helper_assignments",
        "family_activity",
        "appointment_notes",
        "tasks",
        "task_ticks",
    ):
        assert any(table in statement for statement in compiled), f"{table} missing from schema"


# ── Append-only evidence and migration-only constraints ──────────────────────────────────────
#
# `apps/api/tests/conftest.py`'s `repository`/`client` fixtures build their schema with
# `Base.metadata.create_all(...)`, which every other test in this suite runs against. That never
# creates the `intervention_outcomes_reject_update`/`_reject_delete` (SQLite) or
# `intervention_outcomes_append_only` (Postgres) triggers `3c430fbc9737` adds -- so a bug in a
# migration-only constraint, such as `record_outcome`'s reason-amendment path doing a plain
# `UPDATE` on an append-only table, was invisible to the whole suite and only surfaced against a
# database built by `alembic upgrade head` (`pnpm demo:offline`, the live Supabase demo). These
# tests reuse `file_repository` above -- the same "run the real migrations" approach
# `test_state_and_outcomes_survive_repository_restart` already established -- specifically to
# close that hole for this table.


def test_reason_amendment_succeeds_against_a_migrated_schema(tmp_path: Path) -> None:
    """The senior screen always saves "Not today" on its own and only then offers the optional
    "why?", so the reason necessarily arrives as a second call. Against a migrated schema this
    used to 500: the amendment path mutated the already-recorded `InterventionOutcomeRow` in
    place, and the append-only trigger on `intervention_outcomes` rejects UPDATE outright.
    """
    repository = file_repository(tmp_path / "amendment.db")
    repository.reset()
    first = repository.advance("activity_declines")
    intervention_id = first.created_intervention.intervention_id

    declined = repository.record_outcome(intervention_id, "declined")
    assert declined.outcome == "declined"

    amended = repository.record_outcome(intervention_id, "declined", reason="not_for_me")
    assert amended.audit_event.event_type == "intervention_outcome_reason_added"

    with repository.sessions() as session:
        rows = list(
            session.scalars(
                select(InterventionOutcomeRow)
                .where(InterventionOutcomeRow.intervention_id == intervention_id)
                .order_by(InterventionOutcomeRow.recorded_at, InterventionOutcomeRow.outcome_id)
            )
        )
    # Append-only: the reason arrived as a second evidence row, never as a rewrite of the first --
    # which is also why this succeeds at all against a schema with reject-update triggers.
    assert len(rows) == 2
    assert rows[0].reason is None
    assert rows[1].reason == "not_for_me"
    repository.close()


def test_sqlite_migration_enforces_append_only_intervention_outcomes(tmp_path: Path) -> None:
    """The specific trigger BUG 1 hit, pinned directly -- not only through the repository's own
    (now append-only) code path -- so a future change that goes back to `UPDATE`ing a row in
    place fails loudly here rather than as an unexplained 500 on the demo path.
    """
    repository = file_repository(tmp_path / "append-only-outcomes.db")
    repository.reset()
    first = repository.advance("activity_declines")
    intervention_id = first.created_intervention.intervention_id
    repository.record_outcome(intervention_id, "declined")
    with (
        pytest.raises(DatabaseError, match="append-only evidence"),
        repository.engine.begin() as connection,
    ):
        connection.execute(
            update(InterventionOutcomeRow)
            .where(InterventionOutcomeRow.intervention_id == intervention_id)
            .values(reason="tampered")
        )
    repository.close()


def test_the_senior_decline_then_reason_flow_works_over_http_against_a_migrated_schema(
    tmp_path: Path,
) -> None:
    """The exact two-call sequence from the senior UI ("Not today", then the optional "why?"),
    over HTTP, against a database whose schema came from `alembic upgrade head` -- proving the fix
    end to end rather than only at the repository layer.
    """
    repository = file_repository(tmp_path / "amendment-http.db")
    settings = Settings(
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        silverloop_runtime_profile="offline",
        auth_enabled=False,
        llm_enabled=False,
    )
    application = create_app(repository, settings=settings, migrate_on_start=False)
    try:
        with TestClient(application) as client:
            client.post("/v1/demo/reset")
            advanced = client.post(
                "/v1/simulation/advance", json={"event": "activity_declines"}
            ).json()
            intervention_id = advanced["created_intervention"]["intervention_id"]

            declined = client.post(
                f"/v1/interventions/{intervention_id}/outcome", json={"outcome": "declined"}
            )
            assert declined.status_code == 200, declined.text

            amended = client.post(
                f"/v1/interventions/{intervention_id}/outcome",
                json={"outcome": "declined", "reason": "not_for_me"},
            )
            assert amended.status_code == 200, amended.text
    finally:
        repository.close()


def test_running_migrations_does_not_silence_the_structured_loggers(tmp_path: Path) -> None:
    """`alembic/env.py` calls `logging.config.fileConfig`, whose default
    `disable_existing_loggers=True` switches off every logger it does not name -- and
    `alembic.ini` names only root, sqlalchemy and alembic.

    The API builds `silverloop.request` in `create_app` and then runs `alembic upgrade head` in
    its own lifespan, so the default would leave the structured request log and the planner's
    provider-failure warning permanently disabled in any deployment that migrates on start. Both
    are operator surfaces, and the planner's is now the *only* record of a provider error's text;
    they must survive a migration.
    """
    request_log = request_logger()
    agent_log = agent_logger()
    assert not request_log.disabled and not agent_log.disabled

    upgrade_database(f"sqlite+pysqlite:///{tmp_path / 'logging.db'}")

    assert not request_log.disabled
    assert not agent_log.disabled
