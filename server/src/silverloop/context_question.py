"""The one question worth asking (F31-ish: context on the senior side).

`policy.py` already decides, from sensor data alone, whether today is a NO_ACTION, a SUPPRESS, a
COORDINATOR_REVIEW or one of the two outreach rungs (GENTLE_NUDGE / PROGRAMME_SUGGESTION). This
module never re-runs or second-guesses that ladder -- it has no import from `policy.py` and never
will. What it adds is much narrower: given the `PersonState` the ladder already produced, decide
whether it is worth asking the person, in their own words, what a quiet day actually was.

The restraint is the whole feature. Asking whenever the system is merely uncertain turns
Care+ into an interrogation, which is exactly what this audience has too much of already
(coordinators, family, well-meaning apps). So `question_for` returns a question only when an
answer would plausibly change something real, and returns `None` in every other case:

  * the two rungs where nothing depends on today's explanation at all -- NO_ACTION (nothing is
    being sent regardless of why today looks quiet) and SUPPRESS (blocked by consent or the
    contact-fatigue guard, again regardless of why);
  * COORDINATOR_REVIEW, where a human is already looking at the full picture and a scripted
    one-tap question adds noise rather than context;
  * a day the tracker itself cannot be trusted to describe (`quality.safe_to_interpret` is
    `False`) -- the person's answer cannot rescue a reading nothing should be inferred from;
  * a day rain already explains on its own terms, using `policy.py`'s own condition
    (`context.rainy` and fewer than two sustained low days) so this module's idea of "already
    explained" never drifts from the ladder's;
  * a run in which the person has already answered (`asked_recently`) -- asking again would be
    asking the same question twice with different wording. `PersonState.context_note` is the
    fixture persona's biography, not a recorded answer, and it never gates the question: an
    earlier version checked it, and because every demo persona has a biography the question
    could never be asked at all.

What is left -- GENTLE_NUDGE or PROGRAMME_SUGGESTION, with a reliable, unexplained reading -- is
exactly the situation where sending outreach without asking risks being presumptuous: the person
may simply be resting, away, or otherwise fine, and a nudge lands wrong when that is true. Pairing
the (still-sent, still permitted) outreach with a genuine question is the least intrusive way to
find out, rather than guessing either way.

`asked_because` names the specific gap so a reviewer can check the question was earned rather than
merely conversational -- the same discipline `ActivityReason.basis` applies to "why this fits you"
lines, applied here to "why this was asked".
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from silverloop.models import (
    ContextAnswerOption,
    ContextAnswerValue,
    ContextQuestion,
    Decision,
    PersonState,
    PreferenceDimension,
    ProposedMemory,
    SocialPreference,
)

QUESTION_ID = "quiet_day_check_in"

# Rungs where the missing fact would actually change what happens next. Every other rung -- both
# ends of the ladder, NO_ACTION/SUPPRESS at the bottom and COORDINATOR_REVIEW at the top -- is
# fixed regardless of today's explanation; see the module docstring for why each is excluded.
_DECISION_CHANGING_RUNGS = frozenset({Decision.GENTLE_NUDGE, Decision.PROGRAMME_SUGGESTION})

# How few sustained low days still let a same-day rainy forecast count as a full explanation on
# its own. Mirrors `policy.decide`'s own `signal.context.rainy and signal.sustained_low_days < 2`
# check exactly, so "rain already explains it" never means something different here than it does
# on the ladder that actually used it.
_RAIN_EXPLAINS_BELOW_SUSTAINED_DAYS = 2

_OPTIONS = (
    ContextAnswerOption(value=ContextAnswerValue.RESTING, label="I'm resting today"),
    ContextAnswerOption(value=ContextAnswerValue.AWAY, label="I'm away"),
    ContextAnswerOption(value=ContextAnswerValue.OTHER_PLANS, label="I had other plans"),
    ContextAnswerOption(
        value=ContextAnswerValue.NOT_FEELING_IT, label="I don't feel like going out"
    ),
    # A question Care+ describes as optional must be answerable with "no". Without this the
    # only ways past it are to assert a reason that may not be true, or to leave it sitting on the
    # screen -- and a question that cannot be declined is not optional, it is a demand.
    #
    # It is a real recorded answer rather than a client-side dismissal, so the question is asked
    # once and does not return, and the audit shows the person was asked and chose not to say.
    ContextAnswerOption(value=ContextAnswerValue.PREFER_NOT_TO_SAY, label="I would rather not say"),
)

# The closed vocabulary, derived from the options themselves rather than restated, so the set the
# repository validates against can never drift from the set the senior was actually offered.
OPTION_VALUES: frozenset[str] = frozenset(option.value for option in _OPTIONS)

# The one answer option `memory_from_answer` currently reads anything from. Phrased as a mood
# rather than a refusal, but a person's free-text `note` on it can still say more -- see below.
_NOT_FEELING_IT_VALUE = ContextAnswerValue.NOT_FEELING_IT.value

# What has to appear in the free-text `note` for a "don't feel like going out" answer to imply
# anything about company specifically, as opposed to simply not fancying it today. Kept narrow and
# literal on purpose: this proposes a memory, and a proposal grounded in a guess at what someone
# meant would be worse than proposing nothing.
_ALONE_KEYWORDS = ("alone", "by myself", "on my own")


def question_for(state: PersonState, *, asked_recently: bool) -> ContextQuestion | None:
    """A single question, or `None` when nothing an answer could say would change anything.

    See the module docstring for the full list of reasons this returns `None`; every branch below
    corresponds to one of them, in the same order.
    """
    if asked_recently:
        return None

    if state.last_decision not in _DECISION_CHANGING_RUNGS:
        return None

    if not state.signal.quality.safe_to_interpret:
        return None

    if (
        state.signal.context.rainy
        and state.signal.sustained_low_days < _RAIN_EXPLAINS_BELOW_SUSTAINED_DAYS
    ):
        return None

    return ContextQuestion(
        question_id=QUESTION_ID,
        question="Today looks quieter than usual for you. Is everything alright?",
        options=list(_OPTIONS),
        asked_because=(
            f"Activity is about {abs(round(state.signal.delta_percent))}% below what is usual "
            "for this person, with no rain, prior note, or other explanation on record -- that "
            "gap is what decided a nudge was permitted, and an answer could close it either way."
        ),
    )


def memory_from_answer(
    question_id: str, value: str, note: str | None, now: datetime
) -> ProposedMemory | None:
    """A memory this answer might be worth keeping, or `None`.

    Never writes anything -- see `ProposedMemory`'s own docstring for why a belief the person has
    not agreed to is a belief they cannot correct. This only proposes, and only when the person's
    own words, not a guess, ground the proposal: choosing "I don't feel like going out" says
    nothing about company on its own, but adding a note that mentions going out *alone* is the
    person volunteering the reason, and that is the one piece of evidence `PreferenceDimension.
    SOCIAL` may be moved by (see `preferences.py`'s own comment on why a decline alone never
    reaches it).
    """
    if question_id != QUESTION_ID or value != _NOT_FEELING_IT_VALUE:
        return None
    if not note:
        return None

    lowered = note.lower()
    if not any(keyword in lowered for keyword in _ALONE_KEYWORDS):
        return None

    return ProposedMemory(
        proposal_id=f"MEM-{uuid4().hex[:8].upper()}",
        dimension=PreferenceDimension.SOCIAL,
        value=SocialPreference.SOCIAL.value,
        statement="You've mentioned that going out alone isn't something you enjoy.",
        question="Should Care+ remember that, and lean towards suggestions with company?",
        source_text=note,
        created_at=now,
    )
