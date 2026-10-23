"""The planner already records enough to evidence itself; these read it back.

`_create_intervention` stores the deterministic ranker's choice alongside the candidate actually
sent, plus the planner's own `agent` record with its guardrail counters. Until F15 nothing read
any of it. Counting the agreement between the two candidate keys is an agent-versus-baseline
comparison over live data -- shadow-mode evidence without running anything in shadow.
"""

from __future__ import annotations

from sqlalchemy import select

from silverloop.db_models import InterventionRow
from silverloop.sql_repository import SqlAlchemyRepository


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def test_planner_metrics_are_zero_before_any_outreach() -> None:
    repository = _repo()
    try:
        metrics = repository.metrics()
        assert metrics.planner_runs == 0
        assert metrics.planner_agent_selected == 0
        assert metrics.planner_agreed_with_ranker == 0
        assert metrics.planner_fallback_modes == {}
        assert metrics.planner_guardrail_rejections == 0
        assert metrics.planner_guardrail_violations == 0
    finally:
        repository.close()


def test_every_intervention_contributes_exactly_one_planner_run() -> None:
    """The denominator is "runs where a planner decision was possible", not "runs"."""
    repository = _repo()
    try:
        for index in range(2):
            repository.advance("activity_declines", event_id=f"observability-{index}")

        metrics = repository.metrics()
        assert metrics.planner_runs == metrics.interventions == 2
        assert sum(metrics.planner_fallback_modes.values()) == metrics.planner_runs
    finally:
        repository.close()


def test_a_disabled_planner_is_reported_honestly_rather_than_as_agreement() -> None:
    """With no planner, the ranker chose -- that must not be counted as the agent agreeing.

    This is the failure this metric exists to make visible: a demo where the planner silently
    degraded looks identical to one where it ran, unless something reports the mode.
    """
    repository = _repo()
    try:
        repository.advance("activity_declines", event_id="observability-disabled")

        metrics = repository.metrics()
        assert metrics.planner_runs == 1
        # Whatever the local environment does, a run that did not reach the model must never be
        # counted as the agent selecting or agreeing.
        assert metrics.planner_agent_selected == 0
        assert metrics.planner_agreed_with_ranker == 0
        assert "agent" not in metrics.planner_fallback_modes
    finally:
        repository.close()


def test_agreement_is_only_counted_when_the_agent_actually_ran() -> None:
    """Synthetic evidence, because a real agent run needs credentials this suite never has."""
    repository = _repo()
    try:
        repository.advance("activity_declines", event_id="observability-synthetic")

        with repository.sessions.begin() as session:
            row = session.scalars(select(InterventionRow)).first()
            assert row is not None
            row.evidence_json = {
                **row.evidence_json,
                "candidate_key": "gentle_nudge:indoor_walk",
                "deterministic_candidate_key": "gentle_nudge:indoor_walk",
                "agent": {
                    "mode": "agent",
                    "rejected_proposal_count": 1,
                    "guardrail_violation_count": 4,
                },
            }
        metrics = repository.metrics()
        assert metrics.planner_agent_selected == 1
        assert metrics.planner_agreed_with_ranker == 1
        assert metrics.planner_guardrail_rejections == 1
        assert metrics.planner_guardrail_violations == 4
        assert metrics.planner_fallback_modes == {"agent": 1}
    finally:
        repository.close()


def test_disagreement_is_counted_as_a_run_but_not_an_agreement() -> None:
    repository = _repo()
    try:
        repository.advance("activity_declines", event_id="observability-disagree")

        with repository.sessions.begin() as session:
            row = session.scalars(select(InterventionRow)).first()
            assert row is not None
            row.evidence_json = {
                **row.evidence_json,
                "candidate_key": "gentle_nudge:chair_mobility",
                "deterministic_candidate_key": "gentle_nudge:indoor_walk",
                "agent": {"mode": "agent"},
            }

        metrics = repository.metrics()
        assert metrics.planner_agent_selected == 1
        assert metrics.planner_agreed_with_ranker == 0
    finally:
        repository.close()
