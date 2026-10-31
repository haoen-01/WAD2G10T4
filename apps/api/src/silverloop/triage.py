"""Who a caregiver should follow up with first, and what to take note of when they do.

A deterministic reading of decisions `policy.decide` has already made -- never a second policy.
Nothing here writes, sends, schedules or changes a decision; it orders people on a caregiver's
screen and says, in plain words, why.

The rule that keeps this safe is a one-way ceiling. The two follow-up windows that suggest a person
contacts a senior are reachable only from a decision the policy ladder already returned:

- `REACH_OUT_TODAY` only while a review case the ladder opened on `COORDINATOR_REVIEW` is still
  unresolved, and today's rung is not one that holds contact back (rain, the person's own
  explanation, a baseline too small to read, the weekly cap, the recent-uptake cooldown). Once a
  person has answered the case, the board does not ask again. One stated exception: an open case
  stays here on a day whose tracker reading cannot be interpreted, because the case rests on
  earlier readable days and an unworn tracker does not retract it.
- `CHECK_IN_WITHIN_48H` only when the ladder itself permitted outreach (`PROGRAMME_SUGGESTION`, or
  `GENTLE_NUDGE` whose recent messages did not land).

An acknowledged case -- a coordinator chose to keep monitoring -- is not asked about again until it
is due back (`case_due_back`); until then it reads `KEEP_AN_EYE_ON`, never a contact window.

Each row also carries its Care Team group (`CareTeamGroup`), placed here from the same facts as the
window so a client never re-derives workflow placement and the two can never contradict each other.

Every gate that stops the ladder short of outreach -- consent, data quality, confidence, the
person's own explanation, rain, a baseline too small to read, the weekly contact cap and the
accepted-outreach cooldown -- therefore also stops this module short of suggesting contact. The
more sensitive, research-informed step thresholds below only ever move someone onto
`KEEP_AN_EYE_ON` (look again, contact no one) and break ties inside a window. They can never lift a
person into a window the policy did not permit. `tests/test_triage.py` asserts that ceiling for
every gate rather than trusting this note.

What the output deliberately carries no more of than the roster does: no step count, no
percentage about a person, no score. Changes are described in bands ("more than 40% below their
usual"), and the reading order is a position in a list, not a number about anyone's body.

Not a medical or emergency tool. It reads daily activity only, makes no health judgement, and says
so on every board.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from silverloop.models import (
    CareNote,
    CareNoteKind,
    CarePriorityBoard,
    CarePriorityRow,
    CareTeamGroup,
    CareTeamGroupReason,
    CaseStatus,
    Decision,
    FollowUpWindow,
    PersonState,
    PolicyGate,
    PriorityHold,
    ThresholdReference,
)
from silverloop.quality import MINIMUM_WEAR_HOURS

DEFAULT_TOP_K = 3
MAX_TOP_K = 10

# ── Sensitive watch thresholds ────────────────────────────────────────────────────────────────
#
# Set as low as the evidence allows, and used only for `KEEP_AN_EYE_ON` and ordering.
#
# A dip must clear BOTH a relative and an absolute floor. The relative floor (10% below the
# person's own usual) is half the policy's lowest outreach rung. The absolute floor is the lower
# bound of the minimal important difference in daily steps reported by Demeyer et al. (2016):
# 600-1,100 steps/day. Below that, a change is within what clinical studies treat as noise, so
# flagging it would only train a caregiver to ignore the list. The absolute floor is also what
# keeps a tiny baseline from tripping this, matching the policy's own small-baseline gate.
EARLY_DIP_PERCENT = 10.0
MEANINGFUL_STEP_CHANGE = 600
# Against the anchored reference (the person's earliest settled routine) rather than the rolling
# baseline, which absorbs a slow decline. Same size as the policy's gentle-nudge rung.
DRIFT_PERCENT = 20.0

# Daily step levels for older adults, used only to order people inside a window and to add a note.
# Tudor-Locke & Bassett (2004): under 5,000 steps/day is the "sedentary" band. Tudor-Locke et al.
# (2011): 3,500-5,500 steps/day for older adults living with a chronic illness or disability, and
# 7,000-10,000 for healthy older adults.
SEDENTARY_STEPS = 5_000
LOW_RESERVE_STEPS = 3_500

# The severity bands a note may use. The person's own figure is never shown.
WELL_BELOW_PERCENT = 40.0
NOTICEABLY_BELOW_PERCENT = 25.0

BOUNDARY_NOTE = (
    "Not an emergency or medical service. These priorities come from daily activity patterns "
    "only, and Care+ cannot judge anyone's health or safety. If you are worried about "
    "someone's immediate safety, call 995."
)

_WINDOW_ORDER: dict[FollowUpWindow, int] = {
    FollowUpWindow.REACH_OUT_TODAY: 0,
    FollowUpWindow.CHECK_IN_WITHIN_48H: 1,
    FollowUpWindow.KEEP_AN_EYE_ON: 2,
    FollowUpWindow.NO_ACTION_NEEDED: 3,
}
_HOLD_ORDER: dict[PriorityHold | None, int] = {
    None: 0,
    PriorityHold.DATA_NOT_READABLE: 1,
    PriorityHold.CONSENT_WITHDRAWN: 2,
}
_CONTACT_WINDOWS = frozenset({FollowUpWindow.REACH_OUT_TODAY, FollowUpWindow.CHECK_IN_WITHIN_48H})

# Gates after which the ladder does not interpret today's reading at all.
_UNREADABLE_GATES = frozenset({PolicyGate.DATA_QUALITY, PolicyGate.CONFIDENCE})
# Gates that stop the ladder *because contact would be wrong today*, not because the reading says
# nothing. These cap even an open review case below the contact windows. The unreadable gates are
# not among them: a case opened on earlier readable days is not retracted by a tracker left off.
_OUTREACH_HOLDING_GATES = frozenset(
    {
        PolicyGate.STATED_EXPLANATION,
        PolicyGate.RAIN_CONTEXT,
        PolicyGate.SMALL_BASELINE,
        PolicyGate.CONTACT_CAP,
        PolicyGate.ACCEPTED_COOLDOWN,
    }
)
_APPROACH: dict[FollowUpWindow, str] = {
    FollowUpWindow.REACH_OUT_TODAY: (
        "Call or visit today. Ask in your own words how their week has been and whether anything "
        "in their routine has changed, and listen for what would help. Record what you decide on "
        "their review case."
    ),
    FollowUpWindow.CHECK_IN_WITHIN_48H: (
        "A friendly check-in within the next two days. Ask what would make getting out easier "
        "this week, rather than repeating Care+'s suggestion."
    ),
    FollowUpWindow.KEEP_AN_EYE_ON: "No contact needed yet. Look again after their next reading.",
    FollowUpWindow.NO_ACTION_NEEDED: "Nothing to do.",
}
_HOLD_APPROACH: dict[PriorityHold, str] = {
    PriorityHold.CONSENT_WITHDRAWN: (
        "Respect their choice. Care+ sends nothing and suggests no follow-up while consent is "
        "withdrawn."
    ),
    PriorityHold.DATA_NOT_READABLE: (
        "Nothing to act on from the tracker. If you are already in touch, a reminder to wear or "
        "charge it can help."
    ),
}


@dataclass(frozen=True)
class CareContext:
    """What the repository knows about a person beyond `PersonState`. All counts, no content."""

    tracker_not_synced_days: int = 0
    open_case_id: str | None = None
    open_case_status: CaseStatus | None = None
    days_in_review: int | None = None
    review_by_day: date | None = None
    case_evidence_id: str | None = None
    # Care+ outreach in the contact-cap window, by how it ended. Counted from the latest
    # outcome per intervention, so an amended decline is one decline.
    recent_no_reply: int = 0
    recent_declined: int = 0
    # The latest last-day-of-waiting across outreach offers still open, or `None` when nothing is
    # waiting for a reply.
    awaiting_reply_until: date | None = None
    # They took a suggestion up inside the policy's accepted-outreach cooldown. Carried separately
    # because the read-time ladder checks the weekly cap first, so a same-day acceptance of the
    # day's own suggestion reads as `CONTACT_CAP` and the cooldown never shows as the gate.
    accepted_recently: bool = False
    # A proposed review-timing change for this person is waiting for a coordinator's decision.
    review_timing_proposal_waiting: bool = False


@dataclass(frozen=True)
class _Triage:
    window: FollowUpWindow
    hold: PriorityHold | None
    headline: str
    notes: list[CareNote] = field(default_factory=list)


def case_due_back(review_by_day: date | None, as_of: date) -> bool:
    """Whether an unresolved case has reached the day Care+ said it would come back to the
    queue. The one rule for "due back" -- used for the Care Team group, the headline, the case note
    and the reading order alike.

    A case with no recorded review day is *not* due back. Such a case predates the case clock, and
    the repository reports that day as "not recorded" rather than back-filling it; treating it as
    due would invent a checkpoint the simulation never set. An open case needs judgement whatever
    its day, so for grouping this only decides where an acknowledged one sits -- and that case stays
    on the board, in the case queue, and resolvable.
    """
    return review_by_day is not None and review_by_day <= as_of


def _plural(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def _severity(state: PersonState) -> float:
    return max(0.0, -state.signal.delta_percent)


def _reference_severity(state: PersonState) -> float:
    return max(0.0, -state.signal.reference_delta_percent)


def _step_drop(state: PersonState) -> float:
    return max(0.0, state.signal.baseline_median_steps - state.signal.current_steps)


def _early_dip(state: PersonState) -> bool:
    return _severity(state) >= EARLY_DIP_PERCENT and _step_drop(state) >= MEANINGFUL_STEP_CHANGE


def _drift(state: PersonState) -> bool:
    reference = state.baseline.reference_steps
    # Zero means no anchored reference has settled yet, not a reference of zero steps.
    if reference <= 0:
        return False
    return (
        _reference_severity(state) >= DRIFT_PERCENT
        and reference - state.signal.current_steps >= MEANINGFUL_STEP_CHANGE
    )


def _sensitive_tripwire(state: PersonState) -> bool:
    """Whether the watch list's low thresholds fire. Never consulted for a contact window.

    A day the person disputed is treated like any other reading here. Skipping it would print
    "within their usual range" about a day that was not, and the difference between that row and
    its notes would tell the coordinator the person had disputed it.
    """
    return state.signal.sustained_low_days >= 2 or _early_dip(state) or _drift(state)


def _change_note(state: PersonState) -> CareNote | None:
    severity = _severity(state)
    if severity >= WELL_BELOW_PERCENT:
        text = "Activity is well below their own usual level (more than 40% lower)."
    elif severity >= NOTICEABLY_BELOW_PERCENT:
        text = "Activity is noticeably below their own usual level (more than 25% lower)."
    elif _early_dip(state):
        text = (
            "Activity has dipped slightly below their own usual level: at least 10% lower, and "
            "by more than about 600 steps a day, the smallest change used here as meaningful."
        )
    elif _drift(state):
        text = (
            "Activity is lower than when Care+ first learned their routine. This is a slow "
            "drift that the day-to-day comparison can miss."
        )
    else:
        return None
    return CareNote(kind=CareNoteKind.CHANGE, text=text)


def _level_note(state: PersonState) -> CareNote | None:
    steps = state.signal.current_steps
    if steps < LOW_RESERVE_STEPS:
        text = (
            "Their latest daily activity is under 3,500 steps, at the low end of the daily "
            "activity levels described for older adults. A smaller change matters more here."
        )
    elif steps < SEDENTARY_STEPS:
        text = (
            "Their latest daily activity is under 5,000 steps, the level activity research "
            "describes as sedentary for older adults."
        )
    else:
        return None
    return CareNote(kind=CareNoteKind.ACTIVITY_LEVEL, text=text)


def _level_band(state: PersonState) -> int:
    steps = state.signal.current_steps
    if steps < LOW_RESERVE_STEPS:
        return 0
    if steps < SEDENTARY_STEPS:
        return 1
    return 2


def _severity_band(state: PersonState) -> int:
    worst = max(_severity(state), _reference_severity(state))
    if worst >= WELL_BELOW_PERCENT:
        return 3
    if worst >= NOTICEABLY_BELOW_PERCENT:
        return 2
    if _early_dip(state) or _drift(state):
        return 1
    return 0


def _outreach_notes(context: CareContext) -> list[CareNote]:
    notes: list[CareNote] = []
    if context.recent_no_reply:
        notes.append(
            CareNote(
                kind=CareNoteKind.OUTREACH_HISTORY,
                text=(
                    f"{_plural(context.recent_no_reply, 'recent Care+ message')} got no "
                    "reply. A familiar voice may reach them where a message did not."
                ),
            )
        )
    if context.recent_declined:
        notes.append(
            CareNote(
                kind=CareNoteKind.OUTREACH_HISTORY,
                text=(
                    f"They declined {_plural(context.recent_declined, 'recent suggestion')}. Ask "
                    "what would suit them better rather than offering the same thing again."
                ),
            )
        )
    if context.awaiting_reply_until is not None:
        notes.append(
            CareNote(
                kind=CareNoteKind.OUTREACH_HISTORY,
                text=(
                    "A Care+ message is still waiting for their reply, so avoid asking about "
                    "the same thing twice."
                ),
            )
        )
    return notes


def _context_notes(state: PersonState) -> list[CareNote]:
    notes: list[CareNote] = []
    if state.signal.context.rainy:
        notes.append(
            CareNote(
                kind=CareNoteKind.CONTEXT,
                text="It rained on their latest day, which can explain a quieter reading.",
            )
        )
    if state.signal.context.holiday:
        notes.append(
            CareNote(
                kind=CareNoteKind.CONTEXT,
                text="Their latest day was a public holiday, when routines often change.",
            )
        )
    # Nothing about what the person told Care+ -- not a stated explanation, not a disputed
    # day, not even that they said anything. Those stay on the senior's own surface.
    return notes


def _case_notes(context: CareContext, as_of: date) -> list[CareNote]:
    if context.open_case_id is None:
        return []
    notes: list[CareNote] = []
    status = (
        "waiting for a first review"
        if context.open_case_status == CaseStatus.OPEN
        else "acknowledged but not yet resolved"
    )
    if context.days_in_review is not None:
        status += f", on day {context.days_in_review} of review"
    notes.append(CareNote(kind=CareNoteKind.CASE, text=f"Their review case is {status}."))
    if case_due_back(context.review_by_day, as_of):
        notes.append(
            CareNote(
                kind=CareNoteKind.CASE,
                text=(
                    "The case has reached the day Care+ said it would come back to the queue "
                    f"({context.review_by_day.isoformat()})."
                ),
            )
        )
    return notes


def _tracker_note(context: CareContext) -> CareNote | None:
    if context.tracker_not_synced_days <= 0:
        return None
    return CareNote(
        kind=CareNoteKind.TRACKER,
        text=(
            "The tracker may not have synced on "
            f"{_plural(context.tracker_not_synced_days, 'day')} of the last 7. Missing readings "
            "say nothing about how they are."
        ),
    )


def _hold_notes(gate: PolicyGate) -> list[CareNote]:
    """The note that explains a contact hold. System facts only. Rain already has its context note,
    and a stated explanation gets no note at all."""
    if gate == PolicyGate.CONTACT_CAP:
        text = (
            "Care+ has already contacted them twice this week. More contact risks becoming "
            "pressure."
        )
    elif gate == PolicyGate.ACCEPTED_COOLDOWN:
        text = (
            "They are acting on a recent suggestion. Another nudge now would feel like supervision."
        )
    else:
        return []
    return [CareNote(kind=CareNoteKind.SPACE, text=text)]


def _classify(state: PersonState, context: CareContext) -> _Triage:
    gate = state.decided_by_gate
    decision = state.last_decision

    # Consent first, exactly as the ladder orders it. Withdrawal also closes any open case, so a
    # stale case id can never reach a contact window past this line.
    if not state.consent_active or gate == PolicyGate.CONSENT:
        return _Triage(
            FollowUpWindow.NO_ACTION_NEEDED,
            PriorityHold.CONSENT_WITHDRAWN,
            "Consent withdrawn. No proactive outreach.",
        )

    # An unresolved case is a human-review item the ladder already opened: `_create_case` is the
    # only thing that opens one, and only on `COORDINATOR_REVIEW`. It stays at the top even on a
    # day whose reading cannot be interpreted, because nothing about today is being read to put it
    # there.
    if context.open_case_id is not None:
        if context.open_case_status == CaseStatus.ACKNOWLEDGED and not case_due_back(
            context.review_by_day, state.current_day
        ):
            # A coordinator has answered the case with "keep monitoring". Until it is due back,
            # asking them to reach out would override that decision, exactly as for a resolved
            # case; the case is still theirs, so it stays on the board above plain watching.
            return _Triage(
                FollowUpWindow.KEEP_AN_EYE_ON,
                None,
                (
                    "A coordinator has reviewed their case and Care+ is monitoring until it "
                    "comes back to the queue."
                    if context.review_by_day is not None
                    else "A coordinator has reviewed their case and Care+ is monitoring "
                    "until it is resolved."
                ),
                _hold_notes(gate),
            )
        if gate in _OUTREACH_HOLDING_GATES:
            # The case still needs a person, but today's rung holds contact back. Reviewing the
            # case is still work for the caregiver; contacting the senior today is not.
            return _Triage(
                FollowUpWindow.KEEP_AN_EYE_ON,
                None,
                "Their review case is still open, but Care+'s safety rules are holding "
                "outreach back today. Review the case before contacting them.",
                _hold_notes(gate),
            )
        overdue = case_due_back(context.review_by_day, state.current_day)
        # The decline headlines only when today's own decision is the review rung; any lower rung
        # means today's reading is not the sustained decline the case was opened on.
        if decision != Decision.COORDINATOR_REVIEW:
            headline = (
                "Their review case is still waiting for a person. Today's reading neither adds to "
                "it nor closes it."
            )
        elif overdue:
            headline = (
                "Their review case has come back to the queue, and activity is still below their "
                "usual."
            )
        else:
            headline = "Activity has stayed well below their usual for several days."
        return _Triage(FollowUpWindow.REACH_OUT_TODAY, None, headline)

    # The ladder reached review on this reading, but no case is waiting, so a person has already
    # answered it. A continuing decline opens a fresh case on the next reading; until then, asking
    # the caregiver to reach out again would override the human decision that closed it.
    if decision == Decision.COORDINATOR_REVIEW:
        return _Triage(
            FollowUpWindow.KEEP_AN_EYE_ON,
            None,
            "Activity is still well below their usual, but their review case has been answered.",
            [
                CareNote(
                    kind=CareNoteKind.CASE,
                    text="No review case is waiting. If the decline continues, Care+ opens a "
                    "new one.",
                )
            ],
        )

    if gate in _UNREADABLE_GATES:
        return _Triage(
            FollowUpWindow.NO_ACTION_NEEDED,
            PriorityHold.DATA_NOT_READABLE,
            "The latest tracker reading is too thin to interpret. This says nothing about how "
            "they are.",
        )

    if context.accepted_recently and decision in {
        Decision.GENTLE_NUDGE,
        Decision.PROGRAMME_SUGGESTION,
    }:
        return _Triage(
            FollowUpWindow.KEEP_AN_EYE_ON,
            None,
            "They took up a suggestion in the last few days. Give them space to act on it.",
            _hold_notes(PolicyGate.ACCEPTED_COOLDOWN),
        )

    if decision == Decision.PROGRAMME_SUGGESTION:
        return _Triage(
            FollowUpWindow.CHECK_IN_WITHIN_48H,
            None,
            "Activity has been noticeably below their usual for at least two days.",
        )

    missed = context.recent_no_reply + context.recent_declined
    if decision == Decision.GENTLE_NUDGE and missed:
        return _Triage(
            FollowUpWindow.CHECK_IN_WITHIN_48H,
            None,
            "Activity is below their usual, and Care+'s recent outreach has not landed.",
        )
    if decision == Decision.GENTLE_NUDGE:
        return _Triage(
            FollowUpWindow.KEEP_AN_EYE_ON,
            None,
            "Activity is a little below their usual. Care+ is sending a gentle nudge, so "
            "nothing is needed from you yet.",
        )

    if gate == PolicyGate.CONTACT_CAP:
        return _Triage(
            FollowUpWindow.KEEP_AN_EYE_ON,
            None,
            "Activity is below their usual, but they have already heard from Care+ enough "
            "this week.",
            _hold_notes(gate),
        )
    if gate == PolicyGate.ACCEPTED_COOLDOWN:
        return _Triage(
            FollowUpWindow.KEEP_AN_EYE_ON,
            None,
            "They took up a suggestion in the last few days. Give them space to act on it.",
            _hold_notes(gate),
        )

    if _sensitive_tripwire(state):
        if gate == PolicyGate.RAIN_CONTEXT:
            headline = "Quieter than usual, but it rained. Care+ is watching before anyone acts."
        elif gate == PolicyGate.STATED_EXPLANATION:
            # Deliberately indistinguishable from any other hold: "they explained why" would tell
            # the coordinator what the senior told Care+.
            headline = "Quieter than usual. Care+ is watching before anyone acts."
        elif gate == PolicyGate.SMALL_BASELINE:
            headline = "Quieter than usual, though the change is within measurement noise."
        elif not _early_dip(state) and _drift(state):
            headline = "Gradually lower than when Care+ first learned their routine."
        else:
            headline = "A small dip below their usual, not yet enough to prompt any outreach."
        return _Triage(FollowUpWindow.KEEP_AN_EYE_ON, None, headline)

    return _Triage(FollowUpWindow.NO_ACTION_NEEDED, None, "Activity is within their usual range.")


def _notes_for(state: PersonState, context: CareContext, triage: _Triage) -> list[CareNote]:
    if triage.hold == PriorityHold.CONSENT_WITHDRAWN:
        return []
    notes = list(triage.notes)
    notes.extend(_case_notes(context, state.current_day))
    readable = triage.hold is None and state.decided_by_gate not in _UNREADABLE_GATES
    if readable and triage.window != FollowUpWindow.NO_ACTION_NEEDED:
        if state.signal.sustained_low_days >= 2:
            notes.append(
                CareNote(
                    kind=CareNoteKind.PERSISTENCE,
                    text=(
                        "Below their usual on "
                        f"{_plural(state.signal.sustained_low_days, 'valid-wear day')} in a row."
                    ),
                )
            )
        if change := _change_note(state):
            notes.append(change)
        if level := _level_note(state):
            notes.append(level)
    if triage.window != FollowUpWindow.NO_ACTION_NEEDED or triage.hold is not None:
        notes.extend(_outreach_notes(context))
        notes.extend(_context_notes(state))
    if tracker := _tracker_note(context):
        notes.append(tracker)
    return notes


def _sort_key(state: PersonState, context: CareContext, triage: _Triage) -> tuple[int | str, ...]:
    """Lexicographic, every term a named fact a note can state. Deliberately not a weighted sum:
    a weighted sum is a score, and a score can be argued with only by reading the weights."""
    readable = triage.hold is None and state.decided_by_gate not in _UNREADABLE_GATES
    case_rank = (
        {CaseStatus.OPEN: 0, CaseStatus.ACKNOWLEDGED: 1}.get(context.open_case_status, 2)
        if context.open_case_id
        else 2
    )
    overdue = int(not case_due_back(context.review_by_day, state.current_day))
    return (
        _WINDOW_ORDER[triage.window],
        _HOLD_ORDER[triage.hold],
        case_rank,
        overdue,
        -state.signal.sustained_low_days if readable else 0,
        -_severity_band(state) if readable else 0,
        _level_band(state) if readable else 2,
        -(context.recent_no_reply + context.recent_declined),
        -(context.days_in_review or 0),
        -context.tracker_not_synced_days,
        state.display_name,
        state.person_id,
    )


def _placement(
    state: PersonState, context: CareContext, triage: _Triage
) -> tuple[CareTeamGroup, CareTeamGroupReason]:
    """The Care Team group for one row, in a fixed precedence. Read from the same facts `_classify`
    used, so a row can never read "Care+ is handling" beside a contact window it cannot back.

    1. A hold (consent withdrawn, tracker unclear) needs no attention. Withdrawal closes any case,
       and `_classify` sets "tracker unclear" only with no unresolved case, so none hides here.
    2. An open case needs judgement. An acknowledged one needs judgement once due back, and until
       then Care+ is monitoring (its window is `KEEP_AN_EYE_ON`, never a contact window).
    3. With no unresolved case, an outreach offer still waiting for a reply is waiting for the
       senior.
    4. Otherwise the follow-up window decides: watching is Care+'s to handle, a suggested
       check-in needs judgement (it asks a person to check in within two days, which Care+
       cannot do for them), and nothing to do is nothing to do.
    """
    if triage.hold == PriorityHold.CONSENT_WITHDRAWN:
        return CareTeamGroup.NO_ATTENTION_NEEDED, CareTeamGroupReason.CONSENT_WITHDRAWN
    if triage.hold == PriorityHold.DATA_NOT_READABLE:
        return CareTeamGroup.NO_ATTENTION_NEEDED, CareTeamGroupReason.TRACKER_UNCLEAR
    if context.open_case_id is not None:
        if context.open_case_status != CaseStatus.ACKNOWLEDGED:
            return CareTeamGroup.NEEDS_JUDGEMENT, CareTeamGroupReason.OPEN_CASE
        if case_due_back(context.review_by_day, state.current_day):
            return CareTeamGroup.NEEDS_JUDGEMENT, CareTeamGroupReason.MONITORING_DUE_BACK
        return CareTeamGroup.SILVERLOOP_HANDLING, CareTeamGroupReason.MONITORING_UNTIL_REVIEW_DAY
    if context.awaiting_reply_until is not None:
        return CareTeamGroup.WAITING_FOR_SENIOR, CareTeamGroupReason.AWAITING_REPLY
    if triage.window == FollowUpWindow.NO_ACTION_NEEDED:
        return CareTeamGroup.NO_ATTENTION_NEEDED, CareTeamGroupReason.NOTHING_NEEDED
    if triage.window == FollowUpWindow.KEEP_AN_EYE_ON:
        return CareTeamGroup.SILVERLOOP_HANDLING, CareTeamGroupReason.KEEP_AN_EYE_ON
    # `CHECK_IN_WITHIN_48H`: a person is asked to check in, so it is theirs to judge, not
    # Care+'s. `REACH_OUT_TODAY` needs an unresolved case, handled above.
    return CareTeamGroup.NEEDS_JUDGEMENT, CareTeamGroupReason.CHECK_IN_SUGGESTED


def _evidence_ids(state: PersonState, context: CareContext) -> list[str]:
    ids = [state.signal.quality.evidence_id]
    if context.case_evidence_id:
        ids.append(context.case_evidence_id)
    return ids


THRESHOLD_REFERENCES: tuple[ThresholdReference, ...] = (
    ThresholdReference(
        label="Reach out today",
        rule=(
            "Only while a review case is waiting. Care+'s policy opens one when activity has "
            "stayed below their own usual past their review setting: more than 40% for at least "
            "three valid-wear days, unless a coordinator has approved a change for that person "
            "within fixed bounds, and always at 60% or more for three days."
        ),
        source="Care+ policy ladder",
    ),
    ThresholdReference(
        label="Check in within 48h",
        rule=(
            "Only where the policy already permits outreach: more than 25% below their usual for "
            "two valid-wear days, or a gentle nudge whose recent messages went unanswered or were "
            "declined. Consent, data quality, the weekly contact cap and the recent-uptake "
            "cooldown all still apply."
        ),
        source="Care+ policy ladder",
    ),
    ThresholdReference(
        label="Keep an eye on",
        rule=(
            "At least 10% below their usual and at least 600 steps a day lower, or 20% below their "
            "earliest settled routine, or two low days in a row. These flags never suggest "
            "contact on their own."
        ),
        source=(
            "Demeyer et al., PLoS One 2016: 600 to 1,100 steps a day was the smallest important "
            "change in a study of adults with a long-term lung condition (COPD). Used here only "
            "as a noise floor, not as a clinical threshold for this caseload"
        ),
    ),
    ThresholdReference(
        label="Order within a window",
        rule=(
            "An unreviewed case first, then days in a row below usual, size of the change, lower "
            "daily activity (under 3,500, then under 5,000 steps), and outreach that did not land."
        ),
        source=(
            "Tudor-Locke & Bassett, Sports Med 2004 (under 5,000 steps a day is described as "
            "sedentary); Tudor-Locke et al., IJBNPA 2011 (step-count ranges described for older "
            "adults, from 3,500 to 10,000 a day). Activity levels only, never a health judgement"
        ),
    ),
    ThresholdReference(
        label="Readings left out",
        rule=(
            f"Days with less than {MINIMUM_WEAR_HOURS:g} hours of tracker wear are never "
            "interpreted, so a missing reading is never treated as a quiet day."
        ),
        source="Care+ data-quality gate",
    ),
)


def build_board(
    people: Iterable[tuple[PersonState, CareContext]], *, top_k: int = DEFAULT_TOP_K
) -> CarePriorityBoard:
    top_k = max(1, min(top_k, MAX_TOP_K))
    triaged = [(state, context, _classify(state, context)) for state, context in people]
    triaged.sort(key=lambda item: _sort_key(*item))
    rows: list[CarePriorityRow] = []
    for position, (state, context, triage) in enumerate(triaged, start=1):
        approach = (
            _HOLD_APPROACH[triage.hold] if triage.hold is not None else _APPROACH[triage.window]
        )
        group, reason = _placement(state, context, triage)
        consented = state.consent_active
        rows.append(
            CarePriorityRow(
                position=position,
                person_id=state.person_id,
                display_name=state.display_name,
                follow_up_window=triage.window,
                hold=triage.hold,
                headline=triage.headline,
                suggested_approach=approach,
                take_note=_notes_for(state, context, triage),
                open_case_id=context.open_case_id if consented else None,
                as_of_day=state.current_day,
                evidence_ids=_evidence_ids(state, context),
                care_team_group=group,
                care_team_group_reason=reason,
                # Nothing a withdrawn person's row could act on: their case and offers are closed
                # by the withdrawal, and a review-timing change cannot be approved without consent.
                review_back_on_day=(
                    context.review_by_day if consented and context.open_case_id else None
                ),
                awaiting_reply_until=context.awaiting_reply_until if consented else None,
                review_timing_proposal_waiting=(
                    consented and context.review_timing_proposal_waiting
                ),
            )
        )
    follow_up_first: Sequence[CarePriorityRow] = [
        row for row in rows if row.follow_up_window in _CONTACT_WINDOWS
    ][:top_k]
    return CarePriorityBoard(
        top_k=top_k,
        follow_up_first=list(follow_up_first),
        people=rows,
        boundary_note=BOUNDARY_NOTE,
        thresholds=list(THRESHOLD_REFERENCES),
    )
