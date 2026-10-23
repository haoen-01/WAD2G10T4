"""Deterministic environment replay for the evaluation harness.

`replay()` mirrors the event table and consent transition in
`silverloop.sql_repository.SqlAlchemyRepository.advance`, specifically lines 497-561 of
`sql_repository.py`, WITHOUT importing that module (see the module-boundary contract in
`silverloop.evaluation`). Each `EnvironmentStep`'s metric, context and consent state are derived
only from prior metrics/context/consent -- never from any policy's decision -- so the exact same
list of steps can be folded over by every registered policy (D2). The only state that varies by
policy is the running contact count, tracked by the caller (`runner.py`), not here.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, time, timedelta

from silverloop.adapters.synthetic import SyntheticFixtureAdapter
from silverloop.analytics import analyse_signal
from silverloop.evaluation.scenario_spec import EvaluationScenario, GroundTruthState
from silverloop.evaluation.world import INITIAL_LATENT, LatentState, advance_latent
from silverloop.fixtures import persona_seed, synthetic_programmes
from silverloop.models import ContextSignal, DailyMetric, SignalSummary

ALLOWED_EVENTS = frozenset(
    {
        "activity_declines",
        "rain_explains_decline",
        "rain_clears_activity_low",
        "recovery",
        "low_wear",
        "consent_revoked",
        "public_holiday",
    }
)


class SimulationError(ValueError):
    """Raised when a scenario references an event the environment does not model."""


def load_persona_history(person_id: str, seed: int) -> list[DailyMetric]:
    """The single multi-persona seam.

    Routes through `silverloop.fixtures.persona_seed`, the same function
    `SqlAlchemyRepository.reset` uses, so the repository and the evaluation harness derive a
    person's fixture from the identical seed by construction. F5 grows the persona registry;
    this function does not need to change when it does.
    """
    batch = SyntheticFixtureAdapter(persona_seed(person_id, seed), person_id=person_id).read()
    return [metric.daily_metric() for metric in batch.metrics]


class EnvironmentStep:
    """One decision-independent step of the replayed environment.

    `latent` is the authored world behind the step (M24) and is `None` for a scenario with no
    `world:` block. **No policy and no fold may read it**: it is ground truth, so letting a
    decision see it would be handing the answer sheet to the candidate.
    `test_fold_policy_never_reads_latent` pins that, both by source inspection and behaviourally.
    """

    __slots__ = (
        "step",
        "person_id",
        "event",
        "label",
        "forbidden",
        "history",
        "metric",
        "context",
        "consent_active",
        "signal",
        "programme_fresh",
        "latent",
    )

    def __init__(
        self,
        *,
        step: int,
        person_id: str,
        event: str,
        label: GroundTruthState,
        forbidden: tuple[str, ...],
        history: tuple[DailyMetric, ...],
        metric: DailyMetric,
        context: ContextSignal,
        consent_active: bool,
        signal: SignalSummary,
        programme_fresh: bool,
        latent: LatentState | None = None,
    ) -> None:
        self.step = step
        self.person_id = person_id
        self.event = event
        self.label = label
        self.forbidden = forbidden
        self.history = history
        self.metric = metric
        self.context = context
        self.consent_active = consent_active
        self.signal = signal
        self.programme_fresh = programme_fresh
        self.latent = latent


def _advance_metric(
    event: str, history: list[DailyMetric], current: DailyMetric
) -> tuple[DailyMetric, ContextSignal, bool]:
    """Port of the event table in `sql_repository.py:497-561`.

    Returns `(next_metric, context, revokes_consent)`. `revokes_consent` mirrors the
    `consent_revoked` branch, which appends an inactive `ConsentEvidenceRow` before evaluation.
    """
    if event not in ALLOWED_EVENTS:
        raise SimulationError(
            f"Unsupported event {event!r}. Choose one of {sorted(ALLOWED_EVENTS)}"
        )

    next_day = current.day + timedelta(days=1)
    context = ContextSignal()
    revokes_consent = False

    if event == "activity_declines":
        previous_low_days = sum(
            metric.steps < 4200 and metric.wear_hours >= 8 for metric in [*history, current][-2:]
        )
        next_metric = DailyMetric(
            day=next_day,
            steps=max(2100, 3400 - previous_low_days * 450),
            active_minutes=max(12, 26 - previous_low_days * 4),
            sleep_hours=6.4,
            wear_hours=13.2,
        )
    elif event == "rain_explains_decline":
        next_metric = DailyMetric(
            day=next_day,
            steps=3300,
            active_minutes=25,
            sleep_hours=7.0,
            wear_hours=13.1,
        )
        context = ContextSignal(rainy=True, note="Heavy afternoon rain fixture")
    elif event == "rain_clears_activity_low":
        next_metric = DailyMetric(
            day=next_day,
            steps=3200,
            active_minutes=24,
            sleep_hours=6.8,
            wear_hours=13.0,
        )
        context = ContextSignal(
            rainy=False,
            note="Skies have cleared, but activity has not recovered",
        )
    elif event == "public_holiday":
        next_metric = DailyMetric(
            day=next_day,
            steps=4300,
            active_minutes=32,
            sleep_hours=7.0,
            wear_hours=13.2,
        )
        context = ContextSignal(
            holiday=True,
            note=(
                "Public holiday fixture; recorded as context only -- the policy does "
                "not treat a holiday as an automatic excuse for a decline."
            ),
        )
    elif event == "recovery":
        next_metric = DailyMetric(
            day=next_day,
            steps=6180,
            active_minutes=47,
            sleep_hours=7.3,
            wear_hours=13.8,
        )
    elif event == "low_wear":
        next_metric = DailyMetric(
            day=next_day,
            steps=900,
            active_minutes=7,
            sleep_hours=None,
            wear_hours=2.1,
        )
    else:  # consent_revoked
        next_metric = DailyMetric(
            day=next_day,
            steps=0,
            active_minutes=0,
            sleep_hours=None,
            wear_hours=0,
        )
        revokes_consent = True

    return next_metric, context, revokes_consent


def _observe(metric: DailyMetric, rng: random.Random, sigma: float) -> DailyMetric:
    """The measurement channel: what the wearable reports about the day the world just had.

    With `sigma <= 0` -- the default, and what every committed artifact is generated with -- the
    channel is noiseless and the event table above IS the observation, unchanged to the byte. The
    seeded lognormal draw exists so the one property that matters can be tested rather than
    asserted: the same authored latent observed under different noise draws must still produce the
    same `label_from_latent`, because the truth does not move when the measurement does. It is
    off by default because turning it on would move every `expected_decisions` entry in
    `scenarios/`, which are hand-authored and are not this track's to rewrite.

    Wear hours are deliberately NOT jittered: wear time is the data-quality gate's own input, and
    perturbing it would make the quality gate noisy rather than the activity measurement.
    """
    if sigma <= 0:
        return metric
    factor = min(3.0, max(0.1, rng.lognormvariate(0.0, sigma)))
    return DailyMetric(
        day=metric.day,
        steps=max(0, round(metric.steps * factor)),
        active_minutes=max(0, round(metric.active_minutes * factor)),
        sleep_hours=metric.sleep_hours,
        wear_hours=metric.wear_hours,
    )


def _programme_fresh(as_of: datetime) -> bool:
    """Mirrors `_programme_models(current_only=True, as_of=...)`'s freshness filter."""
    return any(
        programme.next_session + timedelta(days=7) >= as_of for programme in synthetic_programmes()
    )


