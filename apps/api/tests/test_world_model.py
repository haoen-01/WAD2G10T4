"""The personal world model: typed facts with provenance, assembled from stores that exist.

Two properties matter more than any wording: an inference is never labelled as something the
person said, and a gap is stated rather than filled. The pure builder is tested directly; the
repository assembly and the route are tested through the contract, including that the
coordinator-facing metrics carry only counts and never the facts.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from silverloop.db_models import InterventionOutcomeRow, InterventionRow
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.local_time import local_date
from silverloop.models import (
    BaselineSummary,
    DeclineReason,
    DimensionPreference,
    FactCategory,
    FactConfidence,
    FactSourceType,
    PreferenceDimension,
)
from silverloop.sql_repository import SqlAlchemyRepository
from silverloop.world_model import (
    ActivityHistoryFact,
    ConfirmedReferenceFact,
    OutreachResponseFact,
    WorldModelInputs,
    build_world_model,
)

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
TODAY = date(2026, 8, 18)


def _inputs(**overrides: object) -> WorldModelInputs:
    base = dict(
        person_id="p1",
        display_name="Mdm Test",
        as_of_day=TODAY,
        as_of=NOW,
        preferred_language="English",
        age=74,
        background="Socially motivated.",
        is_synthetic_profile=True,
        consent_active=True,
        consent_evidence_id="consent_1",
        consent_recorded_at=NOW,
        consent_source="user_demo_input",
        baseline=BaselineSummary(
            window_days=28,
            median_steps=5700,
            mad_steps=280,
            data_quality=1.0,
            reference_steps=5750,
            reference_window_days=28,
            effective_median_steps=5700,
        ),
        baseline_observed_at=NOW,
        confirmed_reference=None,
    )
    base.update(overrides)
    return WorldModelInputs(**base)  # type: ignore[arg-type]


def _offer(client: TestClient) -> dict:
    """Advance the simulation until one advance actually produces a piece of outreach."""
    for _ in range(12):
        payload = client.post("/v1/simulation/advance", json={"event": "activity_declines"}).json()
        intervention = payload.get("created_intervention")
        if intervention is not None:
            return intervention
    raise AssertionError("no intervention was created in twelve declining days")


def _preference(source: str, strength: float, **overrides: object) -> DimensionPreference:
    base = dict(
        dimension=PreferenceDimension.DISTANCE,
        value="far",
        strength=strength,
        source=source,
        confirmed=source == "senior_statement",
        observations=1,
        updated_at=NOW,
    )
    base.update(overrides)
    return DimensionPreference(**base)  # type: ignore[arg-type]


# ── Provenance ────────────────────────────────────────────────────────────────────────────────


def test_fixture_biography_is_labelled_fixture_never_explicit() -> None:
    model = build_world_model(_inputs())
    identity = [f for f in model.facts if f.category is FactCategory.IDENTITY]
    assert identity and all(f.source_type is FactSourceType.FIXTURE for f in identity)
    assert model.quality.fixture == len(identity)


def test_an_inferred_preference_is_never_presented_as_a_statement() -> None:
    model = build_world_model(
        _inputs(
            preferences=[
                _preference("decline_reason", -0.5, observations=2),
                _preference("inferred", 0.4, value="near"),
                _preference("senior_statement", -1.0, value="far", stated_text="too far for me"),
            ]
        )
    )
    facts = {f.key: f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE}
    # A decline-tier belief and a stated one about the same value are two facts, keyed apart.
    assert {
        "preference:distance:far:decline_reason",
        "preference:distance:far:senior_statement",
    } <= set(facts)
    stated = [f for f in facts.values() if f.source_type is FactSourceType.EXPLICIT]
    inferred = [f for f in facts.values() if f.source_type is FactSourceType.INFERRED]
    assert len(stated) == 1 and stated[0].confirmed and '"too far for me"' in stated[0].statement
    assert stated[0].confidence is FactConfidence.HIGH
    assert all("picked up from" in f.statement for f in inferred)
    assert all(not f.confirmed for f in inferred)
    # Two observations from taps is still LOW; nothing inferred reaches HIGH without confirmation.
    assert all(f.confidence is FactConfidence.LOW for f in inferred)


def test_a_confirmed_reference_is_explicit_and_cites_its_evidence() -> None:
    model = build_world_model(
        _inputs(
            confirmed_reference=ConfirmedReferenceFact(
                steps=3100, confirmation_id="conf_1", decided_on_day=TODAY, decided_at=NOW
            )
        )
    )
    fact = next(f for f in model.facts if f.key == "reference_steps")
    assert fact.source_type is FactSourceType.EXPLICIT
    assert fact.confirmed and fact.evidence_ids == ["conf_1"]
    # G-3: no step count in the sentence a person reads -- the number still lives in the
    # fact's own structured `value` field, which the evaluator surface reads separately.
    assert "3,100" not in fact.statement
    assert fact.value == "3100"
    assert "you" in fact.statement.lower()


# ── A-F8: response hour is local and dropped under a simulated run ──────────────────────────


def test_typical_response_hour_is_dropped_under_a_simulated_run() -> None:
    model = build_world_model(
        _inputs(typical_response_hour=15, typical_response_hour_sample=5, is_simulated_run=True)
    )
    assert not any(f.key == "typical_response_hour" for f in model.facts)


def test_typical_response_hour_is_second_person_with_no_tally_when_not_simulated() -> None:
    model = build_world_model(
        _inputs(typical_response_hour=15, typical_response_hour_sample=5, is_simulated_run=False)
    )
    fact = next(f for f in model.facts if f.key == "typical_response_hour")
    assert "you" in fact.statement.lower()
    assert "5" not in fact.statement
    assert "time(s)" not in fact.statement
    assert "3pm" in fact.statement.lower()


def test_repository_typical_response_hour_reads_the_local_clock_not_utc(
    repository: SqlAlchemyRepository,
) -> None:
    """`InterventionOutcomeRow.recorded_at` is stored in UTC; a reply at 23:15 UTC is 07:15 the
    next morning in Singapore, not 11pm. Before this fix `_typical_response_hour` returned the
    raw UTC hour (23); after it, it returns the local one (7)."""
    recorded_at = datetime(2026, 1, 10, 23, 15, tzinfo=UTC)
    with repository.sessions() as session:
        run = repository._active_run(session, DEMO_PERSON_ID)
        run_id = run.run_id
    with repository.sessions.begin() as session:
        for index in range(3):
            session.add(
                InterventionOutcomeRow(
                    outcome_id=f"outcome_hour_test_{index}",
                    intervention_id=f"intervention_hour_test_{index}",
                    run_id=run_id,
                    outcome="accepted",
                    reason=None,
                    actor="senior",
                    reviewer=None,
                    recorded_at=recorded_at,
                )
            )
    with repository.sessions() as session:
        typical_hour, samples = repository._typical_response_hour(session, run_id)
    assert typical_hour == 7
    assert len(samples) == 3


# ── A-F9: provenance ──────────────────────────────────────────────────────────────────────────


def test_a_seeded_consent_is_fixture_not_explicit() -> None:
    """A-F9: `ConsentEvidenceRow.source == "synthetic_fixture"` is nobody's own choice -- it is
    activated by `POST /v1/demo/reset`, not a tap -- and must read the same way the fixture
    biography does, never as `explicit`/`confirmed`."""
    model = build_world_model(_inputs(consent_source="synthetic_fixture"))
    fact = next(f for f in model.facts if f.key == "suggestions")
    assert fact.source_type is FactSourceType.FIXTURE
    assert fact.confidence is FactConfidence.MEDIUM
    assert fact.confirmed is False


def test_a_real_consent_choice_stays_explicit_and_confirmed() -> None:
    model = build_world_model(_inputs(consent_source="user_demo_input"))
    fact = next(f for f in model.facts if f.key == "suggestions")
    assert fact.source_type is FactSourceType.EXPLICIT
    assert fact.confidence is FactConfidence.HIGH
    assert fact.confirmed is True


def test_a_stated_either_is_never_narrated_as_a_lean() -> None:
    """A-F9: `intensity=either` (or any `either`) is the absence of a lean, not a lean towards
    one side, and the phrasing that says "leans towards/away" must never be used for it."""
    model = build_world_model(
        _inputs(
            preferences=[
                _preference(
                    "senior_statement",
                    1.0,
                    dimension=PreferenceDimension.INTENSITY,
                    value="either",
                    stated_text="either is fine",
                )
            ]
        )
    )
    fact = next(f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE)
    assert "lean" not in fact.statement.lower()
    assert "either" in fact.statement.lower()
    assert '"either is fine"' in fact.statement


# ── A-F10: staleness on the person's calendar ────────────────────────────────────────────────


def test_staleness_is_measured_on_the_persons_calendar_not_the_wall_clock() -> None:
    """A-F10: the same wall-clock write (`updated_at`) is stale or not purely depending on how
    far the run's own simulated calendar (`as_of_day`) has moved on from it -- the same clock
    `_preference_expired` already uses for calendar expiry, never the wall-clock delta."""
    # 95 simulated days have passed since `updated_at`'s calendar day: stale, even though the
    # wall-clock write was "recent" in the fixture's own terms.
    model = build_world_model(
        _inputs(
            as_of_day=TODAY + timedelta(days=120),
            preferences=[_preference("inferred", 0.4, updated_at=NOW)],
        )
    )
    assert next(f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE).stale

    # Only 5 simulated days have passed since the same `updated_at`: not stale.
    model = build_world_model(
        _inputs(
            as_of_day=TODAY + timedelta(days=30),
            preferences=[_preference("inferred", 0.4, updated_at=NOW)],
        )
    )
    assert not next(f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE).stale


# ── One outing is one fact about one programme ────────────────────────────────────────────────

CHAIR_SERIES = "kampung admiralty aac|chair mobility & balance"


def test_attendance_is_one_fact_per_programme_counting_the_sessions_attended() -> None:
    """The series is the unit of the statement, and the sessions actually attended are its
    evidence. `enjoyed` used to be added on top of `went`, counting one outing the person
    reported on twice."""
    model = build_world_model(
        _inputs(
            activity_history=[
                ActivityHistoryFact(
                    series_key=CHAIR_SERIES,
                    title="Chair Mobility & Balance",
                    went=2,
                    enjoyed=1,
                )
            ]
        )
    )

    facts = [fact for fact in model.facts if fact.source == "plan_follow_through"]
    assert len(facts) == 1
    assert facts[0].key == f"activity:{CHAIR_SERIES}"
    assert facts[0].statement == 'You went to "Chair Mobility & Balance" before and enjoyed it.'
    assert facts[0].evidence_count == 2
    assert facts[0].source_type is FactSourceType.EXPLICIT


def test_one_attendance_states_nothing_about_the_sessions_not_attended(
    repository: SqlAlchemyRepository,
) -> None:
    """The honesty half of the series roll-up.

    Engagement rolls up to the programme so a cooldown reaches every session of it -- right for
    ranking, and read straight into the world model it stated three facts for one outing: "You
    went to Chair Mobility & Balance", `EXPLICIT`, `HIGH`, confirmed, once for the Wednesday the
    person attended and once each for a Friday and a Sunday they did not.
    """
    week = repository.plan_activity("activity-chair-mobility-1", date(2026, 8, 19), "senior")
    plan_id = next(
        entry.plan_id
        for entry in week.entries
        if entry.activity.activity_id == "activity-chair-mobility-1"
    )
    repository.advance("recovery", event_id="recovery-1")
    repository.advance("recovery", event_id="recovery-2")
    repository.record_planned_follow_through(plan_id, "went", None, "senior")

    facts = [
        fact for fact in repository.world_model().facts if fact.source == "plan_follow_through"
    ]

    assert [fact.key for fact in facts] == [f"activity:{CHAIR_SERIES}"]
    assert facts[0].evidence_count == 1
    assert facts[0].statement == 'You went to "Chair Mobility & Balance" before.'


def test_a_planned_session_nobody_reported_on_states_nothing_at_all(
    repository: SqlAlchemyRepository,
) -> None:
    """A plan is not an outing: until the person says they went, there is no attendance to state
    -- and a listing they answered "interested" about is not one either."""
    repository.plan_activity("activity-chair-mobility-1", date(2026, 8, 19), "senior")

    facts = [
        fact for fact in repository.world_model().facts if fact.source == "plan_follow_through"
    ]

    assert facts == []


# ── Silence is not a refusal, and an open offer is not an answer ──────────────────────────────


def _outreach(**overrides: object) -> OutreachResponseFact:
    base = dict(
        candidate_key="gentle_nudge:walk",
        label="Five-minute movement option",
        offered=1,
        accepted=0,
        completed=0,
    )
    base.update(overrides)
    return OutreachResponseFact(**base)  # type: ignore[arg-type]


def _outreach_statements(*responses: OutreachResponseFact) -> list[str]:
    model = build_world_model(_inputs(outreach_responses=list(responses)))
    return [fact.statement for fact in model.facts if fact.source == "intervention_outcomes"]


def test_an_offer_still_open_states_nothing_at_all() -> None:
    """The offer may be on the person's home page with its buttons unpressed this very moment.

    Before this, the world model's branch was completed / accepted / *else*, so the senior's own
    memory page read 'You were offered "Chair Mobility & Balance" and passed on it.' while the
    same screen asked them whether they would like to hear more about it.
    """
    assert _outreach_statements(_outreach(offered=1)) == []


def test_silence_is_narrated_as_silence_and_never_as_a_refusal() -> None:
    """The product's own rule, everywhere else: "Closed as silence, not a refusal"
    (`care-team-view.tsx`), "a reply that never comes is recorded as silence, not a refusal"
    (`view-models.ts`), and `sql_repository._resolve_unanswered`'s own learning boundary. The
    senior was the one person told otherwise."""
    statements = _outreach_statements(_outreach(offered=1, no_response=1))

    assert statements == ['You did not reply to "Five-minute movement option".']
    assert not any("passed on" in statement for statement in statements)
    assert not any("said no" in statement for statement in statements)


def test_silence_fact_prefix_is_pinned_for_the_senior_privacy_filter() -> None:
    """The senior Privacy page hides silence facts by this exact sentence prefix and category.

    `isSeniorVisibleFact` in `apps/web/lib/view-models.ts` matches `learned_response` facts whose
    statement starts with "You did not reply" -- `PersonFact` has no structured silence marker.
    Rewording the silence sentence here without updating that filter would start showing seniors a
    record of what they did not answer, so this pins the pairing: silence (and only silence) starts
    with the prefix.
    """
    prefix = "You did not reply"
    model = build_world_model(_inputs(outreach_responses=[_outreach(offered=1, no_response=1)]))
    silence = [fact for fact in model.facts if fact.source == "intervention_outcomes"]
    assert len(silence) == 1
    assert silence[0].category == "learned_response"
    assert silence[0].statement.startswith(prefix)

    answered = _outreach_statements(
        _outreach(offered=1, declined=1),
        _outreach(candidate_key="programme:x", label="X", offered=1, deferred=1),
        _outreach(candidate_key="programme:y", label="Y", offered=1, accepted=1),
        _outreach(candidate_key="programme:z", label="Z", offered=1, accepted=1, completed=1),
    )
    assert len(answered) == 4
    assert not any(statement.startswith(prefix) for statement in answered)


def test_an_explicit_decline_is_narrated_as_the_persons_own_no() -> None:
    assert _outreach_statements(_outreach(offered=1, declined=1)) == [
        'You said no to "Five-minute movement option".'
    ]


def test_a_decline_reason_is_repeated_in_plain_words_never_as_its_enum() -> None:
    """`too_far` is a token in a column, not a thing anyone says out loud."""
    for reason, clause in (
        (DeclineReason.TOO_FAR, "it was too far"),
        (DeclineReason.TOO_TIRING, "it sounded too tiring"),
        (DeclineReason.BAD_TIMING, "the timing did not suit you"),
        (DeclineReason.PREFER_SOMETHING_ELSE, "you would prefer something else"),
        (DeclineReason.NOT_FOR_ME, "it was not for you"),
        (DeclineReason.BAD_DAY, "it was just a bad day"),
        (DeclineReason.ALREADY_ACTIVE, "you were already getting about"),
    ):
        statements = _outreach_statements(_outreach(offered=1, declined=1, decline_reason=reason))
        assert statements == [f'You said no to "Five-minute movement option", because {clause}.']
        assert reason.value not in statements[0]


def test_maybe_later_is_neither_a_no_nor_a_silence() -> None:
    """`OutcomeKind`'s own docstring: "Maybe later" is an active reply from someone who read the
    message, and filing it as `NO_RESPONSE` both overstated how many people ignore Care+ and
    scored an explicit deferral as harshly as a refusal. Reading it back to them as either one is
    the same mistake on the surface the person reads."""
    assert _outreach_statements(_outreach(offered=1, deferred=1)) == [
        'You were offered "Five-minute movement option" and said maybe later.'
    ]


def test_an_answer_outranks_the_offers_that_were_never_answered() -> None:
    """Three offers, one answered. The answer is the fact; the other two are not evidence of a
    decision the person did not make, and do not dilute or contradict it."""
    assert _outreach_statements(_outreach(offered=3, declined=1, no_response=0)) == [
        'You said no to "Five-minute movement option".'
    ]
    assert _outreach_statements(_outreach(offered=3, accepted=1)) == [
        'You were offered "Five-minute movement option" and asked to hear more.'
    ]
    assert _outreach_statements(_outreach(offered=3, accepted=1, completed=1)) == [
        'You were offered "Five-minute movement option" and followed it through.'
    ]


def test_an_open_offer_states_nothing_even_when_another_kind_was_declined() -> None:
    statements = _outreach_statements(
        _outreach(candidate_key="gentle_nudge:walk", offered=1),
        _outreach(
            candidate_key="programme:aac-chair-mobility",
            label="Chair Mobility & Balance",
            offered=1,
            declined=1,
        ),
    )
    assert statements == ['You said no to "Chair Mobility & Balance".']


def test_an_open_offer_is_never_answered_by_the_repository_either(
    client: TestClient,
) -> None:
    """The same three cases, end to end through the route the senior's privacy page reads."""

    def _statements() -> list[str]:
        model = client.get(f"/v1/people/{DEMO_PERSON_ID}/world-model").json()
        return [f["statement"] for f in model["facts"] if f["source"] == "intervention_outcomes"]

    intervention = _offer(client)
    assert _statements() == []  # still open, unanswered, on the person's own home page

    declined = client.post(
        f"/v1/interventions/{intervention['intervention_id']}/outcome",
        json={"outcome": "declined", "reason": "too_far"},
    )
    assert declined.status_code == 200, declined.text
    assert _statements() == [f'You said no to "{intervention["title"]}", because it was too far.']

    second = _offer(client)
    silent = client.post(
        f"/v1/interventions/{second['intervention_id']}/outcome",
        json={"outcome": "no_response"},
    )
    assert silent.status_code == 200, silent.text
    assert f'You did not reply to "{second["title"]}".' in _statements()


