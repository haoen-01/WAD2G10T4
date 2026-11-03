"""The one other question worth asking: "is this your new normal?"

`analytics.BASELINE_DRIFT_FLOOR` stops a declining person from vanishing into their own rolling
median (see that constant's own comment). What it cannot do on its own is tell the difference
between someone still declining and someone whose life has genuinely and permanently settled at a
quieter pace -- both look identical to the clamp, which is exactly why the clamp must not decide
that difference by itself. This module decides only whether it is worth *asking* the person; the
answer, and the durable re-anchoring it may cause, live in `sql_repository.py` and
`BaselineConfirmationRow`.

Follows `context_question.py`'s shape deliberately: a question is computed fresh from `PersonState`
every time rather than stored ahead of it (see `ContextQuestionAnswerRow`'s own docstring for why),
and restraint is the whole feature -- this fires only when the clamp has been bound for a long,
deliberately chosen stretch (`CANDIDATE_BASELINE_STREAK_DAYS`), and it is silent for a cooldown
after the person has already said no once (`DECLINE_COOLDOWN_DAYS`). Nothing here re-anchors
anything; it only decides whether to ask.
"""

from __future__ import annotations

from datetime import date

from silverloop.analytics import BASELINE_DRIFT_FLOOR, CANDIDATE_BASELINE_STREAK_DAYS
from silverloop.models import (
    BaselineConfirmationDecision,
    BaselineConfirmationQuestion,
    PersonState,
)

QUESTION_ID = "candidate_baseline_check_in"

# How long Care+ stays quiet after the person has said "no, keep comparing me to before".
#
# A month, deliberately: this is a heavier question than the daily quiet-day check-in
# (`context_question.ACCEPTED_OUTREACH_COOLDOWN_DAYS`-style cooldowns measure single-digit days
# because outreach fatigue is a weekly concern), and a "no" here is a considered answer about how
# someone sees their own life, not a declined suggestion. Asking again next week would read as not
# having listened. Not asking again *at all* would be worse in the other direction: a further
# decline six months later deserves a fresh chance to be named, not permanent silence because of
# one earlier "no". Thirty days is long enough to show the "no" was heard and short enough that a
# person is not locked out of ever revisiting it within a single season.
DECLINE_COOLDOWN_DAYS = 30


def question_for(
    state: PersonState,
    *,
    clamp_streak_days: int,
    last_decision: BaselineConfirmationDecision | None,
    last_decided_on: date | None,
) -> BaselineConfirmationQuestion | None:
    """A single question, or `None` when nothing is worth asking yet.

    `clamp_streak_days` and `last_decision`/`last_decided_on` are read off already-computed state
    (`analytics.clamp_streak_days` and the most recent `BaselineConfirmationRow` for this run)
    rather than recomputed here, so this function stays a pure decision over facts its caller
    already gathered -- the same shape `context_question.question_for` uses.
    """
    if not state.consent_active:
        # Suppressed for the same reason `context_question.py` never asks anything while consent
        # is off: nothing is being sent or re-anchored regardless of the answer, so there is
        # nothing for a question to change.
        return None

    if state.baseline.reference_steps <= 0:
        # No anchored reference yet; there is nothing to compare "my life now" against.
        return None

    if not state.signal.quality.safe_to_interpret:
        # An unreliable reading cannot be trusted to describe today, let alone the last month.
        return None

    if clamp_streak_days < CANDIDATE_BASELINE_STREAK_DAYS:
        return None

    if (
        last_decision is BaselineConfirmationDecision.DECLINE
        and last_decided_on is not None
        and (state.current_day - last_decided_on).days < DECLINE_COOLDOWN_DAYS
    ):
        return None

    return BaselineConfirmationQuestion(
        question_id=QUESTION_ID,
        question=(
            "For some time now, your day-to-day activity has settled into a steadier, quieter "
            "routine than when Care+ first started keeping track. Would you like Care+ "
            "to treat this as your normal from now on?"
        ),
        asked_because=(
            f"The rolling median has sat below {round(BASELINE_DRIFT_FLOOR * 100)}% of the "
            f"anchored reference for {clamp_streak_days} consecutive days, which is long enough "
            "that this plausibly describes a settled change rather than a passing decline."
        ),
        streak_days=clamp_streak_days,
    )
