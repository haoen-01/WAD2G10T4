"""Authored ~60-day activity sequences with a latent "review-worthy" label per episode.

SYNTHETIC design artefacts. Not a senior's data, not derived from one, and deliberately kept in
Python rather than under `scenarios/`: the YAML scenarios are the safety suite's input contract,
and these are an evaluation's input. Pinned by `CALIBRATION_SEQUENCES_DIGEST`, so an edit is a
visible, reviewed change rather than a quiet re-tuning of the evaluation.

Each day is authored as a fraction of the person's anchored reference steps (read from the run
after reset), a wear-time and a rain flag. Each episode carries the label the simulated
coordinators judge against, which Care+ never sees:

- `review_worthy` -- whether a coordinator should hear about it at all;
- `should_reach_by_day` -- the latest sequence day a review-worthy episode should reach one.

What the sequences hold, on purpose:

- benign swings: 40-50% below for three or four days, then back. Not review-worthy. They are what
  the starting setting (40% for three days) asks about for a person whose routine swings;
- a benign dip: about 37% below for three days, which only a tightened setting asks about;
- genuine moderate declines: 42-48% below for ten or more days. Review-worthy. A loosened
  setting asks later, or not at all without the shadow check;
- genuine severe declines: 60% or more below for four or five days. Review-worthy, and at or past
  the absolute review floor, which no setting may pass.

Pure: stdlib only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

SEQUENCE_LENGTH_DAYS = 60
NORMAL_WEAR_HOURS = 13.2
# The weekly shape of an ordinary stretch: centred on the reference, never low.
NORMAL_CYCLE: tuple[float, ...] = (1.00, 1.06, 0.96, 1.03, 0.98, 1.08, 0.94)
# An authored fraction at or below this is "60% or more below" -- the absolute review floor's
# severity. Consecutive valid-wear days at or below it make an episode floor-reaching.
FLOOR_FRACTION = 0.40
FLOOR_DAYS = 3
# Below this fraction of wear a day carries no reading (mirrors `analytics.MINIMUM_WEAR_HOURS`;
# duplicated so this module stays stdlib-only).
MINIMUM_WEAR_HOURS = 8.0

EpisodeLabel = Literal["benign_swing", "benign_dip", "genuine_decline", "severe_decline"]


@dataclass(frozen=True)
class AuthoredDay:
    day: int
    steps_fraction: float
    wear_hours: float
    rainy: bool

    @property
    def event(self) -> str:
        """The simulation event this day is advanced with. Only its context matters: the authored
        metric replaces the event's own reading."""
        if self.rainy:
            return "rain_explains_decline"
        if self.wear_hours < MINIMUM_WEAR_HOURS:
            return "low_wear"
        if self.steps_fraction < 0.7:
            return "activity_declines"
        return "recovery"


@dataclass(frozen=True)
class Episode:
    episode_id: str
    label: EpisodeLabel
    start_day: int
    end_day: int
    review_worthy: bool
    should_reach_by_day: int | None


@dataclass(frozen=True)
class CalibrationSequence:
    sequence_id: str
    title: str
    description: str
    days: tuple[AuthoredDay, ...]
    episodes: tuple[Episode, ...]

    def day(self, index: int) -> AuthoredDay:
        return self.days[index - 1]

    def episode_on(self, day: int) -> Episode | None:
        return next((item for item in self.episodes if item.start_day <= day <= item.end_day), None)

    def reaches_floor(self, episode: Episode) -> bool:
        """At least `FLOOR_DAYS` consecutive valid-wear days at or past the floor's severity."""
        run = 0
        for index in range(episode.start_day, episode.end_day + 1):
            authored = self.day(index)
            if authored.wear_hours < MINIMUM_WEAR_HOURS:
                continue
            run = run + 1 if authored.steps_fraction <= FLOOR_FRACTION else 0
            if run >= FLOOR_DAYS:
                return True
        return False


_Low = tuple[float, ...]


def _build(
    sequence_id: str,
    title: str,
    description: str,
    episodes: tuple[tuple[Episode, _Low], ...],
    *,
    gaps: dict[int, float] | None = None,
    rain: frozenset[int] = frozenset(),
) -> CalibrationSequence:
    fractions: dict[int, float] = {}
    for episode, values in episodes:
        if len(values) != episode.end_day - episode.start_day + 1:
            raise ValueError(f"{sequence_id}/{episode.episode_id}: day count does not match")
        for offset, value in enumerate(values):
            fractions[episode.start_day + offset] = value
    days = tuple(
        AuthoredDay(
            day=index,
            steps_fraction=fractions.get(index, NORMAL_CYCLE[(index - 1) % len(NORMAL_CYCLE)]),
            wear_hours=(gaps or {}).get(index, NORMAL_WEAR_HOURS),
            rainy=index in rain,
        )
        for index in range(1, SEQUENCE_LENGTH_DAYS + 1)
    )
    return CalibrationSequence(
        sequence_id=sequence_id,
        title=title,
        description=description,
        days=days,
        episodes=tuple(episode for episode, _ in episodes),
    )