def test_a_reset_does_not_carry_the_previous_runs_outreach_into_a_fresh_demo(
    client: TestClient,
    repository: SqlAlchemyRepository,
) -> None:
    """ADR 0004, the same rule `_attended_series` and the plan reads already follow: a reset
    starts the story over, so the last operator's offers are not this run's memory. Nothing is
    deleted -- the rows stay, and the person-level learner still reads every one of them."""
    intervention = _offer(client)
    assert (
        client.post(
            f"/v1/interventions/{intervention['intervention_id']}/outcome",
            json={"outcome": "declined"},
        ).status_code
        == 200
    )

    def _statements() -> list[str]:
        model = client.get(f"/v1/people/{DEMO_PERSON_ID}/world-model").json()
        return [f["statement"] for f in model["facts"] if f["source"] == "intervention_outcomes"]

    assert _statements() == [f'You said no to "{intervention["title"]}".']

    assert client.post("/v1/demo/reset").status_code == 200

    assert _statements() == []
    # Not deleted, only out of this run's story -- the rows are exactly where they were, and the
    # person-level posterior that reads them (`_preference_learners`) is untouched by the reset.
    with repository.sessions() as session:
        row = session.get(InterventionRow, intervention["intervention_id"])
        assert row is not None
        outcome = session.scalars(
            select(InterventionOutcomeRow).where(
                InterventionOutcomeRow.intervention_id == intervention["intervention_id"]
            )
        ).all()
    assert [entry.outcome for entry in outcome] == ["declined"]


