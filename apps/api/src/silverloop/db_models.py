from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PersonRow(Base):
    __tablename__ = "people"

    person_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160))
    preferred_language: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScenarioRunRow(Base):
    __tablename__ = "scenario_runs"
    __table_args__ = (Index("ix_scenario_runs_active", "active"),)

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    seed: Mapped[int] = mapped_column(Integer)
    scenario_version: Mapped[str] = mapped_column(String(40))
    current_day: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DailyMetricRow(Base):
    __tablename__ = "daily_metrics"
    __table_args__ = (
        UniqueConstraint("run_id", "day", name="uq_daily_metrics_run_day"),
        Index("ix_daily_metrics_run_day", "run_id", "day"),
    )

    metric_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(96), unique=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    steps: Mapped[int] = mapped_column(Integer)
    active_minutes: Mapped[int] = mapped_column(Integer)
    sleep_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    wear_hours: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(80))
    fixture_classification: Mapped[str] = mapped_column(String(40))
    ingestion_confidence: Mapped[float] = mapped_column(Float, default=1.0)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SimulationEventRow(Base):
    __tablename__ = "simulation_events"
    __table_args__ = (
        UniqueConstraint("run_id", "client_event_id", name="uq_simulation_event_run_client"),
        Index("ix_simulation_events_run_recorded", "run_id", "recorded_at"),
    )

    simulation_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_event_id: Mapped[str] = mapped_column(String(96))
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    event_name: Mapped[str] = mapped_column(String(80))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConsentEvidenceRow(Base):
    __tablename__ = "consent_evidence"
    __table_args__ = (Index("ix_consent_person_recorded", "person_id", "recorded_at"),)

    evidence_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(240))
    actor: Mapped[str] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DecisionEvidenceRow(Base):
    __tablename__ = "decision_evidence"
    __table_args__ = (
        Index("ix_decision_run_recorded", "run_id", "recorded_at"),
        Index("ix_decision_person_observed", "person_id", "observed_at"),
    )

    evidence_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(80))
    fixture_classification: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float)
    policy_version: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str] = mapped_column(String(48))
    reasons_json: Mapped[list[str]] = mapped_column(JSON)
    input_event: Mapped[str] = mapped_column(String(80))
    quality_evidence_id: Mapped[str] = mapped_column(String(96))


class InterventionRow(Base):
    __tablename__ = "interventions"
    __table_args__ = (Index("ix_interventions_run_created", "run_id", "created_at"),)

    intervention_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    decision_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("decision_evidence.evidence_id"), index=True
    )
    decision: Mapped[str] = mapped_column(String(48))
    title: Mapped[str] = mapped_column(String(240))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class InterventionOutcomeRow(Base):
    __tablename__ = "intervention_outcomes"
    __table_args__ = (Index("ix_outcomes_intervention_recorded", "intervention_id", "recorded_at"),)

    outcome_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intervention_id: Mapped[str] = mapped_column(
        ForeignKey("interventions.intervention_id"), index=True
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    outcome: Mapped[str] = mapped_column(String(48))
    # Optional one-tap context on a decline (`DeclineReason`). Nullable and always skippable:
    # a response is never withheld because someone did not want to explain it.
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # How far that reason reaches (`models.ClarificationScope`). Nullable, skippable, and
    # item-level when absent -- the same rule the search-side decline follows.
    clarification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    reviewer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InterventionFollowThroughRow(Base):
    """What actually happened after a suggestion was accepted.

    A separate table rather than another column on `intervention_outcomes` because it answers a
    different question at a different time: the outcome is the tap, this is the week afterwards.
    Collapsing them would make "accepted" and "did it" indistinguishable in storage, which is the
    exact conflation the follow-through loop exists to undo.

    One row per intervention, enforced in the database -- a second report would double-count one
    intervention's evidence in the preference posterior.
    """

    __tablename__ = "intervention_follow_through"
    __table_args__ = (
        UniqueConstraint("intervention_id", name="uq_follow_through_intervention"),
        Index("ix_follow_through_run_recorded", "run_id", "recorded_at"),
    )

    follow_through_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intervention_id: Mapped[str] = mapped_column(
        ForeignKey("interventions.intervention_id"), index=True
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    follow_through: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CandidatePreferenceRow(Base):
    """A durable, person-owned decision to mute (or un-mute) one kind of suggestion.

    Scoped to the person rather than the scenario run: "stop offering me this" is a statement
    about the person's life, not about one demo session, and resetting the demo must not quietly
    start offering something they asked not to see.
    """

    __tablename__ = "candidate_preferences"
    __table_args__ = (
        UniqueConstraint("person_id", "candidate_key", name="uq_candidate_preference_person_key"),
    )

    preference_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    candidate_key: Mapped[str] = mapped_column(String(120))
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DayDisputeRow(Base):
    """A person's own account of a day Care+ read from a sensor.

    Append-only and strictly additive: the `daily_metrics` row it refers to is never modified.
    The device reading and the person's account are both kept, and the quality assessment reports
    that they disagree rather than silently picking one.
    """

    __tablename__ = "day_disputes"
    __table_args__ = (Index("ix_day_disputes_person_day", "person_id", "day"),)

    dispute_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    accurate: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewCaseRow(Base):
    __tablename__ = "review_cases"
    __table_args__ = (Index("ix_review_cases_run_status", "run_id", "status"),)

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    decision_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("decision_evidence.evidence_id"), index=True
    )
    title: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(40))
    priority: Mapped[int] = mapped_column(Integer)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[list[str]] = mapped_column(JSON)
    recommendation: Mapped[str] = mapped_column(Text)
    # The simulated day the case opened -- the product's own clock, the one the response window
    # already counts in. `opened_at` above is a wall clock and cannot answer "how long has this
    # been waiting?", because nothing in this system advances time except a simulation event.
    # Set once at creation and never moved by a refresh: a concern that persists is still the same
    # concern, and re-stamping it would reset the very number a coordinator triages by.
    # `review_by_day` is deliberately NOT a column -- it is `opened_day + CASE_REVIEW_WINDOW_DAYS`,
    # so storing it as well would freeze a constant into every row and let the two disagree.
    # Nullable only for rows written before this column existed.
    opened_day: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Why the case closed, as a `CaseResolution` value. Set at the three places a case can end
    # (recovery, consent withdrawal, a coordinator's decision) and null while it is unresolved.
    # Previously this existed only inside the English prose of a system-authored review note.
    resolution: Mapped[str | None] = mapped_column(String(40), nullable=True)


