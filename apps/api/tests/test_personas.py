"""F5: multi-persona seeding.

Covers acceptance criteria that do not fit naturally inside `test_multi_person.py`: the persona
registry's shape, the `mdm-lim` compatibility guarantee, and the product's central "personal, not
population-average" claim.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from silverloop.analytics import analyse_signal
from silverloop.fixtures import (
    DEMO_PERSON_ID,
    DEMO_PERSONAS,
    persona_profile,
    persona_seed,
    synthetic_history,
)
from silverloop.models import ContextSignal, DailyMetric, Decision
from silverloop.policy import decide

# Pinned before F5 landed, from `synthetic_history(persona_seed(DEMO_PERSON_ID, 2026))`; see the
# "prove it" requirement in the F5 spec. If this ever changes, `mdm-lim` regenerated and every
# scenario/e2e assertion/committed evaluation artifact pinned to her fixture must move with it.
MDM_LIM_HISTORY_HASH = "84e95ee415e9f10811550891407cf1dccdd304c2abb4a940174c6a2461f6cbbf"


def _history_hash(person_id: str, base_seed: int = 2026) -> str:
    profile = persona_profile(person_id)
    history, current = synthetic_history(persona_seed(person_id, base_seed), profile)
    raw = repr(history) + repr(current)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- Registry shape ----------------------------------------------------------------------------


def test_six_personas_are_registered() -> None:
    assert set(DEMO_PERSONAS) == {
        "mdm-lim",
        "mr-ravi",
        "mdm-siti",
        "mr-tan",
        "mdm-devi",
        "mdm-wong",
    }


def test_playbook_personas_are_labelled_correctly() -> None:
    """`mr-tan`, `mdm-devi` and `mdm-wong` are synthetic inventions, not playbook personas --
    each must say so explicitly, and never claim a research/interview basis.
    """
    for person_id in ("mdm-lim", "mr-ravi", "mdm-siti"):
        assert DEMO_PERSONAS[person_id].is_playbook_persona is True

    for person_id in ("mr-tan", "mdm-devi", "mdm-wong"):
        profile = DEMO_PERSONAS[person_id]
        assert profile.is_playbook_persona is False
        assert "SYNTHETIC" in profile.notes
        assert "playbook" not in profile.notes.split("SYNTHETIC")[0].lower()


def test_mdm_wong_is_the_review_threshold_persona() -> None:
    """Invented to exercise the review-threshold calibrator (ADR 0008): a wide ordinary swing."""
    profile = DEMO_PERSONAS["mdm-wong"]
    assert profile.display_name == "Mdm Wong"
    assert profile.preferred_language == "English / Cantonese"
    assert profile.age == 72
    assert profile.seed_offset == 25000
    assert persona_seed("mdm-wong", 2026) == 27026
    assert (profile.baseline_steps, profile.step_std, profile.weekend_multiplier) == (
        5800,
        1620.0,
        0.70,
    )
    assert (profile.history_days, profile.tracker_adherence) == (90, 0.97)
    assert profile.context_note == (
        "Synthetic profile; activity naturally swings a lot from week to week."
    )
    assert "review-threshold calibrator" in profile.notes


def test_persona_seed_offsets_are_unique() -> None:
    offsets = [profile.seed_offset for profile in DEMO_PERSONAS.values()]
    assert len(offsets) == len(set(offsets))


# --- Hard compatibility constraint: mdm-lim's fixture never moves --------------------------------


def test_persona_seed_for_demo_person_is_unchanged() -> None:
    assert persona_seed(DEMO_PERSON_ID, 2026) == 2026


def test_mdm_lim_history_is_byte_identical_to_pre_f5() -> None:
    assert _history_hash(DEMO_PERSON_ID) == MDM_LIM_HISTORY_HASH


def test_mdm_lim_history_shape_is_unchanged() -> None:
    profile = persona_profile(DEMO_PERSON_ID)
    history, current = synthetic_history(persona_seed(DEMO_PERSON_ID, 2026), profile)
    assert len(history) == 28
    assert current.steps == 5720
    assert current.active_minutes == 40
    assert current.sleep_hours == 7.1
    assert current.wear_hours == 13.5


# --- The product's central claim: personal, not population-average ------------------------------


def test_same_absolute_steps_yield_different_decisions_for_mdm_lim_and_mr_ravi() -> None:
    """The exact same absolute step count (2,500/day) is a ~56% decline for `mdm-lim` (baseline
    ~5,850) and a normal day for `mr-ravi` (baseline ~2,400). A policy that only knows the raw
    number cannot tell these apart; Care+, which knows each person's own baseline, must.
    """
    decisions: dict[str, Decision] = {}
    for person_id in (DEMO_PERSON_ID, "mr-ravi"):
        profile = persona_profile(person_id)
        history, current = synthetic_history(persona_seed(person_id, 2026), profile)
        probe_day = current.day + timedelta(days=1)
        probe_current = DailyMetric(
            day=probe_day,
            steps=2500,
            active_minutes=20,
            sleep_hours=7.0,
            wear_hours=13.2,
            source="synthetic",
        )
        _, signal = analyse_signal(
            [*history, current],
            probe_current,
            ContextSignal(),
            person_id=person_id,
            assessed_at=datetime.combine(probe_day, datetime.min.time(), tzinfo=UTC),
        )
        result = decide(signal, consent_active=True, interventions_last_7_days=0)
        decisions[person_id] = result.decision

    assert decisions[DEMO_PERSON_ID] != decisions["mr-ravi"]
    assert decisions[DEMO_PERSON_ID] == Decision.GENTLE_NUDGE
    assert decisions["mr-ravi"] == Decision.NO_ACTION
