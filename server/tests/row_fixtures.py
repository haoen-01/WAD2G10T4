"""Direct row fixtures for state that no route or repository method writes any more.

Step 7 (AAC route removal) took out the routes no screen used, and with them the only writers of
several tables that `advance` still reads: week plans, goals, day disputes, context answers,
baseline confirmations, enjoyment and follow-through reports, coordinator reviews and
review-setting decisions. The `advance` code that reads them is unchanged, so the tests that pin
it set the state up here, one row at a time, exactly as the removed writer stored it. A few read
helpers sit beside them (the audit trail, the world model, the activity preferences, the
catalogue) for reads whose route went but whose repository code `advance` or `metrics()` still
runs. Nothing in this module is application code: it exists only so those tests keep testing what
`advance` does with that state.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from silverloop.db_models import (
    ActivityCandidateRow,
    ActivityDimensionPreferenceRow,
    AuditEventRow,
    BaselineConfirmationRow,
    CandidatePreferenceRow,
    CaseReviewRow,
    ContextQuestionAnswerRow,
    DailyMetricRow,
    DayDisputeRow,
    InterventionFollowThroughRow,
    InterventionRow,
    PlanFollowThroughRow,
    ReviewCaseRow,
    WeekPlanEntryRow,
)
from silverloop.local_time import at_local, local_date
from silverloop.models import (
    ActivityAvailability,
    ActivityCandidate,
    ActivityPreferences,
    AuditEvent,
    BaselineConfirmationDecision,
    CaseResolution,
    CaseStatus,
    ContextGapCategory,
    FollowThrough,
    HumanAction,
    OverrideReason,
    PersonWorldModel,
    PlannedFollowThrough,
    PreferenceDimension,
)
from silverloop.sql_repository import SqlAlchemyRepository


def _id(prefix: str) -> str:
    """The same shape `sql_repository._id` gives a stored row id."""
    return f"{prefix}_{uuid4().hex[:16]}"


def _now() -> datetime:
    return datetime.now(UTC)


def mute_candidate(
    repo: SqlAlchemyRepository,
    candidate_key: str,
    *,
    person_id: str,
    suppressed: bool = True,
    reason: str | None = "not for me",
    actor: str = "senior",
) -> None:
    """A person's own mute (or un-mute) of one suggestion, as `set_candidate_preference` stored it:
    one row per person and key, updated in place."""
    with repo.sessions.begin() as session:
        row = session.scalar(
            select(CandidatePreferenceRow).where(
                CandidatePreferenceRow.person_id == person_id,
                CandidatePreferenceRow.candidate_key == candidate_key,
            )
        )
        if row is None:
            session.add(
                CandidatePreferenceRow(
                    preference_id=_id("pref"),
                    person_id=person_id,
                    candidate_key=candidate_key,
                    suppressed=suppressed,
                    reason=reason,
                    actor=actor,
                    updated_at=_now(),
                )
            )
        else:
            row.suppressed = suppressed
            row.reason = reason
            row.actor = actor
            row.updated_at = _now()


def active_run_id(repo: SqlAlchemyRepository, person_id: str) -> str:
    with repo.sessions() as session:
        return repo._active_run(session, person_id).run_id


def decide_baseline_confirmation(
    repo: SqlAlchemyRepository,
    decision: BaselineConfirmationDecision,
    *,
    person_id: str,
    actor: str = "senior",
) -> float:
    """The senior's answer to "is this your new normal?", stored as
    `decide_baseline_confirmation` stored it: one append-only row for the question pending now.
    Returns the reference in effect after the answer (the rolling median on a confirm)."""
    state = repo.person_state(person_id=person_id)
    pending = state.pending_baseline_confirmation
    assert pending is not None, "no baseline confirmation is pending"
    new_reference_steps = (
        state.baseline.median_steps if decision is BaselineConfirmationDecision.CONFIRM else None
    )
    with repo.sessions.begin() as session:
        session.add(
            BaselineConfirmationRow(
                confirmation_id=_id("baseconf"),
                run_id=repo._active_run(session, person_id).run_id,
                person_id=person_id,
                decision=decision.value,
                streak_days=pending.streak_days,
                previous_reference_steps=state.baseline.reference_steps,
                new_reference_steps=new_reference_steps,
                decided_on_day=state.current_day,
                decided_at=_now(),
                actor=actor,
            )
        )
    return state.baseline.reference_steps if new_reference_steps is None else new_reference_steps


def answer_context_question(
    repo: SqlAlchemyRepository,
    value: str,
    *,
    person_id: str,
    note: str | None = None,
    actor: str = "senior",
) -> None:
    """One answer to the pending context question, stored as `answer_context_question` stored
    it: about the person's current simulated day. (The proposed memory it could raise is not
    written: nothing kept reads `ProposedMemoryRow`.)"""
    state = repo.person_state(person_id=person_id)
    assert state.pending_question is not None, "no context question is pending"
    with repo.sessions.begin() as session:
        session.add(
            ContextQuestionAnswerRow(
                answer_id=_id("ctxans"),
                run_id=repo._active_run(session, person_id).run_id,
                person_id=person_id,
                question_id=state.pending_question.question_id,
                value=value,
                note=note,
                actor=actor,
                answered_at=_now(),
                answered_on_day=state.current_day,
            )
        )


def record_case_review(
    repo: SqlAlchemyRepository,
    case_id: str,
    status: CaseStatus,
    note: str,
    reviewer: str = "coordinator",
    *,
    human_action: HumanAction | None = None,
    override_reason: OverrideReason | None = None,
    reached_too_late: bool = False,
    context_gap_category: ContextGapCategory | None = None,
) -> None:
    """One human review of a case, stored as `review_case` stored it: the case takes the new
    status (a resolution is a coordinator's decision) and one row is appended to its trail,
    stamped on the run's review-setting clock. No calibration follows: that ran from
    `review_case` itself, which went with `POST /v1/cases/{id}/review` in step 7."""
    with repo.sessions.begin() as session:
        case = session.get(ReviewCaseRow, case_id)
        assert case is not None, f"no case {case_id}"
        assert case.status != CaseStatus.RESOLVED.value, "a resolved case is terminal"
        recorded_at = repo._threshold_clock(session, case.run_id, _now())
        case.status = status.value
        if status == CaseStatus.RESOLVED:
            case.resolution = CaseResolution.COORDINATOR_DECISION.value
        session.add(
            CaseReviewRow(
                review_id=_id("review"),
                case_id=case_id,
                run_id=case.run_id,
                status=status.value,
                reviewer=reviewer,
                note=note,
                recorded_at=recorded_at,
                agent_recommendation=case.recommendation,
                human_action=human_action.value if human_action else None,
                override_reason=override_reason.value if override_reason else None,
                reached_too_late=reached_too_late,
                context_gap_category=context_gap_category.value if context_gap_category else None,
            )
        )


def audit_events(repo: SqlAlchemyRepository, *, person_id: str) -> list[AuditEvent]:
    """The person's audit trail for their active run, newest first -- the read
    `list_events` made for `GET /v1/simulation/events` (both removed in step 7)."""
    with repo.sessions() as session:
        run = repo._active_run(session, person_id)
        rows = session.scalars(
            select(AuditEventRow)
            .where(AuditEventRow.run_id == run.run_id)
            .order_by(AuditEventRow.recorded_at.desc(), AuditEventRow.event_id.desc())
        )
        return [repo._to_audit(row) for row in rows]


def state_preference(
    repo: SqlAlchemyRepository,
    dimension: PreferenceDimension,
    value: str,
    *,
    prefer: bool,
    person_id: str,
    until: date | None = None,
    stated_text: str | None = None,
) -> None:
    """A person's own "prefer" or "avoid" on a kind of activity, stored as `state_preference`
    stored it (through `_confirm_dimension_preference`): a confirmed `senior_statement` row at
    full strength, standing or until a day of this run, consuming any inferred row on its key."""
    now = _now()
    strength = 1.0 if prefer else -1.0
    with repo.sessions.begin() as session:
        run = repo._active_run(session, person_id)
        assert until is None or until >= run.current_day, "that day has already passed"
        expires_at = (
            at_local(until, 23, 59) if until is not None and until >= run.current_day else None
        )
        keyed = (
            ActivityDimensionPreferenceRow.person_id == person_id,
            ActivityDimensionPreferenceRow.dimension == dimension.value,
            ActivityDimensionPreferenceRow.value == value,
        )
        row = session.scalar(
            select(ActivityDimensionPreferenceRow).where(
                *keyed, ActivityDimensionPreferenceRow.source == "senior_statement"
            )
        )
        inferred_rows = list(
            session.scalars(
                select(ActivityDimensionPreferenceRow).where(
                    *keyed,
                    ActivityDimensionPreferenceRow.source != "senior_statement",
                    ActivityDimensionPreferenceRow.superseded_by.is_(None),
                )
            )
        )
        if row is None:
            row = ActivityDimensionPreferenceRow(
                preference_id=_id("dimpref"),
                person_id=person_id,
                dimension=dimension.value,
                value=value,
                strength=strength,
                source="senior_statement",
                confirmed=True,
                observations=1,
                updated_at=now,
                first_observed_at=now,
            )
            session.add(row)
        else:
            lapsed = repo._preference_inactive(row, run.current_day, run.run_id)
            reversed_stance = (row.strength > 0) != (strength > 0)
            row.strength = strength
            row.confirmed = True
            row.observations = 1
            row.updated_at = now
            if lapsed or reversed_stance or row.first_observed_at is None:
                row.first_observed_at = now
            if reversed_stance:
                row.stated_text = None
            row.superseded_by = None
        row.expires_at = expires_at
        row.run_id = run.run_id if expires_at is not None else None
        if stated_text is not None:
            row.stated_text = stated_text
        row.positive_evidence = 1.0 if strength >= 0 else 0.0
        row.negative_evidence = 0.0 if strength >= 0 else 1.0
        session.flush()
        for inferred in inferred_rows:
            inferred.superseded_by = row.preference_id
            inferred.updated_at = now
            row.origin_id = inferred.preference_id


def activity_preferences(repo: SqlAlchemyRepository, *, person_id: str) -> ActivityPreferences:
    """What Care+ believes about the kinds of activity the person prefers, read the way
    `advance` reads it -- the read behind `GET /v1/people/{id}/activity-preferences` (removed)."""
    with repo.sessions() as session:
        run = repo._active_run(session, person_id)
        return repo._activity_preferences_model(session, person_id, run.current_day, run.run_id)


def plan_activity(
    repo: SqlAlchemyRepository, activity_id: str, day: date, *, person_id: str
) -> str:
    """Put one listing on the person's own week, as `plan_activity` stored it: a `chosen` row of
    the active run, for a day of the current week not yet past, on the day the listing runs and
    only while it has room. Re-planning the same listing on the same day returns the same row.
    Returns the plan id."""
    with repo.sessions.begin() as session:
        run = repo._active_run(session, person_id)
        listing = session.get(ActivityCandidateRow, activity_id)
        assert listing is not None, f"no listing {activity_id}"
        week_starting = run.current_day - timedelta(days=run.current_day.weekday())
        assert week_starting <= day <= week_starting + timedelta(days=6), "outside the week"
        assert day >= run.current_day, "that day has already passed"
        if listing.start_at is not None:
            start = listing.start_at
            start = start if start.tzinfo is not None else start.replace(tzinfo=UTC)
            assert local_date(start) == day, "the listing does not run that day"
        assert listing.availability != ActivityAvailability.FULL.value, "fully booked"
        existing = session.scalar(
            select(WeekPlanEntryRow).where(
                WeekPlanEntryRow.run_id == run.run_id,
                WeekPlanEntryRow.person_id == person_id,
                WeekPlanEntryRow.day == day,
                WeekPlanEntryRow.activity_id == activity_id,
            )
        )
        if existing is not None:
            return existing.plan_id
        plan_id = _id("plan")
        session.add(
            WeekPlanEntryRow(
                plan_id=plan_id,
                run_id=run.run_id,
                person_id=person_id,
                day=day,
                activity_id=activity_id,
                origin="chosen",
                replaced_reason=None,
                created_at=_now(),
            )
        )
        return plan_id


def record_planned_follow_through(
    repo: SqlAlchemyRepository,
    plan_id: str,
    follow_through: PlannedFollowThrough,
    *,
    person_id: str,
    note: str | None = None,
    actor: str = "senior",
) -> None:
    """What happened to a planned activity, as `record_planned_follow_through` stored it: one
    report per plan of the active run, once the plan's day has passed."""
    with repo.sessions.begin() as session:
        run = repo._active_run(session, person_id)
        plan = session.get(WeekPlanEntryRow, plan_id)
        assert plan is not None and plan.run_id == run.run_id, "not this run's plan"
        assert plan.replaced_reason is None, "that activity was replaced"
        assert plan.day < run.current_day, "that activity has not happened yet"
        session.add(
            PlanFollowThroughRow(
                follow_through_id=_id("pft"),
                plan_id=plan_id,
                run_id=run.run_id,
                person_id=person_id,
                follow_through=follow_through.value,
                note=note,
                actor=actor,
                recorded_at=_now(),
            )
        )


def world_model(repo: SqlAlchemyRepository, *, person_id: str) -> PersonWorldModel:
    """Everything Care+ knows about one person -- the assembly `metrics()` still runs for
    `world_model_quality`, read for one person as `GET /v1/people/{id}/world-model` did."""
    with repo.sessions() as session:
        run = repo._active_run(session, person_id)
        return repo._world_models(session, [run])[run.run_id]


def catalogue(repo: SqlAlchemyRepository) -> list[ActivityCandidate]:
    """The whole activity catalogue, read the way `advance` reads it."""
    with repo.sessions() as session:
        return repo._activity_candidate_models(session)


def dispute_day(
    repo: SqlAlchemyRepository,
    day: date,
    *,
    accurate: bool,
    person_id: str,
    note: str | None = None,
    actor: str = "senior",
) -> None:
    """The person's own account of a recorded day, as `record_day_dispute` stored it: an
    append-only row beside the reading, which is never touched."""
    with repo.sessions.begin() as session:
        run = repo._active_run(session, person_id)
        reading = session.scalar(
            select(DailyMetricRow).where(
                DailyMetricRow.run_id == run.run_id, DailyMetricRow.day == day
            )
        )
        assert reading is not None, f"no reading for {day}"
        session.add(
            DayDisputeRow(
                dispute_id=_id("dispute"),
                run_id=run.run_id,
                person_id=person_id,
                day=day,
                accurate=accurate,
                note=note,
                actor=actor,
                recorded_at=_now(),
            )
        )


def record_follow_through(
    repo: SqlAlchemyRepository,
    intervention_id: str,
    follow_through: FollowThrough,
    *,
    note: str | None = None,
    actor: str = "senior",
) -> None:
    """Whether an accepted suggestion actually happened, as `record_follow_through` stored it:
    one row per intervention, only after the person accepted it."""
    with repo.sessions.begin() as session:
        row = session.get(InterventionRow, intervention_id)
        assert row is not None, f"no intervention {intervention_id}"
        assert repo._latest_outcome(session, intervention_id) == "accepted", "not accepted"
        assert repo._follow_through_row(session, intervention_id) is None, "already recorded"
        session.add(
            InterventionFollowThroughRow(
                follow_through_id=_id("follow"),
                intervention_id=intervention_id,
                run_id=row.run_id,
                person_id=row.person_id,
                follow_through=follow_through.value,
                note=note,
                actor=actor,
                recorded_at=_now(),
            )
        )