class CaseReviewRow(Base):
    __tablename__ = "case_reviews"
    __table_args__ = (Index("ix_case_reviews_case_recorded", "case_id", "recorded_at"),)

    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("review_cases.case_id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    status: Mapped[str] = mapped_column(String(40))
    reviewer: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # ── Override memory (audit-H finding 3 / WAYFINDER F16) ──────────────────────────────────
    # What the agent suggested, what the human chose to do, and -- when those differ -- the reason
    # they gave. Review used to be an audit checkbox: a status and a note, with no record of
    # whether the human agreed with Care+ or overruled it, which made "is this thing's
    # judgement any good?" an unanswerable question.
    #
    # `agent_recommendation` is a frozen copy of `ReviewCaseRow.recommendation` as it read at the
    # moment of the review, not a foreign key to it: a later refresh must not retroactively change
    # what a human was looking at when they decided.
    #
    # Nothing in `learning.py` or the activity ranking path reads this table, and nothing may
    # start to -- a coordinator overruling the system is not a training signal about which
    # activity a senior likes, and treating it as one would let a human decision quietly reweight
    # a different person's suggestions. The one reader beyond audit and evaluation is the
    # review-threshold calibrator (ADR 0008,
    # `docs/adr/0008-coordinator-calibrated-review-threshold.md`). A resolved override with a
    # false-alarm reason may lead it to *propose* a per-person review threshold change;
    # `reached_too_late` reverts a loosening, or -- with nothing loosened -- leads it to propose
    # asking one step sooner. It never touches the baseline, and nothing it proposes applies
    # without a coordinator's approval.
    agent_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # "This should have reached me sooner." Null on reviews recorded before the question existed
    # and on system closures; never backfilled.
    reached_too_late: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # What kind of known context explained the review (`ContextGapCategory`), when the coordinator
    # said. Only ever set beside an override for `known_context`; null otherwise and on every
    # review recorded before the question existed. Tallied for the care team and read by no
    # decision, proposal or review setting (docs/calibration-trust-spec.md).
    context_gap_category: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ReviewThresholdProposalRow(Base):
    """One review-threshold calibrator output -- a proposed change, a considered no-change, or a
    write-up of a revert (ADR 0008). Append-only: a proposal's status is derived from the decision
    rows that reference it, never stored here and updated.

    `proposed_on_day` is the scenario day; `proposed_at` is wall clock and is used only for the
    weekly per-coordinator proposal cap and audit ordering. `write_up_for_decision_id` is unique so
    a revert yields at most one write-up, and deliberately not a foreign key: the decision row it
    describes lives in `review_threshold_decisions`, which already references this table.
    """

    __tablename__ = "review_threshold_proposals"
    __table_args__ = (
        UniqueConstraint(
            "write_up_for_decision_id", name="uq_review_threshold_proposals_write_up_for"
        ),
        Index("ix_review_threshold_proposals_run_day", "run_id", "proposed_on_day"),
        Index("ix_review_threshold_proposals_reporter_at", "reported_by", "proposed_at"),
    )

    proposal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    # `models.ReviewThresholdOutputKind`: proposal | no_change | write_up.
    output_kind: Mapped[str] = mapped_column(String(20))
    # `models.ReviewThresholdProposer`: agent | fixed_rule | coordinator | starting_setting.
    proposer: Mapped[str] = mapped_column(String(20))
    round_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    round_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_severity_pct: Mapped[int] = mapped_column(Integer)
    previous_persistence_days: Mapped[int] = mapped_column(Integer)
    proposed_severity_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposed_persistence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # `models.ReviewThresholdCause`.
    cause: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reasoning: Mapped[str] = mapped_column(Text)
    # Resolved real evidence ids, never the aliases a model saw.
    cited_evidence_ids: Mapped[list[str]] = mapped_column(JSON)
    trigger_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_cases.case_id"), nullable=True
    )
    trigger_review_ids: Mapped[list[str]] = mapped_column(JSON)
    # The reviewing coordinator's `sub`.
    reported_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # `models.OverrideReason` of the triggering review.
    coordinator_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    write_up_for_decision_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_run_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    proposed_on_day: Mapped[date] = mapped_column(Date)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewThresholdDecisionRow(Base):
    """One change to, or check on, a person's review threshold (ADR 0008). Append-only.

    The live threshold is a pure fold over these rows (`review_threshold.resolve_live_threshold`),
    never a stored "current value" column. Every change row takes effect from
    `effective_from_day = decided_on_day + 1`, except `expired`, whose `effective_from_day` is the
    day stateless expiry already applied. `proposal_id` and `ends_approval_id` are unique so a
    proposal is decided at most once and an approval ended at most once, whichever writer races.
    """

    __tablename__ = "review_threshold_decisions"
    __table_args__ = (
        UniqueConstraint("proposal_id", name="uq_review_threshold_decisions_proposal"),
        UniqueConstraint("ends_approval_id", name="uq_review_threshold_decisions_ends_approval"),
        Index("ix_review_threshold_decisions_run_effective", "run_id", "effective_from_day"),
    )

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    # `models.ReviewThresholdDecisionKind`.
    kind: Mapped[str] = mapped_column(String(30))
    proposal_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_threshold_proposals.proposal_id"), nullable=True
    )
    ends_approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_threshold_decisions.decision_id"), nullable=True
    )
    affects_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_threshold_decisions.decision_id"), nullable=True
    )
    # `models.ReviewThresholdRevertTrigger`.
    revert_trigger: Mapped[str | None] = mapped_column(String(30), nullable=True)
    previous_severity_pct: Mapped[int] = mapped_column(Integer)
    previous_persistence_days: Mapped[int] = mapped_column(Integer)
    severity_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    persistence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(120))
    # `models.ReviewThresholdRejectionReason`.
    rejection_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    cause_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Required by code for `approved`: the replay the coordinator approved against.
    replay_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    trigger_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("review_cases.case_id"), nullable=True
    )
    trigger_review_id: Mapped[str | None] = mapped_column(
        ForeignKey("case_reviews.review_id"), nullable=True
    )
    decided_on_day: Mapped[date] = mapped_column(Date)
    effective_from_day: Mapped[date] = mapped_column(Date)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProgrammeRow(Base):
    __tablename__ = "programmes"

    programme_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(240))
    venue: Mapped[str] = mapped_column(String(240))
    distance_km: Mapped[float] = mapped_column(Float)
    next_session: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accessibility_json: Mapped[list[str]] = mapped_column(JSON)
    evidence_source: Mapped[str] = mapped_column(String(120))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActivityCandidateRow(Base):
    """One catalogue listing a senior could ask Care+ about -- the user-initiated loop's
    equivalent of `ProgrammeRow`.

    Deliberately a separate table rather than a `Programme` extension: `Programme` and
    `/v1/programmes` are load-bearing for the existing proactive-outreach loop and e2e suite, and
    the new catalogue's shape (indoor/outdoor, intensity, language tags, availability,
    provenance) is wide enough that reshaping `Programme` to carry it would be a breaking change
    to a contract other surfaces already depend on. Nothing here is computed or guessed: every
    column mirrors a field on `ActivityCandidate`, and `UNKNOWN`/`None` is stored exactly when the
    fact is not known -- never filled in with something plausible.
    """

    __tablename__ = "activity_candidates"

    activity_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    integration_status: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(240))
    provider: Mapped[str] = mapped_column(String(160))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location_name: Mapped[str] = mapped_column(String(200))
    location_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    location_postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The display badge only. `activity_type`/`activity_families_json`/`format` below carry the
    # two facts this one free-text column used to conflate (what the thing is, and how it is
    # run), which is why a single "not for me" on a walk used to teach a dislike of tai chi.
    # All three are nullable: a listing that was written before the taxonomy existed, or that
    # came from a feed with no labels, is unlabelled -- which is a different fact from
    # `ActivityType.OTHER` and must not be backfilled with a guess.
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    activity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    activity_families_json: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, default=list
    )
    format: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Where this listing's facts came from and when anyone last checked them. Nullable, and left
    # null for a fixture: nobody has verified a fixture against a real centre, and stamping a
    # date here would claim exactly the assurance the catalogue does not have.
    metadata_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    indoor_outdoor: Mapped[str] = mapped_column(String(20), default="unknown")
    intensity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Nullable because "the listing does not say" and "solo" are different facts, and a group
    # session is exactly what someone asking to meet people is looking for.
    social_shape: Mapped[str | None] = mapped_column(String(20), nullable=True)
    accessibility_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    language_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability: Mapped[str] = mapped_column(String(20), default="unknown")
    price: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stored, not inferred. The reader used to derive this from `distance_m is None`, which is
    # only correct while exactly one basis exists: the moment a routing adapter measures a real
    # walk, every row it wrote would still read "a fixed figure typed into the listing". A row
    # written before this column existed is null and falls back to that same inference.
    distance_basis: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Everything a person needs in order to actually go, held on the listing rather than left to
    # be chased across three places. All nullable: "not listed" is a real answer and must reach
    # the screen as one instead of being filled in with something plausible.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Nullable to match the migration that added them. They were declared NOT NULL here while
    # `a3f8c72d1e94` created them nullable, so a schema built from this metadata (SQLite tests)
    # and one built by Alembic (Postgres) disagreed -- and the disagreement hid the very failure
    # it caused: every pre-existing Postgres row had NULL here, which the reader then rejected.
    what_to_bring_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    booking: Mapped[str] = mapped_column(String(20), default="unknown")
    booking_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    getting_there_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    good_to_know_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)


