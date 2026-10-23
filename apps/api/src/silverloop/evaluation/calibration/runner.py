"""Drive the real repository through each (arm, profile, sequence) and record an id-free trace.

Every run is a fresh in-memory SQLite repository for `mdm-wong`, reset and then advanced one
authored day at a time through `SqlAlchemyRepository(authored_metric=...)`, which replaces the
simulation event's own reading with the authored one. The same repository methods the API calls
record the simulated coordinator's review (`review_case`) and, in the arms that approve, approve
whatever proposal is open that day (`approve_threshold_proposal`). Nothing is reimplemented: the
policy ladder, the shadow check, the floor, the calibrator, its guardrail, the reverts and the
audited skips are all the product's own.

Arms:

- `starting_setting`: LLM off, and nothing is ever approved -- the review setting the person
  starts with stays live. The reference every delay is measured against.
- `fixed_rule`: LLM off, so the deterministic fixed rule proposes; every open proposal is
  approved on the day of the review that produced it.
- `agent`: LLM on, with `ScriptedThresholdModel` (NOT A MODEL: a deterministic stand-in wearing a
  model's request shape) injected as the calibrator's transport, and approvals as `fixed_rule`.
  The provider is `recorded` with no recording, so every other LLM loop degrades to its offline
  fallback without a network call.

Imported explicitly, never by `silverloop.evaluation` itself: the repository, the settings and
the agent stand-in are imported lazily inside `run_one`.

The trace carries simulated sequence days, counts, kinds and ordinals -- never a database id, a
wall-clock time or free text -- so the report built from it is deterministic.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from silverloop.evaluation.calibration.profiles import (
    PROFILES,
    REVIEW_NOTE,
    ProfileName,
    counts_toward_loosening,
    judge,
)
from silverloop.evaluation.calibration.sequences import (
    CALIBRATION_SEQUENCES,
    CalibrationSequence,
)

ArmName = Literal["starting_setting", "fixed_rule", "agent"]
ARMS: tuple[ArmName, ...] = ("starting_setting", "fixed_rule", "agent")

PERSON = "mdm-wong"
COORDINATOR = "coordinator"
DATABASE_URL = "sqlite+pysqlite:///:memory:"

ARM_DESCRIPTIONS: dict[ArmName, str] = {
    "starting_setting": (
        "No proposal is ever approved: the starting review setting (40% below for three "
        "valid-wear days) stays live throughout."
    ),
    "fixed_rule": (
        "LLM off. The deterministic fixed rule proposes; the simulated coordinator approves "
        "every open proposal on the day of the review that produced it."
    ),
    "agent": (
        "LLM on with a scripted stand-in (NOT A MODEL) as the calibrator's transport; the "
        "simulated coordinator approves every open proposal on the day of the review that "
        "produced it. No network call is made."
    ),
}


@dataclass(frozen=True)
class DayRecord:
    day: int
    decision: str
    gate: str
    delta_percent: float
    sustained_low_days: int
    case_opened: bool
    # Whether any review case is still unresolved at the end of the day, after the day's review:
    # an acknowledged case keeps a decline in front of the coordinator (a later declining day
    # refreshes it rather than opening another), so it covers the day as a new case would.
    case_unresolved: bool
    # The review setting live on this day (as decided), after the day's advance.
    live_severity_pct: int
    live_persistence_days: int


@dataclass(frozen=True)
class ReviewRecord:
    ordinal: int
    opened_day: int
    episode_id: str | None
    status: str
    human_action: str
    override_reason: str | None
    reached_too_late: bool
    counts_toward_loosening: bool


@dataclass(frozen=True)
class ProposalRecord:
    ordinal: int
    proposed_on_day: int
    output_kind: str
    proposer: str
    direction: Literal["looser", "sooner", "none"]
    previous: tuple[int, int]
    proposed: tuple[int, int] | None
    trigger_review_ordinals: tuple[int, ...]
    # Reviews the proposal cites by id (the fixed rule cites every alarm it counted; the agent's
    # citations resolve to the trigger review).
    cited_review_ordinals: tuple[int, ...]
    status: str
    agent_mode: str | None


@dataclass(frozen=True)
class DecisionRecord:
    ordinal: int
    kind: str
    decided_on_day: int
    effective_from_day: int
    revert_trigger: str | None
    before: tuple[int, int]
    after: tuple[int, int] | None
    proposal_ordinal: int | None
    ends_approval_ordinal: int | None


@dataclass(frozen=True)
class ApprovalAttempt:
    day: int
    proposal_ordinal: int
    outcome: Literal["approved", "refused"]
    refusal: str | None


@dataclass
class RunTrace:
    arm: ArmName
    profile: ProfileName
    sequence_id: str
    days: list[DayRecord] = field(default_factory=list)
    reviews: list[ReviewRecord] = field(default_factory=list)
    proposals: list[ProposalRecord] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)
    approval_attempts: list[ApprovalAttempt] = field(default_factory=list)
    calibration_skips: dict[str, int] = field(default_factory=dict)
    calibration_discards: dict[str, int] = field(default_factory=dict)


def _settings(arm: ArmName) -> Any:
    from silverloop.config import Settings

    common: dict[str, Any] = {
        "_env_file": None,
        "database_url": DATABASE_URL,
        "silverloop_runtime_profile": "offline",
        "adapter_mode": "fixture",
        "external_context_enabled": False,
    }
    if arm != "agent":
        return Settings(**common, llm_enabled=False)
    from silverloop.evaluation.ranking_llm.scripted_model import SCRIPTED_MODEL_ID

    # `recorded` with no recording: every LLM loop but the injected calibrator reports itself
    # unavailable and falls back offline. It is the one provider that cannot reach a network.
    return Settings(
        **common,
        llm_enabled=True,
        llm_provider="recorded",
        llm_recording_path="",
        llm_model=SCRIPTED_MODEL_ID,
    )


def _threshold_client_factory(arm: ArmName) -> Callable[[], tuple[Any, str | None]] | None:
    if arm != "agent":
        return None
    from silverloop.evaluation.ranking_llm.scripted_model import ScriptedThresholdModel

    return lambda: (ScriptedThresholdModel(), None)


def authored_metric_for(
    sequence: CalibrationSequence, *, anchor: date, reference_steps: float
) -> Callable[[str, date], Any]:
    """The repository seam: the authored reading for `day`, or `None` outside the sequence."""
    from silverloop.models import DailyMetric

    def metric(person_id: str, day: date) -> Any:
        index = (day - anchor).days
        if person_id != PERSON or not 1 <= index <= len(sequence.days):
            return None
        authored = sequence.day(index)
        return DailyMetric(
            day=day,
            steps=round(authored.steps_fraction * reference_steps),
            active_minutes=round(authored.steps_fraction * 42),
            sleep_hours=7.0,
            wear_hours=authored.wear_hours,
            source="synthetic",
        )

    return metric


def _pair(value: Any) -> tuple[int, int]:
    return (int(value.severity_pct), int(value.persistence_days))


def run_one(arm: ArmName, profile: ProfileName, sequence: CalibrationSequence) -> RunTrace:
    from silverloop.models import CaseStatus, ReviewThresholdOutputKind
    from silverloop.sql_repository import ReviewThresholdConflict, SqlAlchemyRepository

    trace = RunTrace(arm=arm, profile=profile, sequence_id=sequence.sequence_id)
    # The seam is read on every advance; it is bound once the reset tells us the anchor day and the
    # person's anchored reference.
    bound: dict[str, Callable[[str, date], Any]] = {}

    def authored(person_id: str, day: date) -> Any:
        seam = bound.get("metric")
        return seam(person_id, day) if seam is not None else None

    repository = SqlAlchemyRepository(
        DATABASE_URL,
        settings=_settings(arm),
        threshold_client_factory=_threshold_client_factory(arm),
        authored_metric=authored,
    )
    try:
        repository.create_schema_for_tests()
        repository.reset(person_id=PERSON)
        start = repository.person_state(person_id=PERSON)
        anchor = start.current_day
        bound["metric"] = authored_metric_for(
            sequence, anchor=anchor, reference_steps=start.baseline.reference_steps
        )

        def day_of(value: date) -> int:
            return (value - anchor).days

        review_ordinals: dict[str, int] = {}
        attempts: list[tuple[int, str, Literal["approved", "refused"], str | None]] = []

        for authored_day in sequence.days:
            response = repository.advance(
                authored_day.event,
                event_id=f"calibration-{sequence.sequence_id}-{authored_day.day}",
                person_id=PERSON,
            )
            state = response.state
            if day_of(state.current_day) != authored_day.day:  # pragma: no cover - invariant
                raise RuntimeError("The simulated day and the authored day drifted apart.")
            created = response.created_case
            if created is not None:
                episode = sequence.episode_on(authored_day.day)
                judgement = judge(profile, episode, authored_day.day)
                reviewed = repository.review_case(
                    created.case_id,
                    judgement.status,
                    REVIEW_NOTE,
                    COORDINATOR,
                    human_action=judgement.human_action,
                    override_reason=judgement.override_reason,
                    reached_too_late=judgement.reached_too_late,
                )
                ordinal = len(trace.reviews) + 1
                review_ordinals[reviewed.review_evidence_id] = ordinal
                trace.reviews.append(
                    ReviewRecord(
                        ordinal=ordinal,
                        opened_day=authored_day.day,
                        episode_id=episode.episode_id if episode is not None else None,
                        status=judgement.status.value,
                        human_action=judgement.human_action.value,
                        override_reason=(
                            judgement.override_reason.value if judgement.override_reason else None
                        ),
                        reached_too_late=judgement.reached_too_late,
                        counts_toward_loosening=counts_toward_loosening(judgement),
                    )
                )
                if arm != "starting_setting":
                    threshold = repository.review_threshold_state(PERSON, viewer_sub=COORDINATOR)
                    proposal = threshold.open_proposal
                    if (
                        proposal is not None
                        and proposal.output_kind is ReviewThresholdOutputKind.PROPOSAL
                    ):
                        try:
                            repository.approve_threshold_proposal(
                                PERSON,
                                proposal.proposal_id,
                                cause_confirmed=True,
                                shown_on_day=threshold.current_day,
                                note=None,
                                actor=COORDINATOR,
                            )
                            attempts.append(
                                (authored_day.day, proposal.proposal_id, "approved", None)
                            )
                        except (ReviewThresholdConflict, ValueError) as error:
                            attempts.append(
                                (
                                    authored_day.day,
                                    proposal.proposal_id,
                                    "refused",
                                    type(error).__name__,
                                )
                            )
            live = repository.review_threshold_state(PERSON, viewer_sub=COORDINATOR).live
            unresolved = any(
                case.status is not CaseStatus.RESOLVED
                for case in repository.list_cases(person_id=PERSON)
            )
            trace.days.append(
                DayRecord(
                    day=authored_day.day,
                    decision=state.last_decision.value,
                    gate=state.decided_by_gate.value,
                    delta_percent=state.signal.delta_percent,
                    sustained_low_days=state.signal.sustained_low_days,
                    case_opened=created is not None,
                    case_unresolved=unresolved,
                    live_severity_pct=live.severity_pct,
                    live_persistence_days=live.persistence_days,
                )
            )

        final = repository.review_threshold_state(PERSON, viewer_sub=COORDINATOR)
        # `proposals` is newest first; ordinals count in the order the rows were stored.
        chronological = list(reversed(final.proposals))
        proposal_ordinals = {
            proposal.proposal_id: index for index, proposal in enumerate(chronological, start=1)
        }
        for proposal in chronological:
            ordinal = proposal_ordinals[proposal.proposal_id]
            proposed = _pair(proposal.proposed) if proposal.proposed is not None else None
            previous = _pair(proposal.previous)
            direction: Literal["looser", "sooner", "none"] = "none"
            if proposed is not None:
                direction = (
                    "looser" if proposed[0] > previous[0] or proposed[1] > previous[1] else "sooner"
                )
            trace.proposals.append(
                ProposalRecord(
                    ordinal=ordinal,
                    proposed_on_day=day_of(proposal.proposed_on_day),
                    output_kind=proposal.output_kind.value,
                    proposer=proposal.proposer.value,
                    direction=direction,
                    previous=previous,
                    proposed=proposed,
                    trigger_review_ordinals=tuple(
                        review_ordinals[review_id]
                        for review_id in proposal.trigger_review_ids
                        if review_id in review_ordinals
                    ),
                    cited_review_ordinals=tuple(
                        sorted(
                            {
                                review_ordinals[evidence_id]
                                for evidence_id in proposal.cited_evidence_ids
                                if evidence_id in review_ordinals
                            }
                        )
                    ),
                    status=proposal.status,
                    agent_mode=(proposal.agent_run or {}).get("mode"),
                )
            )
        trace.approval_attempts = [
            ApprovalAttempt(day, proposal_ordinals[proposal_id], outcome, refusal)
            for day, proposal_id, outcome, refusal in attempts
        ]
        decision_ordinals: dict[str, int] = {}
        ordered_decisions = sorted(
            final.decisions,
            key=lambda item: (item.decided_at, item.decision_id),
        )
        for index, decision in enumerate(ordered_decisions, start=1):
            decision_ordinals[decision.decision_id] = index
        for decision in ordered_decisions:
            trace.decisions.append(
                DecisionRecord(
                    ordinal=decision_ordinals[decision.decision_id],
                    kind=decision.kind.value,
                    decided_on_day=day_of(decision.decided_on_day),
                    effective_from_day=day_of(decision.effective_from_day),
                    revert_trigger=(
                        decision.revert_trigger.value if decision.revert_trigger else None
                    ),
                    before=_pair(decision.before),
                    after=_pair(decision.after) if decision.after is not None else None,
                    proposal_ordinal=(
                        proposal_ordinals.get(decision.proposal_id)
                        if decision.proposal_id
                        else None
                    ),
                    ends_approval_ordinal=(
                        decision_ordinals.get(decision.ends_approval_id)
                        if decision.ends_approval_id
                        else None
                    ),
                )
            )
        skips: Counter[str] = Counter()
        discards: Counter[str] = Counter()
        for event in repository.list_events(person_id=PERSON):
            reason = str((event.detail or {}).get("reason", "unknown"))
            if event.event_type == "review_threshold_calibration_skipped":
                skips[reason] += 1
            elif event.event_type == "review_threshold_calibration_discarded":
                discards[reason] += 1
        trace.calibration_skips = dict(sorted(skips.items()))
        trace.calibration_discards = dict(sorted(discards.items()))
        return trace
    finally:
        repository.close()


@dataclass(frozen=True)
class CalibrationResult:
    traces: tuple[RunTrace, ...]
    sequences: tuple[CalibrationSequence, ...]


def run_calibration_evaluation(
    sequences: tuple[CalibrationSequence, ...] = CALIBRATION_SEQUENCES,
    *,
    arms: tuple[ArmName, ...] = ARMS,
    profiles: tuple[ProfileName, ...] = PROFILES,
) -> CalibrationResult:
    traces = tuple(
        run_one(arm, profile, sequence)
        for sequence in sequences
        for profile in profiles
        for arm in arms
    )
    return CalibrationResult(traces=traces, sequences=sequences)


__all__ = [
    "ARMS",
    "ARM_DESCRIPTIONS",
    "ApprovalAttempt",
    "ArmName",
    "CalibrationResult",
    "DayRecord",
    "DecisionRecord",
    "ProposalRecord",
    "ReviewRecord",
    "RunTrace",
    "authored_metric_for",
    "run_calibration_evaluation",
    "run_one",
]
