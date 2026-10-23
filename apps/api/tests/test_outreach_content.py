"""`outreach_content.detail_for` -- the screen behind "Yes, tell me more".

Two things are being protected here.

The first is that the button leads somewhere. The bug this module was written to fix was a
primary call to action that recorded a success and then showed the person nothing, so every
offered candidate must return real content and an unknown one must say so plainly rather than
inventing something.

The second is vocabulary. This copy renders inside `.senior-shell`, which
`apps/e2e/tests/product-loop.spec.ts` asserts is free of coordinator language and raw figures.
A percentage or the word "review" reaching this module is a browser-test failure two layers away
from its cause, so it is caught here, at the source, where the message is useful.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from silverloop.models import OutreachDetail, Programme
from silverloop.outreach_content import detail_for

MOVEMENT_KEYS = ["gentle_nudge:chair_mobility", "gentle_nudge:indoor_walk"]

# The exact guard `product-loop.spec.ts` applies to the senior shell. Kept character-for-character
# identical on purpose: if the shell's vocabulary rule changes, both copies should change together
# and this comment should be the reason someone looks.
SENIOR_SHELL_VOCABULARY = re.compile(
    r"\b(?:stable|watch|review|\d+%|\d+ steps|time\(s\)|of \d+|anchor|they|their)\b", re.IGNORECASE
)

PROGRAMME = Programme(
    programme_id="prog-test",
    name="Morning movement group",
    venue="Community hall",
    distance_km=1.2,
    next_session=datetime(2026, 9, 10, 10, 0, tzinfo=UTC),
    accessibility=["step-free access", "seated options"],
    evidence_source="synthetic fixture",
)


def _strings(detail: OutreachDetail) -> list[str]:
    """Every human-readable string the model can put on a screen, including nested steps."""
    values = [detail.title, detail.intro, detail.stop_note, detail.boundary_note]
    values.extend(step.text for step in detail.steps)
    if detail.source:
        values.append(detail.source)
    if detail.programme is not None:
        values.extend([detail.programme.name, detail.programme.venue])
    return [value for value in values if value]


# ── The button leads somewhere ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("candidate_key", MOVEMENT_KEYS)
def test_both_movement_candidates_return_real_steps(candidate_key: str) -> None:
    """Both, not one. Either candidate can be the one that was ranked and offered, so a dead end
    behind either of them is the same dead end for the person who got it."""
    detail = detail_for(candidate_key)

    assert detail.kind == "movement_routine"
    assert detail.title.strip()
    assert detail.intro.strip()
    assert len(detail.steps) >= 3
    assert all(step.text.strip() for step in detail.steps)
    assert [step.order for step in detail.steps] == list(range(1, len(detail.steps) + 1))
    assert detail.source, "fixed content must say where it came from"


@pytest.mark.parametrize("candidate_key", MOVEMENT_KEYS)
def test_every_routine_says_stop_and_states_its_own_boundary(candidate_key: str) -> None:
    """The stop note and the boundary are on the screen, not in a policy document nobody reads."""
    detail = detail_for(candidate_key)

    assert "stop" in detail.stop_note.lower()
    assert "not medical" in detail.boundary_note.lower()
    assert "doctor" in detail.boundary_note.lower()


def test_movement_content_is_identical_between_calls() -> None:
    """Fixed, reviewed content -- checkable by a human once and then still true."""
    assert detail_for(MOVEMENT_KEYS[0]) == detail_for(MOVEMENT_KEYS[0])


def test_the_two_movement_routines_are_actually_different_content() -> None:
    chair, walk = (detail_for(key) for key in MOVEMENT_KEYS)
    assert chair.title != walk.title
    assert [step.text for step in chair.steps] != [step.text for step in walk.steps]


def test_a_programme_candidate_returns_the_programme_details() -> None:
    detail = detail_for(f"programme:{PROGRAMME.programme_id}", PROGRAMME)

    assert detail.kind == "programme_details"
    assert detail.programme == PROGRAMME
    assert PROGRAMME.venue in detail.intro
    # Nothing on this screen may imply Care+ has acted on the person's behalf.
    assert "booked" in detail.intro.lower()


# ── An honest empty state, never a confident one ──────────────────────────────────────────────


def test_an_unknown_candidate_key_returns_none_and_invents_nothing() -> None:
    detail = detail_for("gentle_nudge:something_that_does_not_exist")

    assert detail.kind == "none"
    assert detail.steps == []
    assert detail.programme is None
    # An empty state is allowed to be empty. It is not allowed to be a routine nobody wrote.
    assert "no extra details" in detail.intro.lower()


def test_a_programme_key_without_a_programme_does_not_fabricate_one() -> None:
    """The dangerous near-miss: the key looks right, the data is missing. Inventing a venue and
    a distance here would put a person on a bus to a place that does not exist."""
    detail = detail_for("programme:prog-missing", None)

    assert detail.kind == "none"
    assert detail.programme is None


@pytest.mark.parametrize("candidate_key", ["", "gentle_nudge", "programme", "coordinator_review"])
def test_degenerate_keys_fall_back_rather_than_raising(candidate_key: str) -> None:
    """`candidate_key` can be a bare decision name for interventions that predate candidate
    ranking (see `sql_repository`), so the fallback has to hold for those too."""
    detail = detail_for(candidate_key)

    assert detail.kind == "none"
    assert detail.stop_note.strip()
    assert detail.boundary_note.strip()


# ── Vocabulary: this copy renders inside the senior shell ─────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "detail"),
    [
        ("chair mobility", detail_for("gentle_nudge:chair_mobility")),
        ("indoor walk", detail_for("gentle_nudge:indoor_walk")),
        ("programme", detail_for("programme:prog-test", PROGRAMME)),
        ("empty state", detail_for("unknown-candidate")),
    ],
)
def test_no_returned_string_contains_a_percentage_or_the_word_review(
    label: str, detail: OutreachDetail
) -> None:
    """The mechanical constraint stated in the module's own header, asserted rather than trusted.

    "review" is coordinator vocabulary and a percentage is a raw figure; neither belongs on a
    screen whose entire design rule is that it never describes the system to the reader.
    """
    for value in _strings(detail):
        assert "%" not in value, f"{label}: percentage in {value!r}"
        assert "review" not in value.lower(), f"{label}: coordinator vocabulary in {value!r}"


@pytest.mark.parametrize(
    ("label", "detail"),
    [
        ("chair mobility", detail_for("gentle_nudge:chair_mobility")),
        ("indoor walk", detail_for("gentle_nudge:indoor_walk")),
        ("empty state", detail_for("unknown-candidate")),
    ],
)
def test_fixed_content_passes_the_whole_senior_shell_vocabulary_guard(
    label: str, detail: OutreachDetail
) -> None:
    """Stricter than the rule above, and applied only to the content this module owns.

    The programme detail is excluded because its venue and name come from the programme
    catalogue, which this module does not write; that surface is covered end-to-end by the
    browser test instead.
    """
    for value in _strings(detail):
        match = SENIOR_SHELL_VOCABULARY.search(value)
        assert match is None, f"{label}: {match.group(0)!r} in {value!r}"


@pytest.mark.parametrize("candidate_key", MOVEMENT_KEYS)
def test_movement_content_sets_no_counts_targets_or_durations(candidate_key: str) -> None:
    """The product boundary in the copy itself: general wellbeing content, never a prescription.

    "Ten repetitions" or "for 20 minutes" turns a suggestion into something a person can fail
    at, which is exactly what the stop note promises they cannot.
    """
    detail = detail_for(candidate_key)

    for value in _strings(detail):
        assert not re.search(r"\b\d+\s*(?:reps?|repetitions?|sets?|minutes?|seconds?)\b", value), (
            f"prescriptive count or duration in {value!r}"
        )


def test_every_offerable_nudge_candidate_has_detail_content() -> None:
    """ "Yes, tell me more" must lead somewhere for every candidate the policy can actually offer.

    `gentle_nudge:companion_walk` had no content from the day it was added, and nothing caught it:
    all three nudges start on an identical 0.5 posterior, and the tie broke alphabetically to
    `chair_mobility`, so the companion walk was never selected. Adding the SOCIAL ranking nudge
    changed which candidate wins that tie, and a senior who accepted the suggestion reached a card
    reading "Nothing more to show". The gap was latent for as long as the ordering hid it, so the
    invariant is asserted over the candidate list rather than over a list of keys written twice.
    """
    from datetime import UTC, datetime

    from silverloop.config import Settings
    from silverloop.models import Decision
    from silverloop.sql_repository import SqlAlchemyRepository

    settings = Settings(
        auth_enabled=False, database_url="sqlite+pysqlite:///:memory:", llm_enabled=False
    )
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:", settings=settings)
    repository.create_schema_for_tests()
    repository.reset()
    try:
        with repository.sessions() as session:
            candidates = repository._decision_candidates(
                session, Decision.GENTLE_NUDGE, datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
            )
        assert candidates, "the gentle-nudge ladder must offer something"
        for candidate in candidates:
            detail = detail_for(candidate.key)
            assert detail is not None, f"{candidate.key} has no detail content"
            assert detail.steps, f"{candidate.key} has a detail card with no steps"
    finally:
        repository.close()
