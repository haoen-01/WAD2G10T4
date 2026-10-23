"""Scripted demo histories for the evaluator-only Activity Ranker Inspector.

No persona is seeded with any activity responses, so on live state every persona ranks the same
request identically -- the ranker has nothing personal to read (spec discrepancy D8). These
presets give an evaluator something to compare: a short, hand-written list of the answers a
person could have given, keyed by programme and by how many simulated days ago.

**Scripted, never saved.** A preset is folded through the very same pure learners a real answer
goes through (`preferences.apply_decline`, `preferences.apply_enjoyment`,
`activity_search.count_engagement`) on top of the person's live state, inside one inspection, and
is discarded with the response. Every event carries an `origin_id` prefixed `scripted:` and every
fact it produces is labelled `scripted_history`. Nothing here is a real person's data.

Deliberately outside `silverloop.evaluation`, which may not import the repository. Only
declines, interests and enjoyment reports are scripted: a stated preference is written by
`SqlAlchemyRepository._confirm_dimension_preference`, whose row logic is not a pure function.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, Literal

from silverloop.models import (
    ActivityCandidate,
    ClarificationScope,
    DeclineReason,
    Enjoyment,
    LikedAspect,
)

SCRIPTED_ORIGIN_PREFIX: Final[str] = "scripted:"

_SESSION_SUFFIX = re.compile(r"-\d+$")


def programme_key(activity_id: str) -> str:
    """The programme a fixture listing belongs to: its id without the `activity-` prefix and the
    trailing session number (`activity-chair-mobility-2` -> `chair-mobility`)."""
    key = activity_id.removeprefix("activity-")
    return _SESSION_SUFFIX.sub("", key)


def first_session(catalogue: list[ActivityCandidate], key: str) -> ActivityCandidate | None:
    """The listing a scripted event about programme `key` is recorded against: the first session
    of that programme by activity id, so the choice never depends on catalogue order."""
    sessions = sorted(
        (candidate for candidate in catalogue if programme_key(candidate.activity_id) == key),
        key=lambda candidate: candidate.activity_id,
    )
    return sessions[0] if sessions else None


@dataclass(frozen=True)
class ScriptedEvent:
    kind: Literal["not_for_me", "interested", "enjoyment"]
    programme_key: str
    days_ago: int
    reason: DeclineReason | None = None
    clarification: ClarificationScope | None = None
    enjoyment: Enjoyment | None = None
    liked: tuple[LikedAspect, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HistoryPreset:
    preset_id: str
    person_id: str
    title: str
    events: tuple[ScriptedEvent, ...]


HISTORY_PRESETS: Final[tuple[HistoryPreset, ...]] = (
    HistoryPreset(
        preset_id="lim-social-nearby",
        person_id="mdm-lim",
        title="Mdm Lim: enjoys company, stays close to home (scripted)",
        events=(
            ScriptedEvent(
                kind="enjoyment",
                programme_key="evening-social",
                days_ago=12,
                enjoyment=Enjoyment.ENJOYED,
                liked=(LikedAspect.PEOPLE,),
            ),
            ScriptedEvent(
                kind="not_for_me",
                programme_key="brisk-walk",
                days_ago=10,
                reason=DeclineReason.TOO_FAR,
            ),
            ScriptedEvent(
                kind="enjoyment",
                programme_key="craft-circle",
                days_ago=7,
                enjoyment=Enjoyment.ENJOYED,
                liked=(LikedAspect.PEOPLE, LikedAspect.ACTIVITY),
            ),
            ScriptedEvent(
                kind="not_for_me",
                programme_key="garden-stretch",
                days_ago=5,
                reason=DeclineReason.NOT_FOR_ME,
            ),
            ScriptedEvent(
                kind="not_for_me",
                programme_key="pool-exercise",
                days_ago=4,
                reason=DeclineReason.TOO_FAR,
            ),
            ScriptedEvent(kind="interested", programme_key="chair-mobility", days_ago=2),
        ),
    ),
    HistoryPreset(
        preset_id="ravi-knee-quiet",
        person_id="mr-ravi",
        title="Mr Ravi: gentler, quieter activities (scripted)",
        events=(
            ScriptedEvent(
                kind="not_for_me",
                programme_key="brisk-walk",
                days_ago=11,
                reason=DeclineReason.TOO_TIRING,
            ),
            ScriptedEvent(
                kind="not_for_me",
                programme_key="karaoke",
                days_ago=9,
                reason=DeclineReason.NOT_FOR_ME,
            ),
            ScriptedEvent(
                kind="enjoyment",
                programme_key="seated-strength",
                days_ago=7,
                enjoyment=Enjoyment.ENJOYED,
                liked=(LikedAspect.ACTIVITY,),
            ),
            ScriptedEvent(
                kind="not_for_me",
                programme_key="evening-social",
                days_ago=6,
                reason=DeclineReason.NOT_FOR_ME,
            ),
            ScriptedEvent(kind="interested", programme_key="reading-corner", days_ago=3),
        ),
    ),
)


def preset_by_id(preset_id: str) -> HistoryPreset | None:
    return next((preset for preset in HISTORY_PRESETS if preset.preset_id == preset_id), None)
