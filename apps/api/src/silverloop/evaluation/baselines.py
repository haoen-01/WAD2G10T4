"""Baseline policies for the evaluation harness (playbook §10).

Both baselines are evaluated on `protocol.blind_view` (see `protocol.py`): they never see the
personal median/MAD baseline that `silverloop.policy.decide` uses, because the entire point of
this comparison is to measure what naive/rule-based policies do WITHOUT that context. They return
`silverloop.policy.PolicyResult` -- there is no separate baseline result type.
"""

from __future__ import annotations

from collections.abc import Callable

from silverloop.models import Decision, SignalSummary
from silverloop.policy import PolicyResult

# Playbook §10: "Universal threshold: action if steps < 3,000".
FIXED_THRESHOLD_STEPS = 3000

# Playbook §10: "threshold plus rain/holiday/device suppressions and persistence".
CONTEXTUAL_THRESHOLD_STEPS = 3000
CONTEXTUAL_SEVERE_STEPS = 2200
CONTEXTUAL_PERSISTENT_DAYS = 3
CONTEXTUAL_EMERGING_DAYS = 2


def make_fixed_threshold(threshold: int) -> Callable[..., PolicyResult]:
    """A universal-step-threshold policy at an arbitrary cut point.

    Exists so `sweep.py` can ask the question this comparison would otherwise beg: is
    `fixed_threshold`'s poor score a fact about universal thresholds, or an artefact of the one
    number the playbook happened to quote? Sweeping the threshold answers it with a computation
    instead of an assertion.
    """

    def decide(
        signal: SignalSummary,
        *,
        consent_active: bool,
        interventions_last_7_days: int,
    ) -> PolicyResult:
        del consent_active, interventions_last_7_days
        if signal.current_steps < threshold:
            return PolicyResult(Decision.GENTLE_NUDGE, 50, [])
        return PolicyResult(Decision.NO_ACTION, 0, [])

    return decide


def fixed_threshold_decide(
    signal: SignalSummary,
    *,
    consent_active: bool,
    interventions_last_7_days: int,
) -> PolicyResult:
    """No consent check, no quality gate, no context, no contact cap -- by design.

    Both keyword arguments are accepted and deliberately ignored so this satisfies the same
    `Policy` protocol as every other entry, without pretending to use context it was never given.
    """
    del consent_active, interventions_last_7_days
    if signal.current_steps < FIXED_THRESHOLD_STEPS:
        return PolicyResult(Decision.GENTLE_NUDGE, 50, [])
    return PolicyResult(Decision.NO_ACTION, 0, [])


def contextual_rule_decide(
    signal: SignalSummary,
    *,
    consent_active: bool,
    interventions_last_7_days: int,
) -> PolicyResult:
    """Threshold plus rain/holiday suppression and blind persistence -- no personal baseline,
    no confidence gate, and deliberately NO contact cap of its own.

    Scoring note (this used to be stated dishonestly). Because this policy has no cap, counting
    `metrics.HardViolation.CONTACT_CAP_BREACH` against it in an uncapped run is grading it on an
    exam it was built to fail, and it is not evidence that Care+'s judgement is better -- only
    that Care+ was given a budget and this policy was not. The harness therefore reports a
    budget-matched arm (`runner.CAPPED_ARM`) in which the SAME weekly cap is applied uniformly to
    every policy by the harness itself, and that arm is the headline. The uncapped arm is retained
    only so the size of the budget effect is visible; `contact_cap_breach` is meaningful there as a
    description of behaviour, never as a comparative score.
    """
    del interventions_last_7_days
    if not consent_active:
        return PolicyResult(Decision.SUPPRESS, 0, [])
    if not signal.quality.safe_to_interpret:
        return PolicyResult(Decision.NO_ACTION, 0, list(signal.quality.reasons))
    if signal.context.rainy or signal.context.holiday:
        return PolicyResult(Decision.NO_ACTION, 10, [])
    if signal.current_steps >= CONTEXTUAL_THRESHOLD_STEPS:
        return PolicyResult(Decision.NO_ACTION, 0, [])
    if (
        signal.sustained_low_days >= CONTEXTUAL_PERSISTENT_DAYS
        and signal.current_steps < CONTEXTUAL_SEVERE_STEPS
    ):
        return PolicyResult(Decision.COORDINATOR_REVIEW, 80, [])
    if signal.sustained_low_days >= CONTEXTUAL_EMERGING_DAYS:
        return PolicyResult(Decision.PROGRAMME_SUGGESTION, 55, [])
    return PolicyResult(Decision.GENTLE_NUDGE, 30, [])
