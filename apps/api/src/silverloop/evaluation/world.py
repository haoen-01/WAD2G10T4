"""The authored latent world behind a replayed scenario (M24).

Until this module existed the harness had exactly one account of what was true on a given day:
the numbers `simulation._advance_metric` generated. The hand-authored `labels:` entries were
independent of those numbers only by the scenario author's discipline, and
`test_documented_ground_truth_rule_reproduces_every_scenario_label` then pinned every one of them
to a rule built out of `analytics.py` and `quality.py` -- the same predicates the ladder reads. A
second, genuinely separate account of the world was needed, and it has to come from a human, not
from a derivation.

`LatentState` is that account. It is **authored** in the scenario YAML's optional `world:` block,
one entry per event, and says what the scenario writer scripted the person's day to actually be:
how much of their own normal activity they really did, what drove it, how long it has been going
on, and whether the device saw the day at all. Nothing in this module looks at a `DailyMetric`, a
`SignalSummary` or a `Decision`.

Two properties make it honest, and both are enforced elsewhere rather than assumed here:

- the latent is never derived from the generated numbers (this module has no access to them);
- `latent_labels.label_from_latent`'s cut points are authored definitions of the world and are
  never re-tuned to agree with the ladder -- `report.py` prints the agreement rate precisely so a
  reader can see how far apart the two accounts are, and says outright that 1.000 would mean the
  tautology had been rebuilt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: At or below this fraction of the person's own authored norm, the world calls the day low. It is
#: a definition of the scripted world, not a threshold anything measures: no gate, baseline or
#: quality rule reads it, and it is deliberately NOT the ladder's -20% nudge boundary.
LOW_ACTIVITY_LEVEL = 0.80

#: The events on which the device does not see the day. `observable` still defaults from the event
#: rather than from the generated wear hours, so the authored world stays separate from the
#: measurement -- an author may override it either way.
UNOBSERVED_EVENTS = frozenset({"low_wear", "consent_revoked"})

#: Upper bound on an authored level. A person may exceed their own norm (a holiday walk, a good
#: week); three times it is a typo, not a world.
MAX_ACTIVITY_LEVEL = 3.0


class LatentCause(StrEnum):
    """What the scenario author says is driving this day's activity level.

    `NONE` means nothing in particular is: the person is living their normal life, whatever the
    number happens to read. It is the right answer for a day that is at or above the person's own
    norm even when it rained, because weather that explains nothing is not a cause (see
    `scenarios/holdout/h02_low_baseline_under_rain.yaml`).
    """

    NONE = "none"
    WEATHER = "weather"
    ILLNESS_LIKE = "illness_like"
    DEVICE = "device"
    HOLIDAY = "holiday"
    ROUTINE_CHANGE = "routine_change"


@dataclass(frozen=True)
class LatentState:
    """What was actually true on one replayed day, as authored.

    `true_activity_level` is a fraction of the person's own AUTHORED norm, never of a rolling or
    anchored median computed from the replay. `days_low` counts consecutive days the world has
    been low, including this one. `observable` is whether the device saw the day at all -- which
    is what lets a scenario say "a real decline happened and the wearable missed it", the case the
    harness could not represent before, because `low_wear` used to set both the truth and the
    label to "unusable".
    """

    true_activity_level: float
    cause: LatentCause
    days_low: int
    observable: bool

    @property
    def is_low(self) -> bool:
        return self.true_activity_level <= LOW_ACTIVITY_LEVEL


#: Where every scenario's world starts: a normal, fully observed day with nothing driving it.
INITIAL_LATENT = LatentState(
    true_activity_level=1.0,
    cause=LatentCause.NONE,
    days_low=0,
    observable=True,
)


class WorldSpecError(ValueError):
    """Raised when a scenario's `world:` block fails structural validation."""


