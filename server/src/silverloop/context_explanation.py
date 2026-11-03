"""What a recorded answer to the quiet-day question means for the decision ladder.

`context_question.py` decides whether the question is worth asking. This module decides what the
answer is worth once given, and it is deliberately the only place that knows: one pure lookup, in
the shape `consent_scopes.py` established, so a future change to what an answer means touches this
function and not the ladder that reads it.

Why this module exists at all
-----------------------------
Until it did, a recorded answer changed nothing. `ContextQuestionAnswerRow` was written, read once
as an existence check (`asked_recently`, so the question is not asked twice) and read again for
display -- so "I'm away" and "I don't feel like going out" were indistinguishable to
`policy.decide`. The question's own `asked_because` string already claimed a nudge was permitted
because there was "no rain, prior note, or other explanation on record", which was not true of an
answer the person had already given. This module makes it true.

Two rules the ladder relies on
------------------------------
**An explanation expires.** Every answer that explains anything explains it for a bounded number of
*simulated* days, counted from the day the person gave it. Wall-clock time cannot be used here:
`_weekly_contact_count` once counted a seven-day window against `utcnow()`, and a demo advancing
ten simulated days in one wall-clock minute suppressed a contact a simulated week later. The window
below is measured in the person's own calendar for exactly that reason, which is why
`ContextQuestionAnswerRow` carries `answered_on_day` alongside its wall-clock `answered_at` --
the same split, and the same justification, as `BaselineConfirmationRow.decided_on_day`.

**An explanation can never reach the escalation rung.** `EXPLANATION_MAX_SUSTAINED_DAYS` is 3, and
`policy.decide`'s coordinator-review rung requires `sustained_low_days >= 3`, so the two conditions
are disjoint by construction -- the same trick that stops the rain gate's `< 2` bound from ever
blocking it. The person this product should worry about most is the one who answers "I'm resting"
every day for a week, and a system that can be talked out of putting that situation in front of a
human by the person it is worried about has the one failure that review cannot recover. So a stated
explanation may defer a nudge or a suggestion, and may never defer a human.

Two of the five answers deliberately explain nothing
----------------------------------------------------
`not_feeling_it` is absent from the window table because not wanting to go out may *be* the signal
rather than an account of it -- it is a preference report, and `context_question.memory_from_answer`
already routes it to the one place that may act on it. `prefer_not_to_say` is absent because a
question described as optional must be answerable with no consequence, and that has to be true of
the decision as well as the wording. An answer set where every option conveniently confirms nothing
is wrong is not listening; it is looking for permission to stop.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# How many simulated days each answer keeps explaining a quieter-than-usual reading, counting the
# day the answer was given as the first. Values absent from this mapping explain nothing at all,
# which is a decision rather than an omission -- see the module docstring.
#
# The windows are deliberately short and fixed. Asking "away until when?" is a second question, and
# the burden of being asked twice costs more than the precision buys: a window that expires too
# early resumes ordinary behaviour, which is the safe direction to be wrong in.
# A note on what a one-day window can and cannot do, because it is not obvious and a test found
# it: the question is only ever raised *by* a decision, so an answer always arrives after the day
# it describes has already been decided, and `advance()` never re-decides a decided day (see the
# repository's decision-evidence discipline). A window of exactly one day therefore explains only a
# day whose decision is already recorded, and can never change an outcome. Such an answer is still
# recorded, still shown in the world model, and still stops the question being re-asked -- its value
# is evidential rather than decisional, and that is the honest description of it.
_EXPLANATION_WINDOW_DAYS: dict[str, int] = {
    # Being away from home explains a changed routine completely, and rarely for a single day.
    "away": 3,
    # Two days, not one. Someone who says they are resting today is plausibly still quieter
    # tomorrow, and one extra day of patience before nudging is exactly the least intrusive reading
    # of what they said. A rest *week* is precisely what must still reach a human, which
    # `EXPLANATION_MAX_SUSTAINED_DAYS` guarantees rather than this number.
    "resting": 2,
    # One day, and therefore evidential only -- see the note above. Deliberate: "I had other plans"
    # is past tense about a specific day and makes no claim about tomorrow, so inflating it to two
    # days to give it a decisional effect would be inventing a statement the person did not make.
    "other_plans": 1,
}

# What the ladder records when each explanation applies. Kept beside the windows so the rationale
# and the rule can never drift apart, and phrased as a report of what the person said rather than
# as a conclusion the system reached on its own.
_EXPLANATION_RATIONALE: dict[str, str] = {
    "away": "This person has said they are away from home.",
    "other_plans": "This person has said they had other plans.",
    "resting": "This person has said they are resting.",
}

# Above this many sustained low days a stated explanation stops applying, whatever it was.
# Disjoint from `policy.decide`'s coordinator-review threshold by construction; see the module
# docstring, and `test_context_explanation.py` for the assertion that keeps it that way.
EXPLANATION_MAX_SUSTAINED_DAYS = 3


@dataclass(frozen=True)
class StatedExplanation:
    """One answer that is still explaining the day being decided.

    Carries its own dates so the ladder can record when the explanation was given and when it runs
    out, rather than asserting that a day is explained without saying on what authority.
    """

    value: str
    rationale: str
    stated_on: date
    explains_through: date


def explanation_window_days(value: str) -> int | None:
    """How many simulated days `value` explains, or `None` when it explains nothing."""
    return _EXPLANATION_WINDOW_DAYS.get(value)


def explanation_for(value: str, *, stated_on: date, day: date) -> StatedExplanation | None:
    """The explanation `value` provides for `day`, or `None`.

    Returns `None` for an answer that explains nothing, for a day before the answer was given, and
    for a day past the window. Pure and total over its inputs: no session, no clock, no settings.
    """
    window = explanation_window_days(value)
    if window is None:
        return None
    if day < stated_on:
        return None
    explains_through = stated_on + timedelta(days=window - 1)
    if day > explains_through:
        return None
    return StatedExplanation(
        value=value,
        rationale=_EXPLANATION_RATIONALE[value],
        stated_on=stated_on,
        explains_through=explains_through,
    )


def active_explanation(
    answers: list[tuple[str, date | None]], *, day: date
) -> StatedExplanation | None:
    """The explanation in force on `day`, given every answer this person has recorded.

    `answers` is `(value, stated_on)` pairs in any order. A `None` `stated_on` is a row written
    before `answered_on_day` existed: it is skipped rather than guessed at, because inventing a
    scenario day for it would put a fabricated date in the audit trail.

    When several answers are still in force the most recently stated one wins -- the person's
    latest account of their own week is the better one, and a longer-running earlier answer should
    not outrank it.
    """
    active = [
        explanation
        for value, stated_on in answers
        if stated_on is not None
        and (explanation := explanation_for(value, stated_on=stated_on, day=day)) is not None
    ]
    if not active:
        return None
    return max(active, key=lambda explanation: explanation.stated_on)
