from __future__ import annotations

from silverloop.models import ActivityCandidate, OutreachDetail, OutreachStep, Programme

# The content behind "Yes, tell me more".
#
# Fixed, reviewed, and deliberately not generated. Everywhere else in the product a model may
# choose wording; here it may not. This is the one screen that asks a person to move their body,
# and it has to read identically on every run, be checkable by a human once, and stay checked.
#
# Written to a hard boundary, which is stated on the screen rather than assumed:
#   * general wellbeing content, never exercise prescription and never therapy
#   * no counts, no targets, no durations to hit, nothing to finish or fail
#   * seated by default, because the people this reaches are the ones moving least
#   * every routine says stop, in the routine, not in a footnote
#
# Two mechanical constraints that are easy to break and expensive to catch. Nothing here may
# contain a percentage or the word "review": the senior shell asserts that its own vocabulary
# stays free of coordinator language and raw figures, and this copy renders inside it.

_STOP_NOTE = "Stop any time. There is nothing to finish and nothing to get right."

_BOUNDARY_NOTE = (
    "This is a general wellbeing suggestion, not medical or exercise advice. Care+ does not "
    "know anything about your health. If something hurts or feels wrong, do not do it, and speak "
    "to your doctor if you are unsure."
)

_SOURCE = "Fixed Care+ content, written for this prototype and unchanged between runs."


_MOVEMENT_CONTENT: dict[str, tuple[str, str, list[str]]] = {
    "gentle_nudge:chair_mobility": (
        "A few minutes, sitting down",
        "All of this is done in a chair. Sit comfortably, with your feet flat on the floor.",
        [
            "Sit back so the chair is taking your weight, and let your shoulders drop.",
            "Roll your shoulders slowly backwards a few times, then forwards a few times.",
            "Lift one heel off the floor, keeping your toes down, then swap. Slow and easy.",
            "Straighten one leg out in front of you, hold it a moment, and lower it. Then the "
            "other leg.",
            "Sit still for a moment at the end and let your breathing settle.",
        ],
    ),
    "gentle_nudge:companion_walk": (
        "A short walk, with company if you would like it",
        "Nothing has been arranged and nobody has been contacted. If someone is around and you "
        "feel like company, this is nicer with them; if not, it works just as well on your own.",
        [
            "Decide whether you would rather go with someone or go on your own. Either is fine.",
            "If you would like company, invite whoever first comes to mind.",
            "Walk as far as feels easy, indoors or outside, whichever suits today.",
            "Turn back whenever you want to. There is nowhere to get to.",
            "Sit down for a minute afterwards and let your breathing settle.",
        ],
    ),
    "gentle_nudge:indoor_walk": (
        "A short walk, indoors",
        "This is just moving about inside your home. Nothing about it needs to look like exercise.",
        [
            "Stand up slowly, and wait a moment before you start walking.",
            "Walk to the far end of your home and back, at whatever pace feels easy.",
            "If there is something to hold on to along the way, use it.",
            "Do that once more if you feel like it. Once is completely fine.",
            "Sit down afterwards and rest for a minute.",
        ],
    ),
}


def _movement_detail(candidate_key: str) -> OutreachDetail | None:
    content = _MOVEMENT_CONTENT.get(candidate_key)
    if content is None:
        return None
    title, intro, steps = content
    return OutreachDetail(
        kind="movement_routine",
        title=title,
        intro=intro,
        steps=[OutreachStep(order=index, text=text) for index, text in enumerate(steps, start=1)],
        stop_note=_STOP_NOTE,
        boundary_note=_BOUNDARY_NOTE,
        source=_SOURCE,
    )


def _programme_detail(programme: Programme, activity: ActivityCandidate | None) -> OutreachDetail:
    return OutreachDetail(
        kind="programme_details",
        title=programme.name,
        intro=(
            "Nothing has been booked and nobody has been told you looked."
            if activity is not None
            # Without the catalogue listing there is nowhere else for the venue and distance to
            # appear, so the intro carries them. With it, repeating them here would say the same
            # thing twice on one card.
            else (
                f"This one is at {programme.venue}, about {programme.distance_km} km from you. "
                "Nothing has been booked and nobody has been told you looked."
            )
        ),
        steps=[
            OutreachStep(
                order=1,
                text=(
                    "If you would like to go, you can turn up or ring the centre yourself. "
                    "Care+ will not contact them for you."
                ),
            ),
            OutreachStep(
                order=2,
                text="You can change your mind at any point, including after you arrive.",
            ),
        ],
        stop_note="There is nothing to reply to and nothing you have committed to.",
        boundary_note=(
            "Details come from the activity list in this prototype. Check with the centre before "
            "you travel."
        ),
        programme=programme,
        activity=activity,
        source=_SOURCE,
    )


def detail_for(
    candidate_key: str,
    programme: Programme | None = None,
    activity: ActivityCandidate | None = None,
) -> OutreachDetail:
    """The content to show after someone asks to hear more.

    Falls back to an explicit "nothing to show" rather than inventing something, because the
    failure this whole module exists to fix was a button promising more and delivering nothing.
    An honest empty state is recoverable; a confident empty one is not.
    """
    movement = _movement_detail(candidate_key)
    if movement is not None:
        return movement
    if candidate_key.startswith("programme:") and programme is not None:
        return _programme_detail(programme, activity)
    return OutreachDetail(
        kind="none",
        title="Nothing more to show",
        intro=(
            "There are no extra details stored for this suggestion. Nothing has been booked and "
            "there is nothing you need to do."
        ),
        stop_note=_STOP_NOTE,
        boundary_note=_BOUNDARY_NOTE,
    )