def _benign(episode_id: str, start: int, end: int, label: EpisodeLabel = "benign_swing") -> Episode:
    return Episode(episode_id, label, start, end, review_worthy=False, should_reach_by_day=None)


def _genuine(
    episode_id: str, start: int, end: int, reach_by: int, label: EpisodeLabel = "genuine_decline"
) -> Episode:
    return Episode(episode_id, label, start, end, review_worthy=True, should_reach_by_day=reach_by)


SWINGING_ROUTINE = _build(
    "swinging_routine",
    "A swinging routine, then two moderate declines that persist",
    "Three benign swings of 45-50% below for three or four days, a genuine decline of about 45% "
    "below for twelve days, and after a recovery a second genuine decline of about 45% below "
    "that is still under way when the sequence ends.",
    (
        (_benign("swing-1", 9, 11), (0.55, 0.52, 0.56)),
        (_benign("swing-2", 18, 21), (0.56, 0.53, 0.50, 0.55)),
        (_benign("swing-3", 28, 31), (0.54, 0.50, 0.52, 0.57)),
        (
            _genuine("decline-1", 38, 49, reach_by=41),
            (0.57, 0.55, 0.53, 0.54, 0.52, 0.55, 0.53, 0.51, 0.54, 0.52, 0.53, 0.55),
        ),
        (
            _genuine("decline-2", 51, 60, reach_by=54),
            (0.50, 0.49, 0.50, 0.48, 0.50, 0.49, 0.50, 0.48, 0.49, 0.50),
        ),
    ),
    rain=frozenset({28}),
)

SHARP_DROP = _build(
    "sharp_drop",
    "Benign swings, a sharp drop past the floor, then a mild dip",
    "Two benign swings, a genuine drop of 65-70% below for five days, a benign dip of about 37% "
    "below for three days that only a tightened setting asks about, then one more benign swing.",
    (
        (_benign("swing-1", 9, 11), (0.55, 0.53, 0.56)),
        (_benign("swing-2", 18, 21), (0.54, 0.52, 0.51, 0.56)),
        (
            _genuine("drop-1", 30, 34, reach_by=32, label="severe_decline"),
            (0.36, 0.32, 0.30, 0.33, 0.31),
        ),
        (_benign("dip-1", 43, 45, label="benign_dip"), (0.63, 0.62, 0.64)),
        (_benign("swing-3", 52, 55), (0.55, 0.52, 0.50, 0.56)),
    ),
)

SLOW_SLIDE = _build(
    "slow_slide",
    "Benign swings, a long moderate slide with a missed charge, then a sharp drop",
    "Three benign swings, a genuine decline of 42-48% below for fourteen days with one day the "
    "tracker was barely worn, then a genuine drop of 65-70% below for four days.",
    (
        (_benign("swing-1", 8, 10), (0.54, 0.51, 0.55)),
        (_benign("swing-2", 16, 19), (0.55, 0.50, 0.52, 0.56)),
        (_benign("swing-3", 25, 27), (0.53, 0.52, 0.55)),
        (
            _genuine("slide-1", 32, 45, reach_by=35),
            (0.56, 0.54, 0.52, 0.53, 0.20, 0.55, 0.52, 0.54, 0.58, 0.53, 0.55, 0.52, 0.54, 0.56),
        ),
        (
            _genuine("drop-1", 53, 56, reach_by=55, label="severe_decline"),
            (0.35, 0.30, 0.32, 0.34),
        ),
    ),
    gaps={36: 3.0},
)

CALIBRATION_SEQUENCES: tuple[CalibrationSequence, ...] = (SWINGING_ROUTINE, SHARP_DROP, SLOW_SLIDE)


def sequences_document(
    sequences: tuple[CalibrationSequence, ...] = CALIBRATION_SEQUENCES,
) -> list[dict[str, object]]:
    """The canonical JSON-ready form: the digest input, and the report's sequence section."""
    return [
        {
            "sequence_id": sequence.sequence_id,
            "title": sequence.title,
            "description": sequence.description,
            "days": [asdict(day) for day in sequence.days],
            "episodes": [
                {**asdict(episode), "reaches_floor": sequence.reaches_floor(episode)}
                for episode in sequence.episodes
            ],
        }
        for sequence in sequences
    ]


def sequences_digest(sequences: tuple[CalibrationSequence, ...] = CALIBRATION_SEQUENCES) -> str:
    canonical = json.dumps(
        sequences_document(sequences), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


CALIBRATION_SEQUENCES_DIGEST = sequences_digest()


__all__ = [
    "CALIBRATION_SEQUENCES",
    "CALIBRATION_SEQUENCES_DIGEST",
    "FLOOR_DAYS",
    "FLOOR_FRACTION",
    "SEQUENCE_LENGTH_DAYS",
    "AuthoredDay",
    "CalibrationSequence",
    "Episode",
    "EpisodeLabel",
    "sequences_digest",
    "sequences_document",
]