@dataclass(frozen=True)
class LatentSpec:
    """One authored `world:` entry.

    `cause` and `true_level` are required -- they are the judgement only a human can make.
    `days_low` and `observable` are optional and default from the previous day's latent and the
    event name respectively, so the common case stays two keys wide and an author who needs to
    say something unusual (a decline that continues invisibly through a revocation, a device that
    dropped out on an otherwise ordinary day) can still say it explicitly.
    """

    cause: LatentCause
    true_activity_level: float
    days_low: int | None = None
    observable: bool | None = None


_SPEC_KEYS = frozenset({"cause", "true_level", "days_low", "observable"})


def coerce_latent_spec(raw: object, *, where: str) -> LatentSpec:
    """Parse one `world:` entry. Strict: an unknown key is an authoring mistake, not a comment."""
    if not isinstance(raw, dict):
        raise WorldSpecError(f"{where}: each 'world' entry must be a mapping")
    unknown = sorted(set(raw) - _SPEC_KEYS)
    if unknown:
        raise WorldSpecError(
            f"{where}: unknown world key(s) {', '.join(unknown)}; "
            f"expected any of: {', '.join(sorted(_SPEC_KEYS))}"
        )
    for required in ("cause", "true_level"):
        if required not in raw:
            raise WorldSpecError(f"{where}: 'world' entry is missing required key {required!r}")

    try:
        cause = LatentCause(raw["cause"])
    except ValueError as exc:
        allowed = ", ".join(member.value for member in LatentCause)
        raise WorldSpecError(
            f"{where}: unknown cause {raw['cause']!r}; expected one of: {allowed}"
        ) from exc

    level = raw["true_level"]
    if isinstance(level, bool) or not isinstance(level, int | float):
        raise WorldSpecError(f"{where}: 'true_level' must be a number, got {level!r}")
    level = float(level)
    if not 0.0 <= level <= MAX_ACTIVITY_LEVEL:
        raise WorldSpecError(
            f"{where}: 'true_level' must lie in [0, {MAX_ACTIVITY_LEVEL}], got {level}"
        )

    days_low = raw.get("days_low")
    if days_low is not None:
        if isinstance(days_low, bool) or not isinstance(days_low, int):
            raise WorldSpecError(f"{where}: 'days_low' must be an integer, got {days_low!r}")
        if days_low < 0:
            raise WorldSpecError(f"{where}: 'days_low' must not be negative, got {days_low}")

    observable = raw.get("observable")
    if observable is not None and not isinstance(observable, bool):
        raise WorldSpecError(f"{where}: 'observable' must be a boolean, got {observable!r}")

    return LatentSpec(
        cause=cause,
        true_activity_level=level,
        days_low=days_low,
        observable=observable,
    )


def advance_latent(event: str, previous: LatentState, spec: LatentSpec) -> LatentState:
    """Advance the authored world by one day.

    Called BEFORE the day is observed (`simulation.replay`), so the ordering in the code matches
    the ordering in the fiction: the world moves, and only then does a wearable get to have an
    opinion about it. The authored level and cause always win; `days_low` continues the previous
    day's run whenever the world is low and resets otherwise, and `observable` defaults from the
    event. Both defaults are overridable per entry.
    """
    days_low = spec.days_low
    if days_low is None:
        low = spec.true_activity_level <= LOW_ACTIVITY_LEVEL
        days_low = previous.days_low + 1 if low else 0
    observable = spec.observable
    if observable is None:
        observable = event not in UNOBSERVED_EVENTS
    return LatentState(
        true_activity_level=spec.true_activity_level,
        cause=spec.cause,
        days_low=days_low,
        observable=observable,
    )


__all__ = [
    "INITIAL_LATENT",
    "LOW_ACTIVITY_LEVEL",
    "MAX_ACTIVITY_LEVEL",
    "UNOBSERVED_EVENTS",
    "LatentCause",
    "LatentSpec",
    "LatentState",
    "WorldSpecError",
    "advance_latent",
    "coerce_latent_spec",
]