# ── G-3: second person, no scoreboard vocabulary ─────────────────────────────────────────────

_SENIOR_VOCABULARY_GUARD = re.compile(
    r"\b(?:stable|watch|review|\d+%|\d+ steps|time\(s\)|of \d+|anchor|they|their"
    # "passed on it" was the wording that told someone they had refused an offer they had never
    # answered, and an offer still open on their own home page. There is no case left in which
    # Care+ may narrate a non-answer as the person's decision, so the phrase is banned
    # outright rather than left for the next reader to re-derive.
    r"|passed on)\b",
    re.IGNORECASE,
)

# A value out of a closed list is a token in a column, never a word on the senior's page.
# Statements here are prose, so an underscore between two lowercase words is a leaked enum --
# `too_far`, `prefer_something_else`, `no_response` -- and nothing else.
_RAW_ENUM_GUARD = re.compile(r"[a-z]+_[a-z]+")


def test_no_fact_carries_a_percentage_or_status_word() -> None:
    model = build_world_model(_inputs(preferences=[_preference("decline_reason", -0.3)]))
    for fact in model.facts:
        assert not _SENIOR_VOCABULARY_GUARD.search(fact.statement), fact.statement
        assert not _RAW_ENUM_GUARD.search(fact.statement), fact.statement


def test_every_decline_reason_in_the_enum_has_a_plain_sentence_of_its_own() -> None:
    """Whole-enum coverage, so adding a reason without wording it fails here rather than
    printing its token at a 74-year-old. A reason retired from the enum with rows still on disk
    is a different case -- `sql_repository._decline_reason_or_none` reads it as "no reason
    given" -- and is covered there."""
    for reason in DeclineReason:
        model = build_world_model(
            _inputs(outreach_responses=[_outreach(offered=1, declined=1, decline_reason=reason)])
        )
        statement = next(
            fact.statement for fact in model.facts if fact.source == "intervention_outcomes"
        )
        assert statement != 'You said no to "Five-minute movement option".', reason
        assert not _RAW_ENUM_GUARD.search(statement), statement
        assert not _SENIOR_VOCABULARY_GUARD.search(statement), statement


