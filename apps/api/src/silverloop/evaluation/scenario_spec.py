"""Scenario loading for the evaluation harness.

`labels` is an ADDITIVE extension to the existing scenario YAMLs used by
`silverloop.scenarios`. It carries ground-truth *world state*, one entry per event, and is
never derived from `expected_decisions` (see `GroundTruthState` docstring). This module only
reads the fields it needs; it does not validate `expected_decisions`/`expected_cases` beyond
type coercion, because `silverloop.scenarios.run_scenario` already owns that contract.

`world` (M24) is a second, equally additive block: the authored latent state behind each event,
parsed by `silverloop.evaluation.world`. It is optional per scenario and never edits, replaces or
is derived from `labels` -- the two are independent accounts of the same day whose agreement the
report prints. `silverloop.scenarios` reads neither block; it only ever looks up the keys it
knows, so both are invisible to the parity runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

from silverloop.evaluation.outcomes import AuthoredOutcome, OutcomeSpecError, coerce_outcome
from silverloop.evaluation.world import LatentSpec, WorldSpecError, coerce_latent_spec
from silverloop.fixtures import DEMO_PERSON_ID
from silverloop.models import Decision

DEFAULT_PERSON_ID = DEMO_PERSON_ID
DEFAULT_SEED = 2026


class GroundTruthState(StrEnum):
    """World-state ground truth for one event, independent of any policy's decision.

    Anti-circularity guard: a scenario's `labels:` entries must NEVER be `Decision` member
    names. Ground truth describes what actually happened in the world (a real dip explained by
    rain, a persistent decline, revoked consent, ...), not what any policy chose to do about it.
    Scoring a policy against its own decisions would be circular by construction.
    """

    STABLE = "stable"
    EXPLAINED_DIP = "explained_dip"
    EMERGING_DECLINE = "emerging_decline"
    PERSISTENT_DECLINE = "persistent_decline"
    UNUSABLE_DATA = "unusable_data"
    NO_CONSENT = "no_consent"


_DECISION_VALUES = frozenset(member.value for member in Decision)
_DECISION_NAMES = frozenset(member.name for member in Decision)


class ScenarioSpecError(ValueError):
    """Raised when a scenario YAML fails structural or semantic validation."""


@dataclass(frozen=True)
class EvaluationScenario:
    """A parsed scenario, additive over the `silverloop.scenarios` YAML contract.

    `expected_decisions` and `expected_cases` are carried through ONLY for the parity gate
    (`test_evaluation_parity.py`), which proves the harness reproduces Care+'s existing,
    already-trusted behaviour. Metric computation (`metrics.py`) must never read them: doing so
    would score `silverloop` against its own output.
    """

    path: Path
    name: str
    seed: int
    person_id: str
    events: tuple[str, ...]
    labels: tuple[GroundTruthState, ...]
    forbidden: tuple[tuple[str, ...], ...]
    expected_decisions: tuple[str, ...]
    expected_cases: int
    #: The authored latent world, one entry per event, or `None` when the scenario does not carry
    #: a `world:` block. `None` is a real state, not a default to be filled in: a latent that was
    #: not authored must stay absent rather than be inferred from the replayed numbers.
    world: tuple[LatentSpec, ...] | None = None
    #: The authored follow-through outcomes (M38), one optional entry per event: what this person
    #: does IF contacted on that day. A counterfactual fact about the person, in the same spirit
    #: as `world`, never a record of what a policy did -- which is what keeps the funnel from
    #: scoring Care+ against its own output. `None` when the scenario authors no block.
    outcomes: tuple[AuthoredOutcome | None, ...] | None = None


def _coerce_labels(path: Path, raw: object, event_count: int) -> tuple[GroundTruthState, ...]:
    if not isinstance(raw, list):
        raise ScenarioSpecError(f"{path}: 'labels' must be a list")
    if len(raw) != event_count:
        raise ScenarioSpecError(
            f"{path}: 'labels' has {len(raw)} entries but 'events' has {event_count}; "
            "labels must have exactly one entry per event"
        )
    labels: list[GroundTruthState] = []
    for entry in raw:
        if entry in _DECISION_VALUES or entry in _DECISION_NAMES:
            raise ScenarioSpecError(
                f"{path}: label {entry!r} is a Decision member; ground truth must be world "
                "state, never a policy decision (anti-circularity guard, see D4)"
            )
        try:
            labels.append(GroundTruthState(entry))
        except ValueError as exc:
            allowed = ", ".join(member.value for member in GroundTruthState)
            raise ScenarioSpecError(
                f"{path}: unknown label {entry!r}; expected one of: {allowed}"
            ) from exc
    return tuple(labels)


def _coerce_world(path: Path, raw: object, event_count: int) -> tuple[LatentSpec, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ScenarioSpecError(f"{path}: 'world' must be a list")
    if len(raw) != event_count:
        raise ScenarioSpecError(
            f"{path}: 'world' has {len(raw)} entries but 'events' has {event_count}; "
            "the latent world must have exactly one entry per event"
        )
    specs: list[LatentSpec] = []
    for index, entry in enumerate(raw):
        try:
            specs.append(coerce_latent_spec(entry, where=f"{path}:world[{index}]"))
        except WorldSpecError as exc:
            raise ScenarioSpecError(str(exc)) from exc
    return tuple(specs)


def _coerce_outcomes(
    path: Path, raw: object, event_count: int
) -> tuple[AuthoredOutcome | None, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ScenarioSpecError(f"{path}: 'outcomes' must be a list")
    if len(raw) != event_count:
        raise ScenarioSpecError(
            f"{path}: 'outcomes' has {len(raw)} entries but 'events' has {event_count}; "
            "the outcome block must have exactly one entry per event (use null for a day the "
            "scenario does not author)"
        )
    parsed: list[AuthoredOutcome | None] = []
    for index, entry in enumerate(raw):
        try:
            parsed.append(coerce_outcome(entry, where=f"{path}:outcomes[{index}]"))
        except OutcomeSpecError as exc:
            raise ScenarioSpecError(str(exc)) from exc
    return tuple(parsed)


def _coerce_forbidden(path: Path, raw: object, event_count: int) -> tuple[tuple[str, ...], ...]:
    if raw is None:
        return tuple(() for _ in range(event_count))
    if not isinstance(raw, list) or len(raw) != event_count:
        raise ScenarioSpecError(
            f"{path}: 'forbidden' must be a list with exactly one entry per event"
        )
    return tuple(tuple(str(item) for item in (entry or [])) for entry in raw)


def load_scenario(path: Path) -> EvaluationScenario:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ScenarioSpecError(f"{path}: scenario must be a mapping")

    events = document.get("events")
    if not isinstance(events, list) or not events:
        raise ScenarioSpecError(f"{path}: 'events' must be a non-empty list")
    events = tuple(str(event) for event in events)

    labels = _coerce_labels(path, document.get("labels"), len(events))
    forbidden = _coerce_forbidden(path, document.get("forbidden"), len(events))
    world = _coerce_world(path, document.get("world"), len(events))
    outcomes = _coerce_outcomes(path, document.get("outcomes"), len(events))

    expected_decisions = document.get("expected_decisions", [])
    if not isinstance(expected_decisions, list):
        raise ScenarioSpecError(f"{path}: 'expected_decisions' must be a list")

    return EvaluationScenario(
        path=path,
        name=path.stem,
        seed=int(document.get("seed", DEFAULT_SEED)),
        person_id=str(document.get("person_id", DEFAULT_PERSON_ID)),
        events=events,
        labels=labels,
        forbidden=forbidden,
        expected_decisions=tuple(str(decision) for decision in expected_decisions),
        expected_cases=int(document.get("expected_cases", 0)),
        world=world,
        outcomes=outcomes,
    )


def discover_scenarios(directory: Path) -> list[EvaluationScenario]:
    paths = sorted(Path(directory).glob("*.yaml"))
    if not paths:
        raise ScenarioSpecError(f"No scenario files found in {directory}")
    return [load_scenario(path) for path in paths]
