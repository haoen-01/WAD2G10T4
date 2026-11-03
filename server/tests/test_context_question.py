"""The one question worth asking.

These tests pin the product claim `context_question.py` exists to satisfy: a question is only
worth asking when the answer would change something real. Every "no question" case here mirrors a
sentence in the module's own docstring, so a future change that quietly starts asking on one of
these days should fail loudly here first.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from silverloop.context_question import QUESTION_ID, memory_from_answer, question_for
from silverloop.models import (
    AttentionBand,
    BaselineSummary,
    ContextSignal,
    DataQualityAssessment,
    Decision,
    PersonState,
    PolicyGate,
    PreferenceDimension,
    SignalSummary,
)

NOW = datetime(2026, 9, 6, 10, 0, tzinfo=UTC)
TODAY = date(2026, 9, 6)


def _quality(**overrides: object) -> DataQualityAssessment:
    defaults: dict[str, object] = dict(
        evidence_id="E-QUAL-1",
        assessed_at=NOW,
        source="synthetic",
        confidence=0.9,
        safe_to_interpret=True,
        reasons=[],
    )
    defaults.update(overrides)
    return DataQualityAssessment(**defaults)


def _signal(**overrides: object) -> SignalSummary:
    defaults: dict[str, object] = dict(
        current_steps=1200,
        delta_percent=-25.0,
        baseline_median_steps=4000,
        robust_z=-2.0,
        sustained_low_days=2,
        confidence=0.8,
        context=ContextSignal(),
        quality=_quality(),
    )
    defaults.update(overrides)
    return SignalSummary(**defaults)


def _state(**overrides: object) -> PersonState:
    defaults: dict[str, object] = dict(
        person_id="p1",
        display_name="Test Person",
        preferred_language="en",
        consent_active=True,
        current_day=TODAY,
        attention_band=AttentionBand.WATCH,
        baseline=BaselineSummary(
            window_days=28, median_steps=4000, mad_steps=500, data_quality=0.9
        ),
        signal=_signal(),
        last_decision=Decision.GENTLE_NUDGE,
        rationale=["Activity is below the personal baseline."],
        decided_by_gate=PolicyGate.SEVERITY_PERSISTENCE,
        permitted_actions=[Decision.GENTLE_NUDGE, Decision.NO_ACTION],
    )
    defaults.update(overrides)
    return PersonState(**defaults)


# ── Asked only when it would change something ────────────────────────────────────────────────


def test_asks_when_outreach_is_permitted_and_nothing_explains_the_gap() -> None:
    question = question_for(_state(), asked_recently=False)
    assert question is not None
    assert question.question_id == QUESTION_ID
    assert len(question.options) >= 3
    assert "%" in question.asked_because or "below" in question.asked_because


def test_asked_recently_suppresses_a_repeat_question() -> None:
    assert question_for(_state(), asked_recently=True) is None


def test_no_action_asks_nothing_because_nothing_is_being_sent_either_way() -> None:
    state = _state(last_decision=Decision.NO_ACTION)
    assert question_for(state, asked_recently=False) is None


def test_suppress_asks_nothing_because_outreach_is_already_blocked() -> None:
    state = _state(last_decision=Decision.SUPPRESS)
    assert question_for(state, asked_recently=False) is None


def test_coordinator_review_asks_nothing_because_a_human_is_already_looking() -> None:
    state = _state(last_decision=Decision.COORDINATOR_REVIEW)
    assert question_for(state, asked_recently=False) is None


def test_unreliable_tracker_asks_nothing() -> None:
    state = _state(signal=_signal(quality=_quality(safe_to_interpret=False)))
    assert question_for(state, asked_recently=False) is None


def test_rain_already_explaining_a_single_low_day_asks_nothing() -> None:
    state = _state(
        signal=_signal(sustained_low_days=1, context=ContextSignal(rainy=True)),
    )
    assert question_for(state, asked_recently=False) is None


def test_rain_no_longer_explains_a_persistent_decline_so_the_question_still_fires() -> None:
    state = _state(
        signal=_signal(sustained_low_days=3, context=ContextSignal(rainy=True)),
        last_decision=Decision.PROGRAMME_SUGGESTION,
    )
    assert question_for(state, asked_recently=False) is not None


def test_a_persona_biography_never_silences_the_question() -> None:
    """`context_note` is the fixture biography every demo persona carries. When it gated the
    question, no persona could ever be asked -- the whole context surface was dead."""
    state = _state(context_note="Socially motivated; responds well to group-based encouragement.")
    assert question_for(state, asked_recently=False) is not None
    # What does silence it is having already answered this run.
    assert question_for(state, asked_recently=True) is None


def test_programme_suggestion_is_also_decision_changing() -> None:
    state = _state(last_decision=Decision.PROGRAMME_SUGGESTION)
    assert question_for(state, asked_recently=False) is not None


# ── asked_because names the specific gap ─────────────────────────────────────────────────────


def test_asked_because_is_never_empty_and_names_a_reason() -> None:
    question = question_for(_state(), asked_recently=False)
    assert question is not None
    assert len(question.asked_because) > 10


# ── memory_from_answer never invents, only proposes ──────────────────────────────────────────


def test_no_mention_of_company_proposes_nothing() -> None:
    assert memory_from_answer(QUESTION_ID, "not_feeling_it", None, NOW) is None
    assert memory_from_answer(QUESTION_ID, "not_feeling_it", "just tired today", NOW) is None


def test_a_note_naming_going_out_alone_proposes_a_social_memory() -> None:
    proposal = memory_from_answer(
        QUESTION_ID, "not_feeling_it", "I don't like going out alone", NOW
    )
    assert proposal is not None
    assert proposal.dimension is PreferenceDimension.SOCIAL
    assert proposal.source_text == "I don't like going out alone"
    assert proposal.created_at == NOW


def test_other_answer_values_never_propose_a_memory_even_with_the_same_note() -> None:
    assert memory_from_answer(QUESTION_ID, "away", "I don't like going out alone", NOW) is None


def test_wrong_question_id_proposes_nothing() -> None:
    assert memory_from_answer("some_other_question", "not_feeling_it", "alone is hard", NOW) is None


def test_memory_from_answer_never_writes_only_proposes() -> None:
    """The proposal is inert data; nothing about calling this function stores anything."""
    proposal = memory_from_answer(
        QUESTION_ID, "not_feeling_it", "I really don't enjoy going out alone", NOW
    )
    assert proposal is not None
    assert proposal.question
    assert proposal.statement