def replay(
    scenario: EvaluationScenario, *, observation_sigma: float = 0.0
) -> list[EnvironmentStep]:
    """Replay a scenario's environment ONCE, independent of any policy.

    The returned list is folded over identically by every `PolicyEntry` (D2): all fields except
    the per-policy running contact count are shared byte-for-byte across policies.

    Each day is advanced in two ordered halves (M24). First the **authored latent world** moves
    (`world.advance_latent`), from the scenario's `world:` block and the previous day's latent --
    it never consults a `DailyMetric`. Then the day is **observed**: the event table produces what
    the wearable saw, optionally through the seeded noise channel `_observe`. A scenario with no
    `world:` block replays exactly as before with `latent=None` on every step; nothing infers a
    latent from the numbers.

    `observation_sigma` seeds per scenario AND per persona, so two people living the same scripted
    week are not measured through the identical error sequence.
    """
    metrics = load_persona_history(scenario.person_id, scenario.seed)
    history = metrics[:-1]
    current = metrics[-1]
    consent_active = True
    world = scenario.world
    latent: LatentState = INITIAL_LATENT
    rng = random.Random(f"{scenario.seed}:{scenario.person_id}:{scenario.name}")
    steps: list[EnvironmentStep] = []

    for index, event in enumerate(scenario.events):
        # The world moves before anything measures it.
        if world is not None:
            latent = advance_latent(event, latent, world[index])

        next_metric, context, revokes_consent = _advance_metric(event, history, current)
        next_metric = _observe(next_metric, rng, observation_sigma)
        history = [*history, current]
        current = next_metric
        if revokes_consent:
            consent_active = False

        assessed_at = datetime.combine(current.day, time(hour=12), tzinfo=UTC)
        _, signal = analyse_signal(
            history, current, context, person_id=scenario.person_id, assessed_at=assessed_at
        )

        steps.append(
            EnvironmentStep(
                step=index + 1,
                person_id=scenario.person_id,
                event=event,
                label=scenario.labels[index],
                forbidden=scenario.forbidden[index],
                history=tuple(history),
                metric=current,
                context=context,
                consent_active=consent_active,
                signal=signal,
                programme_fresh=_programme_fresh(assessed_at),
                latent=latent if world is not None else None,
            )
        )

    return steps