def test_no_statement_carries_a_step_count_tally_anchor_rationale_or_third_person() -> None:
    """G-3: every statement on the senior surface is second person and carries none of the
    scoreboard vocabulary the product's own comments forbid -- counts live only in
    `WorldModelQuality` and each fact's own structured `evidence_count`/`value` fields."""
    from silverloop.models import ActivityGoal, GoalKind
    from silverloop.world_model import OutreachResponseFact

    model = build_world_model(
        _inputs(
            preferences=[
                _preference("decline_reason", -0.3, value="far"),
                _preference(
                    "senior_statement",
                    1.0,
                    dimension=PreferenceDimension.SOCIAL,
                    value="either",
                    stated_text="either is fine with me",
                ),
            ],
            goals=[
                ActivityGoal(
                    goal_id="goal_1",
                    kind=GoalKind.MEET_PEOPLE,
                    text="Spend more time with other people, 2 times a week",
                    target_per_week=2,
                    active=True,
                    created_at=NOW,
                )
            ],
            outreach_responses=[
                OutreachResponseFact(
                    candidate_key="gentle_nudge:walk",
                    label="Five-minute movement option",
                    offered=4,
                    accepted=2,
                    completed=2,
                ),
                # Each remaining narrated branch, so this guard covers every sentence the
                # outreach fact can produce and not only the accepted one.
                OutreachResponseFact(
                    candidate_key="programme:aac-chair-mobility",
                    label="Chair Mobility & Balance",
                    offered=2,
                    accepted=0,
                    completed=0,
                    declined=1,
                    decline_reason=DeclineReason.BAD_TIMING,
                ),
                OutreachResponseFact(
                    candidate_key="programme:aac-sheltered-walk",
                    label="Sheltered Morning Walk",
                    offered=1,
                    accepted=0,
                    completed=0,
                    no_response=1,
                ),
                OutreachResponseFact(
                    candidate_key="programme:aac-gardening",
                    label="Community Gardening",
                    offered=1,
                    accepted=0,
                    completed=0,
                    deferred=1,
                ),
            ],
            activity_history=[
                ActivityHistoryFact(
                    series_key="park providers|tai chi in the park",
                    title="Tai chi in the park",
                    went=3,
                    enjoyed=2,
                )
            ],
            disputed_days=1,
            typical_response_hour=15,
            typical_response_hour_sample=5,
            is_simulated_run=False,
        )
    )
    assert len(model.facts) > 5  # every fact category above is actually exercised
    for fact in model.facts:
        assert not _SENIOR_VOCABULARY_GUARD.search(fact.statement), fact.statement
        assert not _RAW_ENUM_GUARD.search(fact.statement), fact.statement
        assert "you" in fact.statement.lower(), fact.statement


# ── Gaps and quality ──────────────────────────────────────────────────────────────────────────


def test_gaps_are_stated_and_change_as_preferences_are_confirmed() -> None:
    empty = build_world_model(_inputs())
    assert empty.gaps[0].startswith("No activity preference is known yet")
    inferred_only = build_world_model(_inputs(preferences=[_preference("inferred", 0.3)]))
    assert "confirmed" in inferred_only.gaps[0]
    confirmed = build_world_model(_inputs(preferences=[_preference("senior_statement", 1.0)]))
    assert not confirmed.gaps[0].startswith("No activity preference")
    # The honest structural gaps are always stated.
    assert any("time of day" in gap for gap in confirmed.gaps)
    assert any("weather" in gap for gap in confirmed.gaps)


def test_quality_counts_are_counts_of_the_facts_shown() -> None:
    model = build_world_model(
        _inputs(
            preferences=[
                _preference("decline_reason", -0.3),
                _preference(
                    "senior_statement", 1.0, value="near", expires_at=NOW + timedelta(days=2)
                ),
            ],
            expired_preferences=1,
        )
    )
    quality = model.quality
    assert quality.facts == len(model.facts)
    assert quality.explicit + quality.inferred + quality.fixture + quality.external == quality.facts
    assert quality.temporary == 1
    assert quality.expired_excluded == 1
    assert quality.confirmed == sum(1 for f in model.facts if f.confirmed)


# ── Through the contract ──────────────────────────────────────────────────────────────────────


