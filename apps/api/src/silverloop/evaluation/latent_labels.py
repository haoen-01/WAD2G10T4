"""The two ground-truth label sources, and the diagnostic that keeps them honest (M24).

Named `latent_labels` rather than `labels` because `evaluation/ranking/labels.py` already owns
that basename for the ranking benchmark's relevance grades; two modules called `labels` under one
package would make every import site ambiguous to a reader even though Python would resolve them.

Two functions, two accounts of the same day:

- `label_from_signal` is an executable transcription of `report.LABELLING_RULE` -- the rule the
  scenario authors say they followed. It reads `SignalSummary`, so it is built out of
  `analytics.py` and `quality.py`: the same `quality.safe_to_interpret`, the same
  `sustained_low_days >= 3`, the same -20% boundary the ladder reads. It is NOT independent of the
  policy being scored, and that is the finding this module exists to make visible rather than the
  one it tries to hide.
- `label_from_latent` reads the authored `world:` block and nothing else. Its cut points are
  definitions of the scripted world, tuned to nothing.

`label_feature_agreement` is the share of steps where the two agree. **A value of 1.000 means the
second label source has collapsed back onto the first and the harness is a tautology again**; the
report prints that sentence next to the number. The disagreements are listed rather than
reconciled: each one is a day where what the author scripted and what the wearable-derived rule
concluded genuinely differ, which is the only evidence this harness can offer that its ground
truth is not the feature restated.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from silverloop.evaluation.metrics import Rate
from silverloop.evaluation.scenario_spec import GroundTruthState
from silverloop.evaluation.simulation import EnvironmentStep
from silverloop.evaluation.world import LatentCause, LatentState
from silverloop.models import SignalSummary

#: The authored world's own cut points. Deliberately duplicated as named constants so that a
#: future edit to either one is visible in a diff as what it is: a change to the definition of the
#: fictional world, never a re-tune against the ladder.
STABLE_ABOVE_LEVEL = 0.80
PERSISTENT_FROM_DAYS_LOW = 3

#: The signal rule's own boundary, kept as a constant for the same reason. It is the same -20% the
#: nudge rung uses; `report.LABELLING_CAVEAT` says so.
SIGNAL_DIP_PERCENT = -20.0
SIGNAL_PERSISTENT_FROM_DAYS = 3


def label_from_latent(latent: LatentState, consent_active: bool) -> GroundTruthState:
    """Ground truth from the authored world alone.

    Order matters and is authored: consent is a fact about permission, not about the body, so it
    comes first; a day the device never saw cannot be judged whatever was true underneath it;
    weather that the author named as the cause explains the dip regardless of its depth or how
    many days it has run (which is exactly why `h04_rain_never_clears` disagrees with the ladder,
    whose rain gate expires after one day).
    """
    if not consent_active:
        return GroundTruthState.NO_CONSENT
    if not latent.observable:
        return GroundTruthState.UNUSABLE_DATA
    if latent.cause == LatentCause.WEATHER:
        return GroundTruthState.EXPLAINED_DIP
    if latent.true_activity_level > STABLE_ABOVE_LEVEL:
        return GroundTruthState.STABLE
    if latent.days_low < PERSISTENT_FROM_DAYS_LOW:
        return GroundTruthState.EMERGING_DECLINE
    return GroundTruthState.PERSISTENT_DECLINE


def label_from_signal(signal: SignalSummary, consent_active: bool) -> GroundTruthState:
    """Ground truth from the replayed wearable signal -- `report.LABELLING_RULE`, executed.

    Lifted out of `test_evaluation.py`, where it had been a test-only helper used to assert that
    every authored label equalled its output. It is production code now because the report prints
    its agreement with `label_from_latent`; the assertion it used to back has been relaxed to a
    reported rate, since an honest disagreement between two independent label sources must not be
    a CI failure.

    Never reads `expected_decisions` (the anti-circularity guard `scenario_spec.py` enforces on
    the authored labels themselves), but it does read `quality.safe_to_interpret`,
    `sustained_low_days` and the -20% boundary -- three predicates the ladder also reads.
    """
    if not consent_active:
        return GroundTruthState.NO_CONSENT
    if not signal.quality.safe_to_interpret:
        return GroundTruthState.UNUSABLE_DATA
    if signal.context.rainy and signal.reference_delta_percent <= SIGNAL_DIP_PERCENT:
        return GroundTruthState.EXPLAINED_DIP
    if signal.reference_delta_percent > SIGNAL_DIP_PERCENT:
        return GroundTruthState.STABLE
    if signal.sustained_low_days < SIGNAL_PERSISTENT_FROM_DAYS:
        return GroundTruthState.EMERGING_DECLINE
    return GroundTruthState.PERSISTENT_DECLINE


@dataclass(frozen=True)
class StepLabels:
    """Both label columns for one replayed step, plus the authored one they are compared against.

    `label_latent` is `None` for a scenario with no `world:` block: the latent must be authored or
    absent, never inferred from the generated numbers, so there is no fallback to silently fill
    this in.
    """

    scenario_set: str
    scenario: str
    step: int
    person_id: str
    event: str
    label_authored: GroundTruthState
    label_signal: GroundTruthState
    label_latent: GroundTruthState | None

    @property
    def latent_agrees_with_signal(self) -> bool | None:
        if self.label_latent is None:
            return None
        return self.label_latent == self.label_signal

    def describe(self) -> str:
        latent = self.label_latent.value if self.label_latent else "n/a"
        return (
            f"{self.scenario_set}/{self.scenario}:{self.step} ({self.event}) "
            f"authored={self.label_authored.value} signal={self.label_signal.value} "
            f"latent={latent}"
        )


@dataclass(frozen=True)
class LabelAgreement:
    """Every step's label columns, and the two rates worth printing beside them."""

    rows: tuple[StepLabels, ...]

    @property
    def scenarios_without_world(self) -> tuple[str, ...]:
        """Scenario names with no authored `world:` block, in first-seen order. Printed rather
        than silently excluded: a shrinking denominator is a result, not an omission."""
        seen: dict[str, None] = {}
        for row in self.rows:
            if row.label_latent is None:
                seen.setdefault(f"{row.scenario_set}/{row.scenario}", None)
        return tuple(seen)

    @property
    def feature_agreement(self) -> Rate:
        """M24's headline diagnostic: latent vs signal-derived, over steps that have a latent."""
        scored = [row for row in self.rows if row.label_latent is not None]
        return Rate(
            numerator=sum(1 for row in scored if row.latent_agrees_with_signal),
            denominator=len(scored),
            scenarios=len({(row.scenario_set, row.scenario) for row in scored}),
            personas=len({row.person_id for row in scored}),
        )

    @property
    def authored_signal_agreement(self) -> Rate:
        """The rate the relaxed `test_documented_ground_truth_rule_...` reports: how far the
        hand-authored `labels:` entries and the documented signal rule still coincide."""
        return Rate(
            numerator=sum(1 for row in self.rows if row.label_authored == row.label_signal),
            denominator=len(self.rows),
            scenarios=len({(row.scenario_set, row.scenario) for row in self.rows}),
            personas=len({row.person_id for row in self.rows}),
        )

    def feature_disagreements(self) -> tuple[StepLabels, ...]:
        return tuple(row for row in self.rows if row.latent_agrees_with_signal is False)

    def authored_disagreements(self) -> tuple[StepLabels, ...]:
        return tuple(row for row in self.rows if row.label_authored != row.label_signal)

    def latent_vs_authored_disagreements(self) -> tuple[StepLabels, ...]:
        return tuple(
            row
            for row in self.rows
            if row.label_latent is not None and row.label_latent != row.label_authored
        )


def label_rows(
    scenario_set: str, scenario: str, steps: Iterable[EnvironmentStep]
) -> list[StepLabels]:
    """Build one `StepLabels` per replayed `EnvironmentStep`."""
    rows: list[StepLabels] = []
    for step in steps:
        rows.append(
            StepLabels(
                scenario_set=scenario_set,
                scenario=scenario,
                step=step.step,
                person_id=step.person_id,
                event=step.event,
                label_authored=step.label,
                label_signal=label_from_signal(step.signal, step.consent_active),
                label_latent=(
                    None
                    if step.latent is None
                    else label_from_latent(step.latent, step.consent_active)
                ),
            )
        )
    return rows


def build_label_agreement(rows: Sequence[StepLabels]) -> LabelAgreement:
    return LabelAgreement(rows=tuple(rows))


__all__ = [
    "PERSISTENT_FROM_DAYS_LOW",
    "SIGNAL_DIP_PERCENT",
    "STABLE_ABOVE_LEVEL",
    "LabelAgreement",
    "StepLabels",
    "build_label_agreement",
    "label_from_latent",
    "label_from_signal",
    "label_rows",
]
