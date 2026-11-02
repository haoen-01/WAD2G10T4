from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select, update

from silverloop.db_models import DailyMetricRow, DecisionEvidenceRow, ProgrammeRow
from silverloop.migrations import upgrade_database
from silverloop.models import Decision
from silverloop.sql_repository import SqlAlchemyRepository


def durable_repository(path: Path) -> SqlAlchemyRepository:
    url = f"sqlite+pysqlite:///{path}"
    upgrade_database(url)
    repository = SqlAlchemyRepository(url)
    repository.reset()
    return repository


def test_duplicate_event_replays_response_without_advancing_state(tmp_path: Path) -> None:
    database = tmp_path / "idempotency.db"
    repository = durable_repository(database)
    first = repository.advance("activity_declines", "event-demo-001")
    day_after_first = repository.person_state().current_day
    replay = repository.advance("activity_declines", "event-demo-001")

    assert replay == first
    assert repository.person_state().current_day == day_after_first
    with repository.sessions() as session:
        assert session.scalar(select(func.count()).select_from(DecisionEvidenceRow)) == 1
        assert session.scalar(select(func.count()).select_from(DailyMetricRow)) == 30

    repository.close()
    restarted = SqlAlchemyRepository(f"sqlite+pysqlite:///{database}")
    assert restarted.advance("activity_declines", "event-demo-001") == first
    restarted.close()


def test_idempotency_key_cannot_be_reused_for_another_event(tmp_path: Path) -> None:
    repository = durable_repository(tmp_path / "mismatched-key.db")
    repository.advance("activity_declines", "event-demo-002")
    with pytest.raises(ValueError, match="different simulation event"):
        repository.advance("recovery", "event-demo-002")
    repository.close()


def test_stale_programme_fixture_becomes_audited_no_action(tmp_path: Path) -> None:
    repository = durable_repository(tmp_path / "stale-programmes.db")
    with repository.sessions.begin() as session:
        session.execute(update(ProgrammeRow).values(valid_until=datetime(2026, 8, 1, tzinfo=UTC)))

    repository.advance("activity_declines", "event-stale-001")
    result = repository.advance("activity_declines", "event-stale-002")
    assert result.state.last_decision == Decision.NO_ACTION
    assert result.created_intervention is None
    assert any("freshness gate" in reason for reason in result.state.rationale)
    assert result.audit_event.detail["evidence_id"].startswith("decision_")
    repository.close()


def test_duplicate_outcome_is_rejected_without_extra_learning(tmp_path: Path) -> None:
    repository = durable_repository(tmp_path / "duplicate-outcome.db")
    advanced = repository.advance("activity_declines", "event-outcome-001")
    assert advanced.created_intervention is not None
    intervention_id = advanced.created_intervention.intervention_id
    repository.record_outcome(intervention_id, "no_response")
    score_after_first = repository.metrics().candidate_preference_scores

    with pytest.raises(ValueError, match="already been recorded"):
        repository.record_outcome(intervention_id, "no_response")
    assert repository.metrics().candidate_preference_scores == score_after_first
    repository.close()
