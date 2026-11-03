"""A case can tell the story of what Care+ already tried (audit-H finding 9).

The card showed a person, a fixed title, a percentage sentence, three fixed policy strings and one
recommendation -- identical for every case and for every person. The day-one nudge and day-two
suggestion that *preceded* the review, and whether anyone answered them, lived on a completely
separate per-person card that defaulted to Mdm Lim regardless of whose case was on screen.

"Why does this need a human?" was the same sentence for everyone. It is now authored from two
facts the case already has: which rung of the ladder stopped, and what was tried before it. The
template is deterministic and lives in code -- an LLM-written case summary would mean a reviewer
could no longer be sure they were reading policy output rather than a model's paraphrase of it.
"""

from __future__ import annotations

from silverloop.models import Decision, OutcomeKind, PolicyGate
from silverloop.sql_repository import SqlAlchemyRepository, _why_human


def _repo() -> SqlAlchemyRepository:
    repository = SqlAlchemyRepository("sqlite+pysqlite:///:memory:")
    repository.create_schema_for_tests()
    repository.reset()
    return repository


def test_the_case_carries_the_outreach_that_preceded_it() -> None:
    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"prior-{index}")

        case = repository.list_cases()[0]

        assert [step.decision for step in case.prior_outreach] == [
            Decision.GENTLE_NUDGE,
            Decision.PROGRAMME_SUGGESTION,
        ]
        # Oldest first: this is a story, and a story told backwards is a list.
        assert case.prior_outreach[0].day <= case.prior_outreach[1].day
        assert all(step.title for step in case.prior_outreach)
        # The day-one nudge has passed its response window and the clock recorded silence;
        # day two's suggestion is still open. `no_response` is silence the system wrote down, not
        # a reply the person gave -- `None` is "nothing recorded at all", and the two are
        # different states the card must not flatten.
        assert [step.outcome for step in case.prior_outreach] == ["no_response", None]
    finally:
        repository.close()


def test_why_human_names_the_lighter_steps_that_were_tried_and_unanswered() -> None:
    repository = _repo()
    try:
        for index in range(3):
            repository.advance("activity_declines", event_id=f"why-{index}")

        case = repository.list_cases()[0]

        # Recorded silence is not an answer. One of these two carries `no_response` (the response
        # clock closed it), and reading that as engagement would tell a coordinator the person
        # replied to something they never touched.
        assert any(step.outcome == "no_response" for step in case.prior_outreach)
        assert "2 lighter steps" in case.why_human
        assert "neither was answered" in case.why_human
        # Deterministic and gate-derived: the sentence leads with which rung stopped the ladder,
        # not with a paraphrase of the numbers.
        assert case.why_human.startswith("Activity has stayed far enough below")
        assert "that Care+ stopped and asked a person." in case.why_human
        assert "ladder" not in case.why_human
        assert case.recommendation == (
            "Check what you know about them, then decide whether to check in."
        )
    finally:
        repository.close()


def test_why_human_says_so_when_the_senior_did_answer() -> None:
    repository = _repo()
    try:
        first = repository.advance("activity_declines", event_id="answered-0")
        assert first.created_intervention is not None
        repository.record_outcome(
            first.created_intervention.intervention_id, OutcomeKind.ACCEPTED, "senior"
        )
        for index in range(1, 4):
            repository.advance("activity_declines", event_id=f"answered-{index}")

        case = repository.list_cases()[0]

        assert any(step.outcome == OutcomeKind.ACCEPTED.value for step in case.prior_outreach)
        assert "was answered, and the change continued" in case.why_human
        assert "none was answered" not in case.why_human
    finally:
        repository.close()


def test_why_human_is_honest_when_nothing_lighter_was_ever_tried() -> None:
    """The steep path: a change severe and persistent enough to reach the review rung while the
    contact cap, a cooldown or a run of uninterpretable days meant nothing lighter was ever sent.
    Claiming "lighter steps were tried" there would be a fabricated fact, so the template has a
    branch for it -- exercised directly, because `_why_human` is a pure function and driving a
    fixture into this shape would test the fixture rather than the branch."""
    sentence = _why_human(PolicyGate.SEVERITY_PERSISTENCE, [])

    assert "Nothing lighter was tried first" in sentence
    assert "lighter steps were tried" not in sentence


def test_why_human_says_nothing_it_cannot_support_about_an_unrecognised_gate() -> None:
    """A gate with no template clause contributes no clause, rather than a plausible-sounding
    default. If a future rung starts opening cases, the sentence gets narrower, not wrong."""
    sentence = _why_human(PolicyGate.CONTACT_CAP, [])

    assert sentence == (
        "Nothing lighter was tried first: the change crossed the review threshold before any "
        "smaller step was permitted."
    )