class ActivityDimensionPreferenceRow(Base):
    """A learned, ranking-only signal about a *kind* of activity, not one candidate.

    Deliberately not append-only: unlike `candidate_preferences` (a person's own explicit mute),
    this is inferred from decline reasons and is expected to move as more evidence arrives.
    `(person_id, dimension, value, source)` is unique -- the current belief about "outdoor"
    activities from one class of evidence is one row, replaced in place, not a growing log of
    every observation.

    `source` is part of the key on purpose. `preferences.apply_decline` and `apply_enjoyment`
    keep their evidence on separate tiers (`decline_reason` / `inferred`) so a decline can never
    overwrite what an enjoyed activity taught, and the person's own words (`senior_statement`)
    sit above both. The constraint used to omit `source`, which let a decline row silently
    replace an enjoyment row's source and count the moment both named the same value.

    `expires_at` makes a preference temporary: "no walks this week" is a fact until Sunday and
    nothing after. Every reader (`_activity_preferences_model`) treats an expired row as absent;
    a later observation on the same key starts it again from one rather than resurrecting the
    old count. `stated_text` keeps the person's own words when a preference came from them, so
    the Privacy screen can show what was actually said rather than a paraphrase.
    `first_observed_at` is `None` on rows written before it existed; it is never backfilled,
    because a guessed first date would be a fabricated one.

    `run_id` is the run-scoping this table gained instead of a demo reset deleting it outright
    (see `SqlAlchemyRepository.reset`, ADR 0004). Whether a row is run-scoped depends on what kind
    of fact it is, not simply on `source`:

    * A *standing* `senior_statement` row -- `prefer`/`avoid` with no `until` -- keeps
      `run_id = None` and is never run-scoped. A person's own, un-time-boxed word about themselves
      is a standing instruction exactly like `candidate_preferences` (their outreach mutes), not
      something the simulated story taught, so it survives a reset and keeps applying until an
      explicit `forget`.
    * A *time-boxed* `senior_statement` row -- `until` a day -- carries the `run_id` of the run it
      was stated in. `expires_at` is compared against that run's own simulated calendar
      (`_preference_expired`), and a reset rewinds the calendar back to the fixture's anchor day --
      *behind* whatever day the statement was timeboxed against. Without run-scoping, a promise
      that had already lapsed ("avoid until day 3", now on day 10) would be read as not-yet-expired
      the moment the calendar falls behind it again, and reappear. Run-scoping closes that: once a
      reset makes a different run active, the row is inert regardless of what the calendar says.
    * `decline_reason` / `inferred` rows always carry the `run_id` of the run that produced them,
      because that evidence -- a tap on a listing, an enjoyed activity -- only means something
      against the simulated history it came from.

    In every run-scoped case, a row whose `run_id` is not the active run's is treated as absent
    everywhere a reader asks "what does this person currently hold" (`_dimension_rows`), exactly
    like a calendar-expired row, and is restarted in place -- observations reset to one, `run_id`
    reattached -- the next time the same kind of evidence arrives, rather than resurrecting a
    belief (or a promise) from a story that no longer exists. The row is never deleted, so it
    stays available for audit; comparing an inferred belief's history *across* runs is therefore
    not supported by this in-place restart, only within one.

    `run_id is None` is *not* the test for "standing" -- every row this table held before this
    column existed also has `run_id = None`, and so does a row the Alembic backfill could not
    resolve (a person with no active run at the time). `_preference_inactive` derives "standing"
    from `source`/`expires_at` instead, so a legacy or unbackfilled row reads as run-scoped and
    simply matches no real run, rather than being misread as a standing belief it never was.
    """

    __tablename__ = "activity_dimension_preferences"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "dimension",
            "value",
            "source",
            name="uq_activity_dimension_person_value_source",
        ),
        Index("ix_activity_dimension_preferences_person", "person_id"),
    )

    preference_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    dimension: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(String(160))
    strength: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(40))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    observations: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stated_text: Mapped[str | None] = mapped_column(String(280), nullable=True)
    first_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("scenario_runs.run_id"), nullable=True, index=True
    )
    # Evidence for and against, kept apart. `strength` and `observations` stay, both derived from
    # these, because one signed scalar could not say whether zero meant "nothing known" or "two
    # things that disagree", and folding "it was fine" into "I loved it" made what was learned
    # depend on the order the two arrived in. Nullable: a row written before this revision keeps
    # resolving exactly as it did, from the backfilled split of `observations` by `strength`'s
    # sign.
    positive_evidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    negative_evidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The ordinal half: metres for DISTANCE, a rung on the intensity ladder for INTENSITY, with
    # `direction` saying which side of it the person wants. `None` on every nominal axis.
    pivot: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # The most recent origin folded into this belief (a response id, a plan id, a statement id),
    # so the same origin cannot be counted twice, and -- on a `senior_statement` row -- the id of
    # the inferred row that statement *consumed*, which is what makes a ratified belief one row
    # rather than two that contradict each other.
    origin_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Set by `forget` (a retraction) and by ratification. A superseded row is never read, never
    # rendered and never scored; it is not deleted, so the audit trail stays honest, and the next
    # observation on its key starts a fresh belief rather than resurrecting this one's count.
    superseded_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # `models.ClarificationScope`: how far the answer reached. An unclarified "bad timing" or
    # "not for me" is written item-level (`this_slot` / `this_one`) and held back until a second
    # agreeing answer about a different programme; a chip writes the scope it named. `None` is a
    # belief that was never item-level -- a "too far"/"too tiring" ceiling, an enjoyment, a
    # statement -- and resolves as it stands, except a legacy ACTIVITY_TYPE "not for me" written
    # before unclarified ones were scoped, which is read as `this_one`.
    scope: Mapped[str | None] = mapped_column(String(20), nullable=True)


