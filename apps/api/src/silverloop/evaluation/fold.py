"""Folding one policy over one scenario's replayed steps, with an optional uniform budget.

Split out of `runner.py` so `sweep.py` can reuse it without a circular import. Nothing here knows
about arms, scenario sets or reporting.
"""

from __future__ import annotations

from datetime import date, timedelta

from silverloop.evaluation.metrics import CONTACT, DecisionRecord
from silverloop.evaluation.protocol import PolicyEntry
from silverloop.evaluation.scenario_spec import EvaluationScenario
from silverloop.evaluation.simulation import EnvironmentStep
from silverloop.models import Decision

# Mirrors `sql_repository.CONTACT_CAP_WINDOW_DAYS`: a contact counts against the weekly cap while
# its scenario day is today or one of the six before it. Kept as a literal rather than imported,
# because this package must never import the database layer (`test_evaluation.py` enforces it).
CONTACT_CAP_WINDOW_DAYS = 7

BUDGET_WITHHELD_RATIONALE = (
    "Harness-applied uniform weekly contact cap reached; contact withheld so every policy is "
    "compared at the same budget."
)

STALE_PROGRAMME_RATIONALE = "No programme evidence passed the freshness gate; NO_ACTION recorded."


def fold_policy(
    entry: PolicyEntry,
    scenario: EvaluationScenario,
    steps: list[EnvironmentStep],
    *,
    cap: int | None = None,
) -> list[DecisionRecord]:
    """Fold one policy over one scenario's replayed steps.

    The running list of contact days is the ONLY per-policy mutable state (D2): it starts empty
    for every scenario and gains an entry only for this policy's own CONTACT decisions, after the
    programme-freshness demotion below has had a chance to turn a PROGRAMME_SUGGESTION into a
    NO_ACTION. Demotion happens before the append, so a demoted suggestion never inflates the
    contact count (this is what scenario 07 parity checks). The count handed to the policy is the
    number of those days inside the rolling `CONTACT_CAP_WINDOW_DAYS` window ending on the step's
    own day -- the same clock the repository keeps -- so a contact made a simulated week ago has
    left the budget, exactly as it has in the product.

    `cap` is the harness's uniform budget. When it is set, a CONTACT decision taken while the
    budget is already spent is converted to SUPPRESS and flagged `budget_withheld`. The conversion
    happens AFTER the freshness demotion, for the same reason the increment does: a suggestion that
    was never going to be sent must not consume, or appear to consume, budget. A policy that caps
    itself (`silverloop`) reaches this point already under budget, so the harness cap is a no-op
    for it -- an identity the test suite asserts rather than assumes.
    """
    records: list[DecisionRecord] = []
    contact_days: list[date] = []
    for step in steps:
        window_start = step.metric.day - timedelta(days=CONTACT_CAP_WINDOW_DAYS - 1)
        contact_count = sum(1 for day in contact_days if day >= window_start)
        window = [*step.history, step.metric]
        view_signal = entry.view(step.signal, window)
        result = entry.decide(
            view_signal,
            consent_active=step.consent_active,
            interventions_last_7_days=contact_count,
        )
        decision = result.decision
        rationale = list(result.rationale)
        if decision == Decision.PROGRAMME_SUGGESTION and not step.programme_fresh:
            decision = Decision.NO_ACTION
            rationale = [*rationale, STALE_PROGRAMME_RATIONALE]
        budget_withheld = False
        if cap is not None and decision in CONTACT and contact_count >= cap:
            decision = Decision.SUPPRESS
            rationale = [*rationale, BUDGET_WITHHELD_RATIONALE]
            budget_withheld = True
        records.append(
            DecisionRecord(
                policy=entry.name,
                scenario=scenario.name,
                step=step.step,
                person_id=step.person_id,
                event=step.event,
                label=step.label,
                decision=decision,
                support_priority=result.support_priority,
                rationale=tuple(rationale),
                consent_active=step.consent_active,
                confidence=view_signal.confidence,
                safe_to_interpret=step.signal.quality.safe_to_interpret,
                quality_evidence_id=step.signal.quality.evidence_id,
                interventions_last_7_days=contact_count,
                forbidden=step.forbidden,
                budget_withheld=budget_withheld,
            )
        )
        if decision in CONTACT:
            contact_days.append(step.metric.day)
    return records
