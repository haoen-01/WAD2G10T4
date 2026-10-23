"""Policy registration for the evaluation harness.

D1: `silverloop.policy.decide` already structurally satisfies the `Policy` protocol below
(`Protocol.__call__(signal, *, consent_active, interventions_last_7_days) -> PolicyResult`), so
it is registered directly -- no adapter, no wrapper, no changes to `policy.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from silverloop.evaluation.baselines import (
    contextual_rule_decide,
    fixed_threshold_decide,
    make_fixed_threshold,
)
from silverloop.evaluation.ladder import FULL_LADDER, GATE_NAMES, ablated_config, make_ladder
from silverloop.models import DailyMetric, SignalSummary
from silverloop.policy import PolicyResult
from silverloop.policy import decide as silverloop_decide

SILVERLOOP_POLICY_VERSION = "silverloop-policy-v1"
FIXED_THRESHOLD_POLICY_VERSION = "fixed-threshold-v1"
CONTEXTUAL_RULE_POLICY_VERSION = "contextual-rule-v1"
ABLATION_POLICY_VERSION = "silverloop-ablation-v1"
SWEEP_POLICY_VERSION = "fixed-threshold-sweep-v1"

# The absolute-threshold analogue of `analyse_signal`'s low-wear-quality gate; kept separate so a
# future change to that gate does not silently change what "low" means for blind_view.
MINIMUM_WEAR_HOURS = 8
ABSOLUTE_LOW_STEPS = 3000


class Policy(Protocol):
    def __call__(
        self,
        signal: SignalSummary,
        *,
        consent_active: bool,
        interventions_last_7_days: int,
    ) -> PolicyResult: ...


View = Callable[[SignalSummary, Sequence[DailyMetric]], SignalSummary]


def identity_view(signal: SignalSummary, window: Sequence[DailyMetric]) -> SignalSummary:
    """`silverloop`'s own policy sees the real, baseline-relative signal unmodified."""
    del window
    return signal


def absolute_low_days(window: Sequence[DailyMetric]) -> int:
    """Trailing days with `wear_hours >= 8 and steps < 3000`, counted back from the tail of
    `window` (which must end with the current day) until the first day that fails either test.
    This is the absolute-threshold analogue of `analyse_signal`'s personal, median-relative
    `sustained_low_days` -- deliberately blind to the individual's own baseline.
    """
    count = 0
    for metric in reversed(window):
        if metric.wear_hours >= MINIMUM_WEAR_HOURS and metric.steps < ABSOLUTE_LOW_STEPS:
            count += 1
        else:
            break
    return count


def blind_view(signal: SignalSummary, window: Sequence[DailyMetric]) -> SignalSummary:
    """D3: structurally deny the baseline policies Care+'s personal baseline.

    Without this, `contextual_rule` reading `signal.sustained_low_days` would silently inherit
    Care+'s own median-relative persistence calculation, and the comparison between the two
    would be meaningless -- the baseline would be borrowing Care+'s judgement, not making
    its own.
    """
    return signal.model_copy(
        update={
            "delta_percent": 0.0,
            "robust_z": 0.0,
            "sustained_low_days": absolute_low_days(window),
        }
    )


@dataclass(frozen=True)
class PolicyEntry:
    name: str
    version: str
    decide: Policy
    view: View


POLICIES: tuple[PolicyEntry, ...] = (
    PolicyEntry(
        name="fixed_threshold",
        version=FIXED_THRESHOLD_POLICY_VERSION,
        decide=fixed_threshold_decide,
        view=blind_view,
    ),
    PolicyEntry(
        name="contextual_rule",
        version=CONTEXTUAL_RULE_POLICY_VERSION,
        decide=contextual_rule_decide,
        view=blind_view,
    ),
    PolicyEntry(
        name="silverloop",
        version=SILVERLOOP_POLICY_VERSION,
        decide=silverloop_decide,
        view=identity_view,
    ),
)

SILVERLOOP_POLICY_NAME = "silverloop"

# One variant per gate, each built from `ladder.make_ladder` -- a transcription of the ladder that
# lives inside this package. `policy.py` is never imported-and-mutated to produce these.
ABLATIONS: tuple[PolicyEntry, ...] = tuple(
    PolicyEntry(
        name=f"silverloop_no_{gate}",
        version=ABLATION_POLICY_VERSION,
        decide=make_ladder(ablated_config(gate)),
        view=identity_view,
    )
    for gate in GATE_NAMES
)

# The reference arm for the ablation table: the same transcription with every gate ON. It is
# asserted equal to `silverloop.policy.decide` by the harness test suite, so any delta in the
# ablation table is attributable to the disabled gate and not to the transcription.
ABLATION_REFERENCE = PolicyEntry(
    name="silverloop_all_gates",
    version=ABLATION_POLICY_VERSION,
    decide=make_ladder(FULL_LADDER),
    view=identity_view,
)


def sweep_entry(threshold: int) -> PolicyEntry:
    """A `fixed_threshold` baseline at an arbitrary step threshold, for the sensitivity sweep."""
    return PolicyEntry(
        name=f"fixed_threshold_{threshold}",
        version=SWEEP_POLICY_VERSION,
        decide=make_fixed_threshold(threshold),
        view=blind_view,
    )
