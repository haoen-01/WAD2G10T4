"""Multi-person coexistence tests (F2).

These tests exercise the repository directly (not the HTTP layer) because F2 explicitly keeps
`sql_repository.py`'s public methods keyword-only-with-a-demo-default -- the same shape the rest
of the test suite (and every existing caller) already relies on.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from silverloop.db_models import PersonRow, ScenarioRunRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.sql_repository import SqlAlchemyRepository

PERSON_B = "person-b"


@pytest.fixture
def repo() -> SqlAlchemyRepository:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()
    instance.reset()  # seeds DEMO_PERSON_ID
    instance.reset(person_id=PERSON_B, allow_new_person=True)
    return instance


# --- Bug #3: ensure_active_run must be person-scoped, not "does ANY run exist" -----------------


def test_ensure_active_run_is_person_scoped() -> None:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()
    instance.reset(person_id=PERSON_B, allow_new_person=True)  # only Person B has an active run

    instance.ensure_active_run()  # default DEMO_PERSON_ID

    # Must not have skipped seeding the demo person just because Person B's run is active.
    assert instance.person_state().person_id == DEMO_PERSON_ID
    instance.close()


# --- Independent identity, baseline and consent -------------------------------------------------


def test_two_people_have_independent_state(repo: SqlAlchemyRepository) -> None:
    state_a = repo.person_state()
    state_b = repo.person_state(person_id=PERSON_B)

    assert state_a.person_id == DEMO_PERSON_ID
    assert state_b.person_id == PERSON_B
    assert state_a.display_name == "Mdm Lim"
    assert state_b.display_name == PERSON_B  # generic fallback profile


def test_consent_change_for_one_person_does_not_affect_the_other(
    repo: SqlAlchemyRepository,
) -> None:
    repo.set_consent(False, "Person A withdraws.", "senior", person_id=DEMO_PERSON_ID)

    assert repo.person_state(person_id=DEMO_PERSON_ID).consent_active is False
    assert repo.person_state(person_id=PERSON_B).consent_active is True


def test_advance_targets_only_the_requested_person(repo: SqlAlchemyRepository) -> None:
    day_a_before = repo.person_state(person_id=DEMO_PERSON_ID).current_day
    day_b_before = repo.person_state(person_id=PERSON_B).current_day

    repo.advance("activity_declines", person_id=DEMO_PERSON_ID)

    assert repo.person_state(person_id=DEMO_PERSON_ID).current_day > day_a_before
    assert repo.person_state(person_id=PERSON_B).current_day == day_b_before


# --- Independent contact caps, decision evidence, interventions, cases, audit trails ------------


def test_contact_caps_are_independent_per_person(repo: SqlAlchemyRepository) -> None:
    for _ in range(4):
        repo.advance("activity_declines", person_id=DEMO_PERSON_ID)

    metrics_a = repo.metrics(person_id=DEMO_PERSON_ID)
    metrics_b = repo.metrics(person_id=PERSON_B)

    # Person A has been driven towards the contact cap; Person B has had zero events at all.
    assert metrics_a.decision_evidence == 4
    assert metrics_b.decision_evidence == 0


def test_decision_evidence_and_audit_trails_are_person_scoped(repo: SqlAlchemyRepository) -> None:
    repo.advance("activity_declines", person_id=DEMO_PERSON_ID)
    repo.advance("recovery", person_id=PERSON_B)

    events_a = repo.list_events(person_id=DEMO_PERSON_ID)
    events_b = repo.list_events(person_id=PERSON_B)

    assert all(event.person_id == DEMO_PERSON_ID for event in events_a)
    assert all(event.person_id == PERSON_B for event in events_b)
    # Person A's audit trail must not contain Person B's decision, and vice versa.
    ids_a = {event.event_id for event in events_a}
    ids_b = {event.event_id for event in events_b}
    assert ids_a.isdisjoint(ids_b)


def test_interventions_are_person_scoped(repo: SqlAlchemyRepository) -> None:
    advance_a = repo.advance("activity_declines", person_id=DEMO_PERSON_ID)
    advance_b = repo.advance("activity_declines", person_id=PERSON_B)
    assert advance_a.created_intervention is not None
    assert advance_b.created_intervention is not None

    interventions_a = repo.list_interventions(person_id=DEMO_PERSON_ID)
    interventions_b = repo.list_interventions(person_id=PERSON_B)

    assert all(item.person_id == DEMO_PERSON_ID for item in interventions_a)
    assert all(item.person_id == PERSON_B for item in interventions_b)
    assert advance_b.created_intervention.intervention_id not in {
        item.intervention_id for item in interventions_a
    }


def test_coordinator_queue_with_no_person_filter_unions_all_people(
    repo: SqlAlchemyRepository,
) -> None:
    for _ in range(3):
        repo.advance("activity_declines", person_id=DEMO_PERSON_ID)
    for _ in range(3):
        repo.advance("activity_declines", person_id=PERSON_B)

    scoped_a = repo.list_cases(person_id=DEMO_PERSON_ID)
    scoped_b = repo.list_cases(person_id=PERSON_B)
    union = repo.list_cases()  # None -> coordinator semantic: every active run

    assert len(union) == len(scoped_a) + len(scoped_b)
    person_ids_in_union = {case.person_id for case in union}
    assert person_ids_in_union == {DEMO_PERSON_ID, PERSON_B}


# --- Bug #1: preference learners must not cross people -------------------------------------------


def test_preference_learners_do_not_cross_people(repo: SqlAlchemyRepository) -> None:
    advance_a = repo.advance("activity_declines", person_id=DEMO_PERSON_ID)
    intervention_a = advance_a.created_intervention
    assert intervention_a is not None
    candidate_key = intervention_a.evidence["candidate_key"]

    # Person A accepts -- their preference for this candidate should rise.
    result_a = repo.record_outcome(intervention_a.intervention_id, "accepted")
    assert result_a.preference_after > result_a.preference_before
    preference_a_after_accept = repo.metrics(person_id=DEMO_PERSON_ID).candidate_preference_scores[
        candidate_key
    ]

    # Reset Person A so a fresh, identically-ranked candidate is offered, then have Person B
    # decline the same candidate repeatedly. Person B's declines must never move Person A's
    # already-recorded preference for that candidate.
    repo.reset(person_id=PERSON_B, allow_new_person=True)
    for _ in range(3):
        advance_b = repo.advance("activity_declines", person_id=PERSON_B)
        intervention_b = advance_b.created_intervention
        if intervention_b is None:
            continue
        repo.record_outcome(intervention_b.intervention_id, "declined")

    preference_a_unchanged = repo.metrics(person_id=DEMO_PERSON_ID).candidate_preference_scores[
        candidate_key
    ]
    assert preference_a_unchanged == preference_a_after_accept


# --- Bug #2: `dq_` evidence IDs must not collide across people -----------------------------------


def test_quality_evidence_ids_do_not_collide_across_people_with_identical_fixtures(
    repo: SqlAlchemyRepository,
) -> None:
    """Person A and Person B share the same seed (F2 ships exactly one curated persona), so
    without the person-scoped `dq_` format their evidence IDs on the identical fixture day would
    collide. This is the exact scenario the F2 spec calls out (evidence-ID collision table).
    """
    response_a = repo.advance("low_wear", person_id=DEMO_PERSON_ID)
    response_b = repo.advance("low_wear", person_id=PERSON_B)

    quality_id_a = response_a.state.signal.quality.evidence_id
    quality_id_b = response_b.state.signal.quality.evidence_id

    assert quality_id_a != quality_id_b
    assert quality_id_a.startswith(f"dq_{DEMO_PERSON_ID}_")
    assert quality_id_b.startswith(f"dq_{PERSON_B}_")


# --- Unknown-person vs known-person-without-a-run must map to different errors -------------------


def test_person_state_unknown_person_raises_key_error(repo: SqlAlchemyRepository) -> None:
    with pytest.raises(KeyError):
        repo.person_state(person_id="does-not-exist")


def test_person_state_known_person_without_active_run_raises_runtime_error(
    repo: SqlAlchemyRepository,
) -> None:
    with repo.sessions.begin() as session:
        session.add(
            PersonRow(
                person_id="orphan",
                display_name="Orphan",
                preferred_language="English",
                created_at=datetime.now(UTC),
            )
        )

    with pytest.raises(RuntimeError):
        repo.person_state(person_id="orphan")


def test_reset_creates_exactly_one_person_row_per_person_id(repo: SqlAlchemyRepository) -> None:
    with repo.sessions() as session:
        count = len(list(session.scalars(select(PersonRow))))
    assert count == 2


# --- reset() must not silently provision a person for an arbitrary string ----------------------


def test_reset_rejects_unknown_person_without_explicit_opt_in() -> None:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()

    with pytest.raises(ValueError):
        instance.reset(person_id="anything")

    with instance.sessions() as session:
        assert session.get(PersonRow, "anything") is None
    instance.close()


def test_reset_allows_unknown_person_with_explicit_opt_in() -> None:
    instance = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    instance.create_schema_for_tests()

    instance.reset(person_id="anything", allow_new_person=True)

    with instance.sessions() as session:
        assert session.get(PersonRow, "anything") is not None
    instance.close()


def test_reset_never_requires_opt_in_for_the_demo_person(repo: SqlAlchemyRepository) -> None:
    # Must not regress: DEMO_PERSON_ID is curated and keeps working with no opt-in argument.
    repo.reset()
    with repo.sessions() as session:
        assert session.get(PersonRow, DEMO_PERSON_ID) is not None


# --- daily_metrics: history read path -----------------------------------------------------------


def test_daily_metrics_default_window_is_oldest_first(repo: SqlAlchemyRepository) -> None:
    result = repo.daily_metrics(person_id=DEMO_PERSON_ID)

    assert len(result) == 14
    days = [entry.day for entry in result]
    assert days == sorted(days)


def test_daily_metrics_respects_a_smaller_day_limit(repo: SqlAlchemyRepository) -> None:
    full = repo.daily_metrics(person_id=DEMO_PERSON_ID, days=29)
    limited = repo.daily_metrics(person_id=DEMO_PERSON_ID, days=5)

    assert len(limited) == 5
    # The limited window is the most recent slice of the full history, still oldest-first.
    assert limited == full[-5:]


def test_daily_metrics_clamps_a_non_positive_day_count_to_at_least_one(
    repo: SqlAlchemyRepository,
) -> None:
    assert len(repo.daily_metrics(person_id=DEMO_PERSON_ID, days=0)) == 1
    assert len(repo.daily_metrics(person_id=DEMO_PERSON_ID, days=-5)) == 1


def test_daily_metrics_are_person_scoped(repo: SqlAlchemyRepository) -> None:
    metrics_a = repo.daily_metrics(person_id=DEMO_PERSON_ID, days=100)
    metrics_b = repo.daily_metrics(person_id=PERSON_B, days=100)

    days_a = {entry.day for entry in metrics_a}
    days_b = {entry.day for entry in metrics_b}
    # The curated demo persona and the generic persona are generated from disjoint calendar
    # windows, so any overlap would indicate the two people's history leaked into one another.
    assert days_a.isdisjoint(days_b)


def test_daily_metrics_unknown_person_raises_key_error(repo: SqlAlchemyRepository) -> None:
    with pytest.raises(KeyError):
        repo.daily_metrics(person_id="does-not-exist")


def test_daily_metrics_returns_empty_list_when_the_active_run_has_no_metrics(
    repo: SqlAlchemyRepository,
) -> None:
    with repo.sessions.begin() as session:
        session.add(
            PersonRow(
                person_id="metric-orphan",
                display_name="Orphan",
                preferred_language="English",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            ScenarioRunRow(
                run_id="run-metric-orphan",
                person_id="metric-orphan",
                seed=1,
                scenario_version="test",
                current_day=date(2026, 1, 1),
                active=True,
                started_at=datetime.now(UTC),
            )
        )

    assert repo.daily_metrics(person_id="metric-orphan") == []