def test_world_model_route_is_the_seniors_and_metrics_carry_only_counts(
    client: TestClient,
) -> None:
    client.post("/v1/simulation/advance", json={"event": "activity_declines"})
    stated = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/social/social",
        json={"stance": "prefer", "stated_text": "I like company"},
    )
    assert stated.status_code == 200, stated.text

    model = client.get(f"/v1/people/{DEMO_PERSON_ID}/world-model").json()
    keys = {fact["key"] for fact in model["facts"]}
    assert "preference:social:social:senior_statement" in keys
    assert "typical_day_steps" in keys
    assert "suggestions" in keys
    social = next(
        f for f in model["facts"] if f["key"] == "preference:social:social:senior_statement"
    )
    assert social["source_type"] == "explicit"
    assert social["confirmed"] is True
    assert '"I like company"' in social["statement"]
    assert (
        model["as_of_day"] == client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["current_day"]
    )
    # A-F9: the seeded demo consent is `synthetic_fixture`, not a real choice, and reads as
    # `fixture`, not `explicit`/`confirmed` -- only the stated preference above is explicit.
    suggestions = next(f for f in model["facts"] if f["key"] == "suggestions")
    assert suggestions["source_type"] == "fixture"
    assert suggestions["confirmed"] is False

    metrics = client.get("/v1/metrics").json()
    quality = metrics["world_model_quality"]
    assert quality["facts"] == len(model["facts"])
    assert quality["explicit"] >= 1  # the stated preference
    assert quality["fixture"] >= 1  # the seeded consent, and the persona biography/identity
    # Counts only: the facts themselves never travel to the coordinator surface.
    assert "facts" not in metrics or isinstance(metrics.get("facts"), int)
    assert "I like company" not in metrics.__repr__()


def test_world_model_after_reset_keeps_the_stated_belief_and_drops_the_inferred_one(
    client: TestClient,
) -> None:
    """ADR 0004: reset run-scopes inferred preferences instead of deleting them; the world model
    must read that exactly like ranking and `GET .../activity-preferences` do."""
    results = client.post("/v1/activities/search", json={"intent": {}}).json()["results"]
    far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
    client.post(
        f"/v1/activities/{far['candidate']['activity_id']}/response",
        json={"response": "not_for_me", "reason": "too_far"},
    )
    stated = client.put(
        f"/v1/people/{DEMO_PERSON_ID}/activity-preferences/social/social",
        json={"stance": "prefer", "stated_text": "I like company"},
    )
    assert stated.status_code == 200, stated.text

    before_keys = {
        fact["key"]
        for fact in client.get(f"/v1/people/{DEMO_PERSON_ID}/world-model").json()["facts"]
    }
    assert "preference:distance:lower:decline_reason" in before_keys
    assert "preference:social:social:senior_statement" in before_keys

    assert client.post("/v1/demo/reset").status_code == 200

    after_keys = {
        fact["key"]
        for fact in client.get(f"/v1/people/{DEMO_PERSON_ID}/world-model").json()["facts"]
    }
    assert "preference:distance:lower:decline_reason" not in after_keys
    assert "preference:social:social:senior_statement" in after_keys


def test_expired_excluded_does_not_grow_across_resets(client: TestClient) -> None:
    """ADR 0004: run-scoping a `decline_reason` row after a reset is not the same fact as it
    lapsing on the calendar, and must not be counted the same way. `quality.expired_excluded`
    stayed meaning calendar-expired only; a stale-run row is simply absent from the model, not
    shown to the senior as one more "expired and excluded" fact that grows every time the demo
    is reset."""

    def _expired_excluded() -> int:
        model = client.get(f"/v1/people/{DEMO_PERSON_ID}/world-model").json()
        return model["quality"]["expired_excluded"]

    baseline = _expired_excluded()

    for _ in range(3):
        results = client.post("/v1/activities/search", json={"intent": {}}).json()["results"]
        far = next(r for r in results if (r["candidate"]["distance_m"] or 0) >= 2000)
        client.post(
            f"/v1/activities/{far['candidate']['activity_id']}/response",
            json={"response": "not_for_me", "reason": "too_far"},
        )
        # The inferred belief just written is active, not expired -- it must not move the count.
        assert _expired_excluded() == baseline

        assert client.post("/v1/demo/reset").status_code == 200
        # The row that decline just wrote is now run-scoped to a retired run: absent from the
        # model, but not double-counted as one more "expired" fact each time this loop resets.
        assert _expired_excluded() == baseline


# ── Contradictions are shown, staleness is labelled, answers are momentary ────────────────────


def test_a_stated_and_an_inferred_belief_that_disagree_are_linked_not_averaged() -> None:
    model = build_world_model(
        _inputs(
            preferences=[
                _preference("decline_reason", -0.7, value="near"),
                _preference("senior_statement", 1.0, value="near", stated_text="near is best"),
            ]
        )
    )
    facts = {f.key: f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE}
    inferred = facts["preference:distance:near:decline_reason"]
    stated = facts["preference:distance:near:senior_statement"]
    assert inferred.contradicts == [stated.key]
    assert stated.contradicts == [inferred.key]
    assert "those win" in inferred.statement and "those win" not in stated.statement
    # One disagreement, whichever side it is read from.
    assert model.quality.contradictions == 1


def test_two_beliefs_leaning_the_same_way_are_not_a_contradiction() -> None:
    model = build_world_model(
        _inputs(
            preferences=[
                _preference("decline_reason", -0.7, value="far"),
                _preference("senior_statement", -1.0, value="far"),
            ]
        )
    )
    assert model.quality.contradictions == 0
    assert all(not f.contradicts for f in model.facts)


def test_an_inferred_fact_nobody_has_reinforced_for_months_is_labelled_stale() -> None:
    model = build_world_model(
        _inputs(
            preferences=[
                _preference("inferred", 0.4, updated_at=NOW - timedelta(days=120)),
                _preference(
                    "senior_statement", 1.0, value="near", updated_at=NOW - timedelta(days=400)
                ),
            ]
        )
    )
    facts = {f.key: f for f in model.facts}
    assert facts["preference:distance:far:inferred"].stale is True
    # A statement does not go stale: the person said it, and only they can change it.
    assert facts["preference:distance:near:senior_statement"].stale is False
    assert model.quality.stale == 1


def test_a_context_answer_is_a_fact_about_one_day_and_lapses_after_it() -> None:
    from silverloop.world_model import ContextAnswerFact

    model = build_world_model(
        _inputs(
            context_answers=[
                ContextAnswerFact(
                    question_id="quiet_day_check_in",
                    value="resting",
                    label="Just resting today",
                    answer_id="ctxans_1",
                    answered_at=NOW,
                    answered_on_day=TODAY,
                )
            ]
        )
    )
    fact = next(f for f in model.facts if f.category is FactCategory.CONTEXT)
    assert fact.expires_at is not None
    assert local_date(fact.expires_at) == TODAY + timedelta(days=1)
    assert model.quality.temporary == 1