class ActivityOfferResponseRow(Base):
    """One tap on a search result: "I'm interested" or "Not for me", with the optional reason.

    Append-only and many per `(person_id, activity_id)`: a person may decline a listing this week
    and choose it next month, and both are evidence. This is the row that finally lets the
    user-initiated loop learn -- before it existed a decline on a search card lived and died in
    the browser, and the dimensional learner was reachable only from outreach.

    `query_id` is an opaque correlation label copied from the search response the person was
    looking at. It is not a foreign key (searches are not stored as rows, only audited) and it is
    never used for ownership or deduplication; it exists so an evaluator can relate a response to
    the `activity_search` audit event it answered.
    """

    __tablename__ = "activity_offer_responses"
    __table_args__ = (
        Index("ix_activity_offer_responses_person_activity", "person_id", "activity_id"),
        Index("ix_activity_offer_responses_run_recorded", "run_id", "recorded_at"),
    )

    response_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activity_candidates.activity_id"))
    query_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # How far that reason reaches (`models.ClarificationScope`), when the person tapped a chip
    # saying so. Nullable and always skippable: unclarified means item-level only.
    clarification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rank_shown: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The plan entry an "interested" created, when it did. `None` for a decline, or for an
    # interest in a session outside the week being planned (recorded, not planned).
    plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The simulated day the tap happened on -- the clock every cooldown in the loop is measured
    # in (see `activity_search.DECLINE_COOLDOWN_DAYS`). `recorded_at` is wall clock, kept for
    # audit ordering only.
    recorded_on_day: Mapped[date] = mapped_column(Date)
    actor: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlanFollowThroughRow(Base):
    """What happened to one planned activity, once the person has said: went, did not go, or it
    was cancelled. One row per plan entry (`uq_plan_follow_through_plan`), append-only, mirroring
    `intervention_follow_through` for outreach -- separate tables because a planned activity is
    not an intervention and has no `intervention_id` to key on.
    """

    __tablename__ = "plan_follow_through"
    __table_args__ = (
        UniqueConstraint("plan_id", name="uq_plan_follow_through_plan"),
        Index("ix_plan_follow_through_run_recorded", "run_id", "recorded_at"),
    )

    follow_through_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("week_plan_entries.plan_id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    follow_through: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlanEnjoymentRow(Base):
    """Whether one planned activity was any good, once the person went and has said. One row per
    plan entry, append-only, mirroring `intervention_enjoyment`."""

    __tablename__ = "plan_enjoyment"
    __table_args__ = (
        UniqueConstraint("plan_id", name="uq_plan_enjoyment_plan"),
        Index("ix_plan_enjoyment_run_recorded", "run_id", "recorded_at"),
    )

    enjoyment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("week_plan_entries.plan_id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    enjoyment: Mapped[str] = mapped_column(String(40))
    liked_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    actor: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InterventionEnjoymentRow(Base):
    """Whether one piece of outreach was any good, once the person has said.

    A separate table from `intervention_follow_through`, one row per intervention just like it,
    for the same reason the two are separate Pydantic models: attending and enjoying are
    different facts, and a system that stores them as one column will keep offering something a
    person dutifully attends and quietly dislikes.
    """

    __tablename__ = "intervention_enjoyment"
    __table_args__ = (
        UniqueConstraint("intervention_id", name="uq_enjoyment_intervention"),
        Index("ix_enjoyment_run_recorded", "run_id", "recorded_at"),
    )

    enjoyment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intervention_id: Mapped[str] = mapped_column(
        ForeignKey("interventions.intervention_id"), index=True
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    enjoyment: Mapped[str] = mapped_column(String(40))
    liked_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    actor: Mapped[str] = mapped_column(String(80))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProposedMemoryRow(Base):
    """Something Care+ believes it has learned, held back until the person agrees to it.

    `status` starts `"pending"` and becomes exactly one of `MemoryDecision`'s values
    (`remember` / `just_today` / `no`) once decided -- terminal, not append-only: a proposal is
    answered once, and `SqlAlchemyRepository.decide_proposed_memory` replays the stored result on
    a repeat call rather than re-deciding it. Scoped to the run it was raised in, matching
    `intervention_follow_through` and friends, so a demo reset starts with a clean slate.
    """

    __tablename__ = "proposed_memories"
    __table_args__ = (
        Index("ix_proposed_memories_person_status", "person_id", "status"),
        Index("ix_proposed_memories_person_dimension_value", "person_id", "dimension", "value"),
    )

    proposal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    dimension: Mapped[str] = mapped_column(String(40))
    value: Mapped[str] = mapped_column(String(160))
    statement: Mapped[str] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ContextQuestionAnswerRow(Base):
    """A record that one context question was asked and answered.

    The question itself is never stored ahead of time, because it is computed fresh, on demand,
    from `PersonState`; storing it would let it drift out of sync with the state that justified
    asking it.

    `answered_on_day` is the *scenario* day (`PersonState.current_day`), not wall-clock time, for
    the same reason `BaselineConfirmationRow.decided_on_day` is: `context_explanation.py` reasons
    over a window of simulated days from this value, and a window derived from `answered_at` would
    reproduce the `_weekly_contact_count` bug exactly -- a demo advancing ten simulated days in one
    wall-clock minute would see every answer as given "today". `answered_at` is kept for audit
    ordering, which is all it can honestly promise.

    Nullable because rows written before the column existed cannot be assigned a scenario day
    without inventing one; `context_explanation.active_explanation` skips them rather than guess.
    """

    __tablename__ = "context_question_answers"
    __table_args__ = (Index("ix_context_question_answers_run", "run_id", "question_id"),)

    answer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    question_id: Mapped[str] = mapped_column(String(80))
    # One of `models.ContextAnswerValue`'s five tokens, enforced at the HTTP edge
    # (`ContextAnswerRequest.value`) and again in `answer_context_question`. The width is legacy
    # headroom, not a licence to store a sentence: while `value` was a bare `str` this column was
    # the only thing standing between free text and the database, and on PostgreSQL it stopped it
    # with a 500 rather than a 422. `note` -- the field that IS the person's own words -- is
    # `Text` below and is redacted out of the audit trail; `value` is not, because it is a token.
    value: Mapped[str] = mapped_column(String(160))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_on_day: Mapped[date | None] = mapped_column(Date, nullable=True)


class BaselineConfirmationRow(Base):
    """One senior decision on "is this your new normal" -- append-only, like `case_reviews` and
    `day_disputes`, never updated in place: both a confirm and a decline are evidence, and either
    may be followed by a later, different decision as the person's life changes again.

    `decided_on_day` is the *scenario* day (`PersonState.current_day`), not wall-clock time --
    everything this table's own cooldown and re-anchoring logic reasons about must be reproducible
    from the frozen seed, which `decided_at` (wall clock, kept only for audit ordering) cannot
    promise. The most recent row with `decision = "confirm"` for a run is the reference in effect;
    the most recent row overall governs the decline cooldown. See `baseline_confirmation.py`.
    """

    __tablename__ = "baseline_confirmations"
    __table_args__ = (Index("ix_baseline_confirmations_run_decided", "run_id", "decided_on_day"),)

    confirmation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    decision: Mapped[str] = mapped_column(String(20))
    streak_days: Mapped[int] = mapped_column(Integer)
    previous_reference_steps: Mapped[float] = mapped_column(Float)
    # Populated only on `confirm`; a `decline` changes nothing about the reference in effect.
    new_reference_steps: Mapped[float | None] = mapped_column(Float, nullable=True)
    decided_on_day: Mapped[date] = mapped_column(Date)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(80))


class ActivityGoalRow(Base):
    """A lifestyle goal the person has chosen -- never a health target, never scored.

    `(person_id, kind)` is unique, matching `activity_dimension_preferences`: the current goal of
    a given kind is one row, replaced in place when the person changes it, not a growing log of
    every edit.
    """

    __tablename__ = "activity_goals"
    __table_args__ = (
        UniqueConstraint("person_id", "kind", name="uq_activity_goal_person_kind"),
        Index("ix_activity_goals_person", "person_id"),
    )

    goal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    target_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WeekPlanEntryRow(Base):
    """One activity a person has put on their own week -- chosen, not suggested.

    Run-scoped, like every other derived row this repository keeps (ADR 0004). A demo reset
    rewinds the simulated calendar to the fixture's anchor day, so a plan an earlier run made
    falls inside the live week again: read person-scoped, a dead run's outings reappeared on the
    senior's week, were reportable ("went", "enjoyed") and taught the *new* run's dimension
    preferences about something it never planned. Every reader and writer
    (`SqlAlchemyRepository._week_plan_model`, `_owned_plan`, `_plan_activity_in_session`,
    `replan_notices`) filters on the active run; the rows themselves stay, append-only, belonging
    to the story that made them.

    `(run_id, person_id, day, activity_id)` is unique so re-submitting the same choice within one
    run is a no-op rather than a duplicate entry on the week -- and so the same choice can be made
    again in a *later* run, which the older `(person_id, day, activity_id)` key made impossible.
    """

    __tablename__ = "week_plan_entries"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "person_id",
            "day",
            "activity_id",
            name="uq_week_plan_run_person_day_activity",
        ),
        Index("ix_week_plan_entries_person_day", "person_id", "day"),
    )

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activity_candidates.activity_id"))
    # `chosen` for everything created through `plan_activity` today; `suggested` is reserved for
    # a future gap-filling offer and is never written by this repository yet.
    origin: Mapped[str] = mapped_column(String(20), default="chosen")
    # Set together, only by `replace_planned_activity`, and only after the person said yes to a
    # `ReplanOfferRow`: why this plan could no longer happen (the offer's own reason code) and
    # which plan took its place. A row with `replaced_reason` set is never asked about again --
    # `_week_plan_model` keeps it visible but never `awaiting_report`, and `plans_due` skips it --
    # because "did you get a chance to go?" about a session that was cancelled under the person
    # is the question audit F finding 8 caught this product asking.
    replaced_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    replaced_by_plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReplanOfferRow(Base):
    """One offer to replace a planned activity the world changed under, and what the person said.

    Written by `advance()` in the same transaction as the change that invalidated the plan, so an
    offer cannot exist without the fact behind it and the fact cannot exist without the offer.
    Before this table, replanning was a read view: the notice was recomputed on every request, a
    "no thanks" lived only in browser state, and nothing recorded that an offer had ever been made
    (audit F finding 8 / review R7).

    `reason` is a closed vocabulary -- `full`, `cancelled`, `weather` -- and it is the *reason
    code*, never the sentence shown to the person; the wording belongs to `replanning.py`.
    `weather` exists precisely so the simulator no longer has to fabricate a catalogue fact
    ("fully booked") to represent a context one (audit J finding F-J-A).

    `resolution` is null while the offer is open and one of `accepted`, `declined`, `expired`,
    `no_alternative` once it is closed. Deliberately NOT an append-only evidence table: an offer
    is resolved in place, which is why no `reject_silverloop_evidence_mutation` trigger is
    installed on it in the Supabase mirror. Run-scoped like every other derived row (ADR 0004): a
    dead run's offer is not the live run's business.
    """

    __tablename__ = "replan_offers"
    __table_args__ = (
        Index("ix_replan_offers_run_person", "run_id", "person_id"),
        Index("ix_replan_offers_plan", "plan_id"),
    )

    offer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("week_plan_entries.plan_id"))
    reason: Mapped[str] = mapped_column(String(20))
    # The alternative that was actually offered, or null when nothing similar survived the same
    # filter the search uses -- "nothing was found" is an honest answer, not a missing value.
    alternative_activity_id: Mapped[str | None] = mapped_column(
        ForeignKey("activity_candidates.activity_id"), nullable=True
    )
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)