def test_the_quiet_day_question_is_reachable_and_its_answer_is_bounded_to_the_day(
    client: TestClient,
) -> None:
    """Regression for the dead surface: every demo persona has a biography, and the biography
    used to satisfy the question's "already explained" guard, so no persona was ever asked."""
    pending = None
    for _ in range(6):
        client.post("/v1/simulation/advance", json={"event": "activity_declines"})
        state = client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()
        if state["pending_question"] is not None:
            pending = state["pending_question"]
            break
    assert pending is not None, "a gentle nudge day never raised the question"
    answered = client.post(
        f"/v1/people/{DEMO_PERSON_ID}/context-answer",
        json={"question_id": pending["question_id"], "value": pending["options"][0]["value"]},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["audit_event"]["detail"]["day"] == state["current_day"]

    model = client.get(f"/v1/people/{DEMO_PERSON_ID}/world-model").json()
    context = [f for f in model["facts"] if f["category"] == "context"]
    assert len(context) == 1 and context[0]["expires_at"] is not None
    # Asked once per run, never queued.
    assert client.get(f"/v1/people/{DEMO_PERSON_ID}/state").json()["pending_question"] is None


def test_two_inferred_beliefs_that_disagree_do_not_invent_the_person_s_words() -> None:
    model = build_world_model(
        _inputs(
            preferences=[
                _preference("decline_reason", -0.5, value="far"),
                _preference("inferred", 0.4, value="far"),
            ]
        )
    )
    facts = [f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE]
    assert all(f.contradicts for f in facts)
    assert not any("own words" in f.statement for f in facts)
    assert model.quality.contradictions == 1


def test_a_goal_and_a_stated_avoid_on_the_same_value_are_two_beliefs_not_one() -> None:
    """D20. A goal resolves with the source `senior_statement`, so it used to share the resolver
    key `social:social:senior_statement` with a stated avoid on the same value. The world model
    then read the goal's `contradicted_by` under the statement's key and reported the person's
    own words contradicting *themselves*, while the goal fact showed no disagreement at all."""
    from silverloop.models import ActivityGoal, GoalKind
    from silverloop.preferences import resolve

    avoid = _preference(
        "senior_statement",
        -1.0,
        dimension=PreferenceDimension.SOCIAL,
        value="social",
        stated_text="I'd rather be on my own",
    )
    goal = ActivityGoal(
        goal_id="goal_1",
        kind=GoalKind.MEET_PEOPLE,
        text="Spend more time with other people",
        created_at=NOW,
    )
    resolved = resolve([avoid], TODAY, goals=[goal])
    keys = [preference.supporting[0] for preference in resolved]
    assert sorted(keys) == ["goal:social:social", "social:social:senior_statement"]
    for preference in resolved:
        assert preference.supporting[0] not in preference.contradicted_by

    # Resolved by the caller (as the repository does) and resolved here must agree.
    for inputs in (
        _inputs(preferences=[avoid], goals=[goal], resolved=resolved),
        _inputs(preferences=[avoid], goals=[goal]),
    ):
        model = build_world_model(inputs)
        facts = {f.key: f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE}
        stated = facts["preference:social:social:senior_statement"]
        goal_fact = facts["goal:meet_people"]
        assert stated.contradicts == ["goal:meet_people"]
        assert goal_fact.contradicts == ["preference:social:social:senior_statement"]
        assert all(f.key not in f.contradicts for f in facts.values())
        # A goal is a choice from a list, not the person's own words.
        assert not any("own words say otherwise" in f.statement for f in facts.values())
        assert model.quality.contradictions == 1


def test_only_a_statement_is_ever_called_the_person_s_own_words() -> None:
    """D20. An inferred belief contradicted by a goal is shown as a disagreement, never narrated as
    "your own words say otherwise" -- that sentence is kept for what the person actually said."""
    from silverloop.models import ActivityGoal, GoalKind

    learned = _preference(
        "decline_reason",
        -0.5,
        dimension=PreferenceDimension.TIMING,
        value="morning",
        observations=3,
    )
    goal = ActivityGoal(
        goal_id="goal_2",
        kind=GoalKind.MORNING_ACTIVITY,
        text="Do something in the morning",
        created_at=NOW,
    )
    model = build_world_model(_inputs(preferences=[learned], goals=[goal]))
    facts = {f.key: f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE}
    inferred = facts["preference:timing:morning:decline_reason"]
    assert inferred.contradicts == ["goal:morning_activity"]
    assert facts["goal:morning_activity"].contradicts == [inferred.key]
    assert "own words" not in inferred.statement
    assert model.quality.contradictions == 1


def test_a_learned_distance_ceiling_is_never_narrated_as_a_lean_away_from_home() -> None:
    """The sentence a person actually reads on the Privacy screen.

    A "too far" at 1.2 km used to be stored as the bucket the listing fell in -- `near` -- and
    this fact then said "You lean away from things close to home", to someone who had said no
    such thing. It is a line, and it is narrated as one, in their own units.
    """
    from silverloop.models import DimensionPreference, PreferenceDimension
    from silverloop.world_model import build_world_model

    ceiling = DimensionPreference(
        dimension=PreferenceDimension.DISTANCE,
        value="lower",
        strength=0.333,
        source="decline_reason",
        observations=1,
        positive_evidence=1.0,
        pivot=1200,
        direction="lower",
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    model = build_world_model(_inputs(preferences=[ceiling]))
    fact = next(f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE)
    assert "closer than about 1.2 km" in fact.statement
    assert "lean" not in fact.statement
    assert "close to home" not in fact.statement


def test_attended_programmes_use_the_rankers_series_identity_across_case_and_spacing(
    repository: SqlAlchemyRepository,
) -> None:
    """X2: the world model's attended-programme facts and the ranker's `series_key` are one
    definition. Two sessions whose provider and title differ only in case and spacing are one
    programme to both, and the fact key keeps its `activity:{provider|title}` encoding."""
    from silverloop.activity_search import series_identity, series_key
    from silverloop.db_models import ActivityCandidateRow, PlanFollowThroughRow, WeekPlanEntryRow

    with repository.sessions.begin() as session:
        run = repository._active_run(session, DEMO_PERSON_ID)
        first = session.get(ActivityCandidateRow, "activity-chair-mobility-1")
        second = session.get(ActivityCandidateRow, "activity-chair-mobility-2")
        assert first is not None and second is not None
        second.title = f"  {first.title.upper()}  "
        second.provider = f"{first.provider.lower()} "
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        for index, row in enumerate((first, second)):
            plan_id = f"plan-x2-{index}"
            session.add(
                WeekPlanEntryRow(
                    plan_id=plan_id,
                    run_id=run.run_id,
                    person_id=DEMO_PERSON_ID,
                    day=run.current_day - timedelta(days=index + 1),
                    activity_id=row.activity_id,
                    origin="chosen",
                    created_at=now,
                )
            )
            session.flush()
            session.add(
                PlanFollowThroughRow(
                    follow_through_id=f"ft-x2-{index}",
                    plan_id=plan_id,
                    run_id=run.run_id,
                    person_id=DEMO_PERSON_ID,
                    follow_through="went",
                    note=None,
                    actor="test",
                    recorded_at=now,
                )
            )

    catalogue = {c.activity_id: c for c in repository.list_activities()}
    one, two = catalogue["activity-chair-mobility-1"], catalogue["activity-chair-mobility-2"]
    assert (one.title, one.provider) != (two.title, two.provider)
    assert series_key(one) == series_key(two)

    with repository.sessions() as session:
        run = repository._active_run(session, DEMO_PERSON_ID)
        history = SqlAlchemyRepository._attended_series(session, DEMO_PERSON_ID, run.run_id)
    assert [(h.series_key, h.went) for h in history] == [("|".join(series_identity(one)), 2)]

    facts = [f for f in repository.world_model().facts if f.key.startswith("activity:")]
    assert [f.key for f in facts] == [f"activity:{'|'.join(series_identity(two))}"]


# ── Which side of a disagreement is in effect, decided by the resolver ────────────────────────


def _outcomes(preferences: list, goals: list | None = None) -> dict:  # noqa: ANN001
    model = build_world_model(_inputs(preferences=preferences, goals=goals or []))
    return {
        fact.key: (fact.in_effect, fact.contradiction_outcome)
        for fact in model.facts
        if fact.category is FactCategory.ACTIVITY_PREFERENCE
    }


def test_a_statement_applies_over_the_learned_belief_it_contradicts() -> None:
    stated = _preference(
        "senior_statement", -1.0, dimension=PreferenceDimension.SOCIAL, value="social"
    )
    learned = _preference(
        "inferred",
        0.5,
        dimension=PreferenceDimension.SOCIAL,
        value="social",
        positive_evidence=2.0,
        observations=2,
    )
    assert _outcomes([stated, learned]) == {
        "preference:social:social:senior_statement": (True, "this_applies"),
        "preference:social:social:inferred": (False, "other_applies"),
    }
    facts = {f.key: f for f in build_world_model(_inputs(preferences=[stated, learned])).facts}
    assert facts["preference:social:social:inferred"].statement.endswith(
        " Your own words say otherwise, and those win."
    )
    assert "those win" not in facts["preference:social:social:senior_statement"].statement


def test_a_stated_belief_applies_over_a_goal_on_the_same_value() -> None:
    from silverloop.models import ActivityGoal, GoalKind

    avoid = _preference(
        "senior_statement", -1.0, dimension=PreferenceDimension.SOCIAL, value="social"
    )
    goal = ActivityGoal(
        goal_id="g", kind=GoalKind.MEET_PEOPLE, text="Spend time with people", created_at=NOW
    )
    assert _outcomes([avoid], [goal]) == {
        "preference:social:social:senior_statement": (True, "this_applies"),
        "goal:meet_people": (False, "other_applies"),
    }


def test_a_goal_applies_over_a_learned_belief_it_contradicts() -> None:
    from silverloop.models import ActivityGoal, GoalKind

    learned = _preference(
        "decline_reason",
        -0.5,
        dimension=PreferenceDimension.TIMING,
        value="morning",
        negative_evidence=2.0,
        observations=2,
    )
    goal = ActivityGoal(
        goal_id="g",
        kind=GoalKind.MORNING_ACTIVITY,
        text="Do something in the morning",
        created_at=NOW,
    )
    assert _outcomes([learned], [goal]) == {
        "preference:timing:morning:decline_reason": (False, "other_applies"),
        "goal:morning_activity": (True, "this_applies"),
    }


def test_a_temporary_avoid_applies_over_a_learned_like_on_that_kind() -> None:
    temporary = _preference(
        "senior_statement",
        -1.0,
        dimension=PreferenceDimension.ACTIVITY_TYPE,
        value="walking",
        expires_at=datetime(2026, 9, 30, 23, 59, tzinfo=UTC),
    )
    learned = _preference(
        "inferred",
        0.333,
        dimension=PreferenceDimension.ACTIVITY_TYPE,
        value="walking",
        positive_evidence=1.0,
    )
    assert _outcomes([temporary, learned]) == {
        "preference:activity_type:walking:senior_statement": (True, "this_applies"),
        "preference:activity_type:walking:inferred": (False, "other_applies"),
    }


def test_equal_tiers_leaning_opposite_ways_are_undecided() -> None:
    from silverloop.models import ClarificationScope

    avoid = _preference(
        "decline_reason",
        -0.333,
        dimension=PreferenceDimension.ACTIVITY_TYPE,
        value="walking",
        negative_evidence=1.0,
        scope=ClarificationScope.THIS_ACTIVITY_TYPE,
    )
    like = _preference(
        "inferred",
        0.333,
        dimension=PreferenceDimension.ACTIVITY_TYPE,
        value="walking",
        positive_evidence=1.0,
    )
    assert _outcomes([avoid, like]) == {
        "preference:activity_type:walking:decline_reason": (True, "undecided"),
        "preference:activity_type:walking:inferred": (True, "undecided"),
    }


def test_a_higher_tier_on_another_value_of_the_axis_means_neither_side_applies() -> None:
    """The review's case: a morning goal and a learned avoid of mornings disagree, but the person's
    own stated like of afternoons wins the whole TIMING axis -- neither morning belief is used, and
    no screen may tell the person the goal "wins"."""
    from silverloop.models import ActivityGoal, ClarificationScope, GoalKind

    learned_avoid_morning = _preference(
        "decline_reason",
        -0.5,
        dimension=PreferenceDimension.TIMING,
        value="morning",
        negative_evidence=2.0,
        observations=2,
        scope=ClarificationScope.THIS_SLOT,
    )
    stated_afternoon = _preference(
        "senior_statement", 1.0, dimension=PreferenceDimension.TIMING, value="afternoon"
    )
    goal = ActivityGoal(
        goal_id="g",
        kind=GoalKind.MORNING_ACTIVITY,
        text="Do something in the morning",
        created_at=NOW,
    )
    outcomes = _outcomes([learned_avoid_morning, stated_afternoon], [goal])
    assert outcomes == {
        "preference:timing:morning:decline_reason": (False, "neither_applies"),
        "preference:timing:afternoon:senior_statement": (True, None),
        "goal:morning_activity": (False, "neither_applies"),
    }


def test_in_effect_is_none_for_facts_that_are_not_preference_beliefs() -> None:
    from silverloop.models import ActivityGoal, ClarificationScope, GoalKind

    held_back = _preference(
        "decline_reason",
        -0.333,
        dimension=PreferenceDimension.TIMING,
        value="evening",
        negative_evidence=1.0,
        scope=ClarificationScope.THIS_SLOT,
    )
    unmapped_goal = ActivityGoal(
        goal_id="g", kind=GoalKind.GET_OUT_MORE, text="Get out more", created_at=NOW
    )
    model = build_world_model(_inputs(preferences=[held_back], goals=[unmapped_goal]))
    facts = {fact.key: fact for fact in model.facts}
    assert facts["preference:timing:evening:decline_reason"].in_effect is False
    assert facts["goal:get_out_more"].in_effect is None
    for fact in model.facts:
        if fact.category is not FactCategory.ACTIVITY_PREFERENCE:
            assert fact.in_effect is None and fact.contradiction_outcome is None


def test_those_win_is_only_said_when_the_persons_words_are_the_belief_in_effect() -> None:
    """A learned like of mornings contradicted by a stated avoid of mornings, while a temporary like
    of afternoons wins the whole TIMING axis: neither morning belief applies, so the learned fact
    must not claim the person's words "win"."""
    from silverloop.models import ActivityGoal, ClarificationScope, GoalKind

    learned_like_morning = _preference(
        "inferred",
        0.5,
        dimension=PreferenceDimension.TIMING,
        value="morning",
        positive_evidence=2.0,
        observations=2,
    )
    stated_avoid_morning = _preference(
        "senior_statement", -1.0, dimension=PreferenceDimension.TIMING, value="morning"
    )
    temporary_afternoon = _preference(
        "senior_statement",
        1.0,
        dimension=PreferenceDimension.TIMING,
        value="afternoon",
        expires_at=datetime(2026, 9, 30, 23, 59, tzinfo=UTC),
    )
    model = build_world_model(
        _inputs(preferences=[learned_like_morning, stated_avoid_morning, temporary_afternoon])
    )
    facts = {f.key: f for f in model.facts}
    learned = facts["preference:timing:morning:inferred"]
    assert learned.contradiction_outcome == "neither_applies"
    assert facts["preference:timing:morning:senior_statement"].contradiction_outcome == (
        "neither_applies"
    )
    assert "those win" not in learned.statement

    # The review's TIMING case (goal, learned avoid of mornings, stated afternoon): said nowhere.
    learned_avoid_morning = _preference(
        "decline_reason",
        -0.5,
        dimension=PreferenceDimension.TIMING,
        value="morning",
        negative_evidence=2.0,
        observations=2,
        scope=ClarificationScope.THIS_SLOT,
    )
    stated_afternoon = _preference(
        "senior_statement", 1.0, dimension=PreferenceDimension.TIMING, value="afternoon"
    )
    goal = ActivityGoal(
        goal_id="g",
        kind=GoalKind.MORNING_ACTIVITY,
        text="Do something in the morning",
        created_at=NOW,
    )
    review = build_world_model(
        _inputs(preferences=[learned_avoid_morning, stated_afternoon], goals=[goal])
    )
    assert not any("those win" in f.statement for f in review.facts)
    assert {f.key: f.contradiction_outcome for f in review.facts if f.contradiction_outcome} == {
        "preference:timing:morning:decline_reason": "neither_applies",
        "goal:morning_activity": "neither_applies",
    }


def test_the_less_travel_goal_is_a_distance_belief_in_effect_beside_a_learned_ceiling() -> None:
    """`less_travel` folds in as a stated "near" with no number: its own resolution group, so a
    learned "too far" line never takes it out of effect, and a stated avoid on "near" is shown as
    the disagreement it is -- with the person's own words applying."""
    from silverloop.models import ActivityGoal, GoalKind
    from silverloop.preferences import apply_decline, resolve
    from silverloop.world_model import build_world_model

    goal = ActivityGoal(
        goal_id="goal_less",
        kind=GoalKind.LESS_TRAVEL,
        text="Travel less to get to things",
        created_at=NOW,
    )
    from silverloop.models import (
        ActivityCandidate,
        ActivityLocation,
        ActivitySource,
        IndoorOutdoor,
        IntegrationStatus,
    )

    listing = ActivityCandidate(
        activity_id="far-walk",
        source=ActivitySource.AAC_FIXTURE,
        integration_status=IntegrationStatus.FIXTURE,
        title="Walk",
        provider="Centre",
        location=ActivityLocation(name="Centre"),
        indoor_outdoor=IndoorOutdoor.OUTDOOR,
        retrieved_at=NOW,
        distance_m=650,
    )
    ceiling = apply_decline([], DeclineReason.TOO_FAR, listing, NOW, origin_id="r1")
    model = build_world_model(
        _inputs(preferences=ceiling, goals=[goal], resolved=resolve(ceiling, TODAY, goals=[goal]))
    )
    facts = {f.key: f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE}
    assert facts["goal:less_travel"].in_effect is True
    assert facts["goal:less_travel"].contradicts == []
    assert facts["preference:distance:lower:decline_reason"].in_effect is True

    # A stated avoid on "near" leans far: it is shown as the disagreement it is, but it is never
    # read, so it cannot take the goal out of effect -- the goal is what applies.
    avoid_near = _preference(
        "senior_statement", -1.0, dimension=PreferenceDimension.DISTANCE, value="near"
    )
    model = build_world_model(_inputs(preferences=[avoid_near], goals=[goal]))
    facts = {f.key: f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE}
    goal_fact = facts["goal:less_travel"]
    avoid_fact = facts["preference:distance:near:senior_statement"]
    assert goal_fact.contradicts == [avoid_fact.key]
    assert (goal_fact.in_effect, goal_fact.contradiction_outcome) == (True, "this_applies")
    assert (avoid_fact.in_effect, avoid_fact.contradiction_outcome) == (False, "other_applies")


def test_a_stated_far_beside_the_less_travel_goal_is_reported_as_not_in_effect() -> None:
    """A stated "far" outranks the goal by tier, but a statement with no number never widens how
    far is comfortable: the goal stays in effect, and the "far" fact says honestly that it is not
    -- in the world model and in the ranker inspector alike."""
    from silverloop.models import ActivityGoal, GoalKind
    from silverloop.preferences import resolve, travel_tolerance_basis, travel_tolerance_m

    goal = ActivityGoal(
        goal_id="goal_less",
        kind=GoalKind.LESS_TRAVEL,
        text="Travel less to get to things",
        created_at=NOW,
    )
    far = _preference("senior_statement", 1.0, dimension=PreferenceDimension.DISTANCE, value="far")
    floor = _preference(
        "inferred",
        0.333,
        dimension=PreferenceDimension.DISTANCE,
        value="higher",
        pivot=2000.0,
        direction="higher",
        observations=1,
    )
    resolved = resolve([far, floor], TODAY, goals=[goal])
    assert (travel_tolerance_m(resolved), travel_tolerance_basis(resolved)) == (1000, "stated_near")

    model = build_world_model(_inputs(preferences=[far, floor], goals=[goal], resolved=resolved))
    facts = {f.key: f for f in model.facts if f.category is FactCategory.ACTIVITY_PREFERENCE}
    assert facts["goal:less_travel"].in_effect is True
    assert facts["preference:distance:far:senior_statement"].in_effect is False
    assert facts["preference:distance:higher:inferred"].in_effect is True
    # Different values, so not a contradiction: nothing is narrated as disagreeing.
    assert facts["goal:less_travel"].contradicts == []
    assert facts["preference:distance:far:senior_statement"].contradicts == []