class AuthUserPersonLinkRow(Base):
    """Maps a Supabase subject (auth.users.id) to one internal person_id."""

    __tablename__ = "auth_user_person_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sub: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.person_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_run_recorded", "run_id", "recorded_at"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("scenario_runs.run_id"), index=True)
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("people.person_id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(120))
    decision: Mapped[str | None] = mapped_column(String(48), nullable=True)
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ── Family groups (family members caring for one senior) ──────────────────────
#
# A family member signs up, then creates a group for a senior (with the PIN the senior shows on
# their own screen, which is the senior's agreement to be linked) or joins an existing group with
# that group's join PIN. A joiner waits as `pending` until an active member approves them.
# `silverloop.family_groups` owns every read and write of these tables.


class AccountRow(Base):
    """The role a self-registered Supabase user chose at sign-up (`senior` or `family`).

    Accounts provisioned with a role in Supabase `app_metadata` (the demo senior, coordinator and
    demo operator) need no row. The demo family accounts have one, written by the setup script.
    """

    __tablename__ = "accounts"

    sub: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CareGroupRow(Base):
    """One senior's family group. At most one per senior (`person_id` is unique). `person_id` is
    NULL until the senior is linked with their senior-link PIN; until then the group sees nothing
    about the senior."""

    __tablename__ = "care_groups"

    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("people.person_id"), unique=True, nullable=True
    )
    # The name the creator typed. Once linked, responses show the senior's own account name.
    senior_name: Mapped[str] = mapped_column(String(80))
    # How the senior agreed to the link (`senior_link_pin`, or `demo_seed`); NULL until linked.
    linked_via: Mapped[str | None] = mapped_column(String(32), nullable=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GroupMemberRow(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "sub", name="uq_group_members_group_sub"),)

    member_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("care_groups.group_id"), index=True)
    sub: Mapped[str] = mapped_column(String(128), index=True)
    relationship: Mapped[str] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(16))  # owner | member
    status: Mapped[str] = mapped_column(String(16))  # active | pending
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When this member last opened this group; the latest active one is their current group.
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FamilyPinRow(Base):
    """A short-lived 6-digit PIN, stored only as a hash.

    `senior_link`: shown on the senior's screen, names `person_id`, single use.
    `group_join`: shown to a group's members, names `group_id`, reusable until it expires.
    """

    __tablename__ = "family_pins"
    __table_args__ = (UniqueConstraint("purpose", "pin_hash", name="uq_family_pins_purpose_hash"),)

    pin_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(16))
    pin_hash: Mapped[str] = mapped_column(String(64))
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("people.person_id"), nullable=True, index=True
    )
    group_id: Mapped[str | None] = mapped_column(
        ForeignKey("care_groups.group_id"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PinAttemptRow(Base):
    """Every PIN entry, so repeated wrong guesses from one account can be locked out."""

    __tablename__ = "pin_attempts"
    __table_args__ = (Index("ix_pin_attempts_sub_at", "sub", "attempted_at"),)

    attempt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sub: Mapped[str] = mapped_column(String(128))
    succeeded: Mapped[bool] = mapped_column(Boolean)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ── Family calendar ──────────────────────────────────────────────────────────
# Owned by `silverloop.family_calendar`. A repeating appointment is ONE row; its days are worked
# out when the calendar is read. Answers and helpers point at one day of it (appointment + date).


class AppointmentRow(Base):
    __tablename__ = "appointments"

    appointment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("care_groups.group_id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    location: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    repeat: Mapped[str] = mapped_column(String(8))  # none | daily | weekly | monthly
    repeat_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AvailabilityEntryRow(Base):
    """A member's free (or busy) time. With `appointment_id`, their answer for that one day of
    that appointment; without, a window on `on_date`."""

    __tablename__ = "availability_entries"

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("care_groups.group_id"), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey("group_members.member_id"), index=True)
    on_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(16))  # available | unavailable
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.appointment_id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HelperAssignmentRow(Base):
    """A member going along to one day of an appointment ("I'll help")."""

    __tablename__ = "helper_assignments"
    __table_args__ = (
        UniqueConstraint(
            "appointment_id", "on_date", "member_id", name="uq_helper_assignments_day_member"
        ),
    )

    assignment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("care_groups.group_id"), index=True)
    appointment_id: Mapped[str] = mapped_column(
        ForeignKey("appointments.appointment_id"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date)
    member_id: Mapped[str] = mapped_column(ForeignKey("group_members.member_id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppointmentNoteRow(Base):
    """A family member's note on one day of an appointment. Unlike the feed it is not append-only:
    its author can delete it. Group-only text: never logged, audited, sent to the agent or shown to
    the senior, and never copied into `family_activity` (the feed records only that a note was
    added). Deleted with its appointment, when an edit to the appointment leaves its day no longer
    one of its occurrences (the text could not be read or removed again), and by the demo reset
    before the feed and appointments."""

    __tablename__ = "appointment_notes"
    __table_args__ = (
        Index("ix_appointment_notes_day_created", "appointment_id", "on_date", "created_at"),
    )

    note_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("care_groups.group_id"), index=True)
    appointment_id: Mapped[str] = mapped_column(
        ForeignKey("appointments.appointment_id"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date)
    member_id: Mapped[str] = mapped_column(ForeignKey("group_members.member_id"), index=True)
    text: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Owned by `silverloop.family_tasks`. Like an appointment, a repeating task is ONE row; its days are
# worked out when read. A tick is one day of it ticked done; un-ticking deletes the row.


class TaskRow(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("care_groups.group_id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))  # task | medicine
    start_date: Mapped[date] = mapped_column(Date)
    time: Mapped[str] = mapped_column(String(5))
    repeat: Mapped[str] = mapped_column(String(8))  # none | daily | weekly
    repeat_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskTickRow(Base):
    __tablename__ = "task_ticks"
    __table_args__ = (UniqueConstraint("task_id", "day", name="uq_task_ticks_task_day"),)

    tick_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("care_groups.group_id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    done_by: Mapped[str] = mapped_column(String(128))
    done_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FamilyActivityRow(Base):
    """One thing a family member did in the group, for the family's activity feed. Append-only:
    nothing updates or deletes a row except the demo reset. Written only by
    `silverloop.family_activity.record`, in the transaction of the change it describes.

    `appointment_id` deliberately has no foreign key and `appointment_title` is a snapshot, so an
    entry outlives the appointment it mentions. A check-in's `note` is group-only text: it is never
    logged, audited, sent to the agent, or shown to the senior.

    Members are referenced by foreign key, so a member who has an entry here must never be
    hard-deleted. A future "leave" or "remove member" feature has to change `status` instead, and
    needs a PostgreSQL test (SQLite does not enforce foreign keys). Only a pending request that was
    declined is deleted, and it has no entries. The demo reset clears the feed before the members.
    """

    __tablename__ = "family_activity"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'check_in') = (check_in_kind IS NOT NULL) "
            "AND (note IS NULL OR kind = 'check_in')",
            name="ck_family_activity_check_in_fields",
        ),
        Index("ix_family_activity_group_created", "group_id", "created_at", "activity_id"),
    )

    activity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("care_groups.group_id"))
    kind: Mapped[str] = mapped_column(String(32))
    actor_member_id: Mapped[str] = mapped_column(ForeignKey("group_members.member_id"), index=True)
    # Only `member_approved`: the member who was let in.
    subject_member_id: Mapped[str | None] = mapped_column(
        ForeignKey("group_members.member_id"), nullable=True
    )
    appointment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    appointment_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    appointment_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    on_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    check_in_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), default="live")  # live | demo_seed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
